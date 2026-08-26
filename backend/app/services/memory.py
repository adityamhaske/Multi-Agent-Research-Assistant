"""
Project memory: writing approved reports in, and reading scoped knowledge back out
(docs/14 §2, §4, §5).

Two operations and one rule.

**Ingestion is approval-gated.** `ingest_session` refuses anything whose status is not
COMPLETED, which in this pipeline is only reachable after a human approved the draft
(`graph.route_after_gate` sends approvals to the finalizer and everything else back to
the synthesizer). The check is here as well as in the caller because it is the property
the whole feature rests on — drafts and rejected work must be *provably* absent from
retrieval, not absent by convention (docs/14 §9).

**Isolation is a SQL boundary.** Every read filters `WHERE project_id = :project_id`
before a single character reaches a model. A prompt-level "only use Project X"
instruction is not a security control and is not treated as one (docs/06 §4).
"""

from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime

import structlog
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
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

# Maximum cosine distance for a chunk to be considered relevant (0 = identical, 2 = opposite).
# 0.4 filters out noisy background matches while retaining genuine semantic relevance.
MAX_COSINE_DISTANCE = 0.45


@dataclass(frozen=True)
class IngestResult:
    """What one ingestion attempt did. `skipped` is a success, not a failure."""

    chunks_written: int = 0
    skipped: bool = False
    reason: str | None = None


@dataclass(frozen=True)
class Retrieved:
    """One retrieved chunk with the report it came from, ready to cite as [R{n}]."""

    chunk: MemoryChunk
    distance: float
    session: Session


async def ingest_session(
    db: AsyncSession,
    session: Session,
    embedder: Embeddings,
    *,
    force: bool = False,
) -> IngestResult:
    """Embed an approved report into its project's memory.

    Idempotent. Re-ingesting a report that is already indexed under the current embedding
    model is skipped rather than repeated — approving twice (a double-click, a redelivered
    Celery task) must not double the corpus or the bill. `force=True` re-indexes, which is
    what a provider switch needs.

    Raises `EmbeddingsUnavailable` if there is no provider; the caller decides whether
    that is fatal. It is not fatal at the end of a run: the research already succeeded and
    is already saved, so an un-indexed report is a gap to report, not a run to fail.
    """
    if session.status != SessionStatus.COMPLETED:
        # The load-bearing guard. Everything else here is mechanics.
        return IngestResult(skipped=True, reason=f"status is {session.status}, not COMPLETED")

    report = (session.final_report or "").strip()
    if not report:
        return IngestResult(skipped=True, reason="no final report text")

    if not force:
        existing = (
            await db.execute(
                select(func.count())
                .select_from(MemoryChunk)
                .where(
                    MemoryChunk.source_session_id == session.id,
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
    await db.execute(delete(MemoryChunk).where(MemoryChunk.source_session_id == session.id))
    db.add_all(
        [
            MemoryChunk(
                project_id=session.project_id,
                source_session_id=session.id,
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
        session_id=str(session.id),
        project_id=str(session.project_id),
        chunks=len(chunks),
        model=embedder.model_id,
    )
    return IngestResult(chunks_written=len(chunks))


async def retrieve(
    db: AsyncSession,
    *,
    project_id: uuid.UUID,
    query_vector: list[float],
    embedding_model: str,
    limit: int = DEFAULT_TOP_K,
) -> list[Retrieved]:
    """Nearest chunks *within one project*, newest-report metadata attached.

    The `project_id` predicate and the ownership check that precedes it are the isolation
    boundary (docs/14 §5). `embedding_model` is filtered too: chunks written by a
    different model are not comparable to this query vector, and silently ranking them
    together would produce confident nonsense rather than an obvious error.
    """
    distance = MemoryChunk.embedding.cosine_distance(query_vector).label("distance")
    rows = (
        await db.execute(
            select(MemoryChunk, distance, Session)
            .join(Session, Session.id == MemoryChunk.source_session_id)
            .where(
                MemoryChunk.project_id == project_id,
                MemoryChunk.embedding_model == embedding_model,
                distance <= MAX_COSINE_DISTANCE,
            )
            .order_by(distance)
            .limit(limit)
        )
    ).all()
    return [
        Retrieved(chunk=chunk, distance=float(dist), session=sess) for chunk, dist, sess in rows
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
    """Make memory legible rather than magic (docs/14 §8)."""
    norm_pid = uuid.UUID(str(project_id))
    by_model = (
        await db.execute(
            select(
                MemoryChunk.embedding_model,
                func.count(),
                func.count(func.distinct(MemoryChunk.source_session_id)),
                func.max(MemoryChunk.created_at),
            )
            .where(MemoryChunk.project_id == norm_pid)
            .group_by(MemoryChunk.embedding_model)
        )
    ).all()

    v1_approved = (
        await db.execute(
            select(func.count())
            .select_from(Session)
            .where(Session.project_id == norm_pid, Session.status == SessionStatus.COMPLETED)
        )
    ).scalar_one()

    v2_approved = (
        await db.execute(
            select(func.count())
            .select_from(ResearchRun)
            .where(ResearchRun.project_id == norm_pid, ResearchRun.status == "COMPLETED")
        )
    ).scalar_one()

    approved = v1_approved + v2_approved

    pg_chunks = sum(chunks for _, chunks, _, _ in by_model)
    pg_indexed = sum(reports for model, _, reports, _ in by_model if model == current_model)

    corpus_file = settings.corpus_path / f"corpus_{norm_pid}.sqlite"
    sqlite_generated = 0
    sqlite_chunks = 0
    sqlite_model = current_model
    sqlite_latest_ts = None
    if corpus_file.exists():
        try:
            with sqlite3.connect(corpus_file) as conn:
                sqlite_generated = conn.execute(
                    "SELECT count(*) FROM corpus_documents WHERE origin = 'generated'"
                ).fetchone()[0]
                chunk_row = conn.execute(
                    "SELECT count(*) FROM corpus_chunks WHERE embedding_model = ?",
                    (current_model,),
                ).fetchone()
                if chunk_row and chunk_row[0] > 0:
                    sqlite_chunks = chunk_row[0]
                else:
                    any_chunk_row = conn.execute(
                        "SELECT count(*), embedding_model FROM corpus_chunks GROUP BY embedding_model"
                    ).fetchone()
                    if any_chunk_row:
                        sqlite_chunks = any_chunk_row[0]
                        sqlite_model = any_chunk_row[1] or current_model
                doc_row = conn.execute("SELECT max(ingested_at) FROM corpus_documents").fetchone()
                if doc_row and doc_row[0]:
                    try:
                        sqlite_latest_ts = datetime.fromisoformat(doc_row[0])
                    except Exception:
                        pass
        except Exception as e:
            logger.warning("corpus_status_read_failed", project_id=str(project_id), error=str(e))

    total_indexed = max(pg_indexed, sqlite_generated)
    total_chunks = max(pg_chunks, sqlite_chunks)
    pending = max(approved - total_indexed, 0)

    models_list = [
        {"embedding_model": model, "chunks": chunks, "reports": reports}
        for model, chunks, reports, _ in sorted(by_model, key=lambda row: row[0])
    ]
    if not models_list and sqlite_chunks > 0:
        models_list = [
            {"embedding_model": sqlite_model, "chunks": sqlite_chunks, "reports": sqlite_generated}
        ]

    pg_latest = max((ts for *_, ts in by_model if ts), default=None)
    latest_ingest = pg_latest or sqlite_latest_ts

    stale = sorted({model for model, *_ in by_model if model != current_model})
    if not by_model and sqlite_chunks > 0 and sqlite_model != current_model:
        stale = [sqlite_model]

    return MemoryStatus(
        chunk_count=total_chunks,
        indexed_reports=total_indexed,
        approved_reports=approved,
        pending_reports=pending,
        current_model=current_model,
        models=models_list,
        last_ingest_at=latest_ingest,
        stale_models=stale,
    )
