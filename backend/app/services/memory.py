"""
Project memory: writing approved reports in, and reading scoped knowledge back out.

Two operations and one rule.

**Ingestion is approval-gated.** `ingest_report` refuses anything not marked COMPLETED,
which is only reachable after a human approved the draft. The check is here as well as in
the caller because it is the property the whole feature rests on — drafts and rejected work
must be *provably* absent from retrieval, not absent by convention.

**A report is a report, whichever pipeline produced it.** Memory is keyed on
`source_report_id`, which is polymorphic across both run tables. It used to carry a foreign
key to `sessions`, so reports from the current runtime could not be indexed at all: they
counted as approved, nothing could ever index them, and Chat answered from an empty store
while `memory/status` reported a backlog that only grew.

**Isolation is a SQL boundary.** Every read filters `WHERE project_id = :project_id`
before a single character reaches a model. A prompt-level "only use Project X"
instruction is not a security control and is not treated as one (docs/06 §4).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

import structlog
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.memory_chunk import MemoryChunk
from app.models.research import ResearchRun
from app.models.session import Session, SessionStatus
from research_engine.chunking import chunk_report
from research_engine.embeddings import EmbeddingsUnavailable
from research_engine.ports import Embeddings

logger = structlog.get_logger()

# How many chunks a chat turn retrieves. docs/14 §5 says "start 8"; it rides in every
# prompt, so it is also a cost knob — eight ~300-token chunks is ~2.4k tokens of context.
DEFAULT_TOP_K = 8

# Cosine distance above which a chunk is not a match by any reading. Normalised embeddings
# put unrelated text near 1.0 and opposed text above it, so this drops results that are
# worse than orthogonal rather than encoding a guess about what "relevant" means.
#
# It was briefly tightened to 0.45 on the reasoning that a smaller number "filters out
# noisy background matches". Nothing had been measured against a real embedding model, and
# the number did not filter noise — it filtered the answer: a question asked of the project
# that owns the report retrieved nothing at all. A retrieval ceiling is a measurement claim
# like any other, and an unmeasured one silently reports "no memory" for memory that is
# there. Tighten this only with a benchmark that says what it costs; `test_retrieval_ceiling
# _admits_a_genuine_match` is the floor that keeps a guess from landing again.
MAX_COSINE_DISTANCE = 1.0


def is_available(db: AsyncSession) -> bool:
    """Whether this host has project memory at all.

    Memory is pgvector-backed, so it exists on the server and not on the desktop app —
    a decision stated in the parity tables, in the release notes and in the UI, not an
    outage. One home for the check: a caller that writes its own dialect test is a caller
    that will disagree with this one the day the storage changes.
    """
    return db.bind is not None and db.bind.dialect.name == "postgresql"


@dataclass(frozen=True)
class IngestResult:
    """What one ingestion attempt did. `skipped` is a success, not a failure."""

    chunks_written: int = 0
    skipped: bool = False
    reason: str | None = None


@dataclass(frozen=True)
class SourceReport:
    """Just enough of the report a chunk came from to cite it.

    A named three-field record rather than the ORM row, because the row can come from
    either run table and a caller that reaches for `.prompt` on one and `.question` on the
    other is a caller that works until the day the other kind shows up.
    """

    id: uuid.UUID
    title: str
    created_at: datetime
    #: `"run"` or `"session"`. Carried because a citation has to link somewhere, and the
    #: two kinds live on different routes — a marker that opens nothing is the failure the
    #: whole citation apparatus exists to prevent.
    kind: str


@dataclass(frozen=True)
class Retrieved:
    """One retrieved chunk with the report it came from, ready to cite as [R{n}]."""

    chunk: MemoryChunk
    distance: float
    report: SourceReport


async def ingest_report(
    db: AsyncSession,
    *,
    project_id: uuid.UUID,
    report_id: uuid.UUID,
    report_markdown: str,
    embedder: Embeddings,
    force: bool = False,
) -> IngestResult:
    """Embed one approved report into its project's memory.

    Approval is the caller's to establish — `ingest_session` and `ingest_run` each check
    the status their own table records — and this function does the mechanics for both, so
    there is one chunking rule, one batching rule and one replacement rule rather than a
    copy per pipeline.

    Idempotent. Re-ingesting a report already indexed under the current embedding model is
    skipped rather than repeated: approving twice (a double-click, a redelivered task) must
    not double the store or the bill. `force=True` re-indexes, which is what a provider
    switch needs.

    Raises `EmbeddingsUnavailable` if there is no provider; the caller decides whether that
    is fatal. It is not fatal at the end of a run — the research already succeeded and is
    already saved, so an un-indexed report is a gap to report, not a run to fail.
    """
    report = (report_markdown or "").strip()
    if not report:
        return IngestResult(skipped=True, reason="no final report text")

    if not force:
        existing = (
            await db.execute(
                select(func.count())
                .select_from(MemoryChunk)
                .where(
                    MemoryChunk.source_report_id == report_id,
                    MemoryChunk.embedding_model == embedder.model_id,
                )
            )
        ).scalar_one()
        if existing:
            return IngestResult(skipped=True, reason="already indexed with this model")

    chunks = chunk_report(report)
    if not chunks:
        return IngestResult(skipped=True, reason="report produced no chunks")

    # One batched call for the whole report rather than one per chunk.
    vectors = await embedder.embed(chunks)
    if len(vectors) != len(chunks):
        raise EmbeddingsUnavailable(
            f"Embedder returned {len(vectors)} vectors for {len(chunks)} chunks."
        )

    # Replace wholesale: a re-index with a different chunk count would otherwise leave
    # the tail of the previous run behind, and those stale rows are unreachable garbage
    # that still gets retrieved.
    await db.execute(delete(MemoryChunk).where(MemoryChunk.source_report_id == report_id))
    db.add_all(
        [
            MemoryChunk(
                project_id=project_id,
                source_report_id=report_id,
                chunk_index=index,
                text=text,
                embedding=vector,
                embedding_model=embedder.model_id,
            )
            for index, (text, vector) in enumerate(zip(chunks, vectors, strict=True))
        ]
    )
    await db.commit()
    logger.info(
        "memory_ingested",
        project_id=str(project_id),
        report_id=str(report_id),
        chunks=len(chunks),
        model=embedder.model_id,
    )
    return IngestResult(chunks_written=len(chunks))


async def ingest_session(
    db: AsyncSession,
    session: Session,
    embedder: Embeddings,
    *,
    force: bool = False,
) -> IngestResult:
    """Approval gate for a session, then the shared mechanics."""
    if session.status != SessionStatus.COMPLETED:
        # The load-bearing guard. Everything else is mechanics.
        return IngestResult(skipped=True, reason=f"status is {session.status}, not COMPLETED")
    return await ingest_report(
        db,
        project_id=session.project_id,
        report_id=session.id,
        report_markdown=session.final_report or "",
        embedder=embedder,
        force=force,
    )


async def ingest_run(
    db: AsyncSession,
    run: ResearchRun,
    report_markdown: str,
    embedder: Embeddings,
    *,
    force: bool = False,
) -> IngestResult:
    """Approval gate for a run, then the shared mechanics.

    The report text is passed in rather than read off `run`: a run keeps its report on the
    latest `Revision`, and the caller already holds the revision it just approved. Reading
    it again here would risk indexing a *different* version from the one the human saw.
    """
    if run.status != "COMPLETED":
        return IngestResult(skipped=True, reason=f"status is {run.status}, not COMPLETED")
    return await ingest_report(
        db,
        project_id=run.project_id,
        report_id=run.id,
        report_markdown=report_markdown,
        embedder=embedder,
        force=force,
    )


async def _resolve_reports(db: AsyncSession, ids: list[uuid.UUID]) -> dict[uuid.UUID, SourceReport]:
    """Titles and dates for a set of report ids, looked up in both run tables.

    Two small `IN` queries rather than a join, because `source_report_id` is polymorphic
    and there is no single table to join to. An id present in neither table is simply
    absent from the result — its chunk is then dropped by the caller rather than cited to a
    report nobody can open.
    """
    if not ids:
        return {}
    found: dict[uuid.UUID, SourceReport] = {}
    for row in (
        (await db.execute(select(ResearchRun).where(ResearchRun.id.in_(ids)))).scalars().all()
    ):
        found[row.id] = SourceReport(
            id=row.id, title=row.question, created_at=row.created_at, kind="run"
        )
    for row in (await db.execute(select(Session).where(Session.id.in_(ids)))).scalars().all():
        found.setdefault(
            row.id,
            SourceReport(id=row.id, title=row.prompt, created_at=row.created_at, kind="session"),
        )
    return found


async def retrieve(
    db: AsyncSession,
    *,
    project_id: uuid.UUID,
    query_vector: list[float],
    embedding_model: str,
    limit: int = DEFAULT_TOP_K,
) -> list[Retrieved]:
    """Nearest chunks *within one project*, with the report each came from attached.

    The `project_id` predicate and the ownership check that precedes it are the isolation
    boundary. `embedding_model` is filtered too: chunks written by a different model are
    not comparable to this query vector, and silently ranking them together would produce
    confident nonsense rather than an obvious error.
    """
    distance = MemoryChunk.embedding.cosine_distance(query_vector).label("distance")
    rows = (
        await db.execute(
            select(MemoryChunk, distance)
            .where(
                MemoryChunk.project_id == project_id,
                MemoryChunk.embedding_model == embedding_model,
                distance <= MAX_COSINE_DISTANCE,
            )
            .order_by(distance)
            .limit(limit)
        )
    ).all()

    reports = await _resolve_reports(db, [chunk.source_report_id for chunk, _ in rows])
    # A chunk whose report has gone is dropped, not cited: a grounding block naming a
    # report the reader cannot open is exactly the unresolvable citation this product
    # exists to make impossible.
    return [
        Retrieved(chunk=chunk, distance=float(dist), report=reports[chunk.source_report_id])
        for chunk, dist in rows
        if chunk.source_report_id in reports
    ]


@dataclass(frozen=True)
class MemoryStatus:
    """What `GET /projects/{id}/memory/status` reports (docs/14 §8).

    `pending_reports` is derived rather than stored: approved reports minus distinct
    indexed ones. That keeps a failed ingestion visible without a status column to keep
    in sync, and it self-heals — a later re-index simply makes the number fall.
    """

    chunk_count: int
    indexed_reports: int
    approved_reports: int
    pending_reports: int
    current_model: str
    models: list[dict]
    last_ingest_at: datetime | None
    stale_models: list[str]


async def status(db: AsyncSession, *, project_id: uuid.UUID, current_model: str) -> MemoryStatus:
    """Make memory legible rather than magic: what is indexed, and what is still pending."""
    norm_pid = uuid.UUID(str(project_id))
    by_model = (
        await db.execute(
            select(
                MemoryChunk.embedding_model,
                func.count(),
                func.count(func.distinct(MemoryChunk.source_report_id)),
                func.max(MemoryChunk.created_at),
            )
            .where(MemoryChunk.project_id == norm_pid)
            .group_by(MemoryChunk.embedding_model)
        )
    ).all()

    session_approved = (
        await db.execute(
            select(func.count())
            .select_from(Session)
            .where(Session.project_id == norm_pid, Session.status == SessionStatus.COMPLETED)
        )
    ).scalar_one()

    run_approved = (
        await db.execute(
            select(func.count())
            .select_from(ResearchRun)
            .where(ResearchRun.project_id == norm_pid, ResearchRun.status == "COMPLETED")
        )
    ).scalar_one()

    approved = session_approved + run_approved

    pg_chunks = sum(chunks for _, chunks, _, _ in by_model)
    pg_indexed = sum(reports for model, _, reports, _ in by_model if model == current_model)

    # These numbers describe **project memory**, and nothing else. They were briefly
    # `max(memory, corpus)`, which made the card read "2 reports indexed" while the memory
    # table held one — the corpus is a different store with a different purpose and its own
    # card, and blending the two reported a coverage the retrieval this card describes did
    # not have. That is the unmeasured-as-measured failure, in the surface whose whole job
    # is to say what memory knows.
    pending = max(approved - pg_indexed, 0)

    models_list = [
        {"embedding_model": model, "chunks": chunks, "reports": reports}
        for model, chunks, reports, _ in sorted(by_model, key=lambda row: row[0])
    ]

    latest_ingest = max((ts for *_, ts in by_model if ts), default=None)
    stale = sorted({model for model, *_ in by_model if model != current_model})

    return MemoryStatus(
        chunk_count=pg_chunks,
        indexed_reports=pg_indexed,
        approved_reports=approved,
        pending_reports=pending,
        current_model=current_model,
        models=models_list,
        last_ingest_at=latest_ingest,
        stale_models=stale,
    )
