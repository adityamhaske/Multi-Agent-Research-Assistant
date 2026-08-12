"""
Project memory: the Definition of Done, as executable assertions (docs/14 §9).

Every claim project chat makes rests on two properties that are invisible from the
outside until they fail:

1. **A project's memory contains only its own approved research.** Isolation is a SQL
   predicate; a test that mocked the query would prove nothing about it.
2. **Rejected and draft work never reaches retrieval.** This is the whole reason memory
   here is trustworthy where "AI remembers everything" is not.

Both are asserted against a live Postgres with pgvector, because both are properties *of
the database*. The suite skips with a reason when there isn't one (see `conftest.py`).

What these tests deliberately do not assert: that a language model, handed correct
excerpts, writes a correct answer with correct markers. That is a model-quality question
measured by the eval harness against a real model, not something a fake LLM in CI can
demonstrate. What is tested here is everything the model is handed and everything done
with what it returns.
"""

from __future__ import annotations

import uuid
import zlib

import pytest
from sqlalchemy import func, select, text

from app.models.chat_message import ChatMessage
from app.models.chat_thread import ChatThread, derive_title
from app.models.memory_chunk import MemoryChunk
from app.models.project import Project
from app.models.session import Session, SessionStatus
from app.models.user import User
from app.services import memory
from research_engine.embeddings import EmbeddingsUnavailable, NoEmbeddings
from research_engine.ports import Embeddings
from tests.conftest import requires_db

pytestmark = requires_db

DIMENSIONS = 768


class StubEmbeddings:
    """A deterministic, dependency-free stand-in with real retrieval behaviour.

    Hashes tokens into a fixed-width vector, so texts sharing vocabulary land near each
    other and unrelated texts do not. That is enough for nearest-neighbour ordering to
    mean something in a test without a model, a key or a network call — and it is
    reproducible, which a real embedding service is not.
    """

    model_id = "stub:hash-768"
    dimensions = DIMENSIONS

    def __init__(self, model_id: str | None = None) -> None:
        if model_id:
            self.model_id = model_id

    @staticmethod
    def _vector(text_value: str) -> list[float]:
        vector = [0.0] * DIMENSIONS
        tokens = [t for t in "".join(c if c.isalnum() else " " for c in text_value).split() if t]
        for token in tokens:
            digest = zlib.crc32(token.lower().encode())
            # Signed contributions, so unrelated texts can sit beyond orthogonal exactly
            # as real embeddings do — otherwise the distance ceiling is never exercised.
            vector[digest % DIMENSIONS] += 1.0 if digest % 2 else -1.0
        norm = sum(value * value for value in vector) ** 0.5
        return [value / norm for value in vector] if norm else [1.0] + [0.0] * (DIMENSIONS - 1)

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(t) for t in texts]


SOLAR_REPORT = """# Solar Capacity 2025

Global solar photovoltaic capacity grew 32 percent during 2025 [1]. The expansion was
driven overwhelmingly by grid-scale installations in China, which accounted for roughly
half of all new capacity added worldwide [2].

## Limitations

The underlying dataset stops at the third quarter [3]. Fourth-quarter figures are
extrapolated and have not been independently audited.
"""

TAX_REPORT = """# Corporate Tax Residency Rules

Corporate tax residency is determined by the place of effective management in most
European jurisdictions [1]. Ireland applies an incorporation test alongside the
management test, which produces occasional dual-residency conflicts [2].

## Limitations

Case law after 2024 was not reviewed [3]. Treaty tie-breaker clauses vary by bilateral
agreement and were treated as out of scope.
"""


async def make_user(db, email: str | None = None) -> User:
    user = User(email=email or f"{uuid.uuid4().hex[:12]}@example.test", hashed_pw="x")
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def make_project(db, user: User, name: str) -> Project:
    project = Project(user_id=user.id, name=name)
    db.add(project)
    await db.commit()
    await db.refresh(project)
    return project


async def make_session(
    db,
    project: Project,
    user: User,
    *,
    prompt: str,
    status: SessionStatus = SessionStatus.COMPLETED,
    final_report: str | None = None,
    draft_report: str | None = None,
) -> Session:
    session = Session(
        user_id=user.id,
        project_id=project.id,
        prompt=prompt,
        status=status,
        final_report=final_report,
        draft_report=draft_report,
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session


async def chunk_count(db, project_id: uuid.UUID) -> int:
    return (
        await db.execute(
            select(func.count())
            .select_from(MemoryChunk)
            .where(MemoryChunk.project_id == project_id)
        )
    ).scalar_one()


# ── The port contract ──────────────────────────────────────────────────────────────


def test_adapters_satisfy_the_embeddings_port():
    """Structural conformance, the same check the other two ports get."""
    from app import adapters

    assert isinstance(adapters.OllamaEmbeddings("nomic-embed-text", "http://x/v1"), Embeddings)
    assert isinstance(adapters.HostedEmbeddings("google", "text-embedding-004", "k"), Embeddings)
    assert isinstance(StubEmbeddings(), Embeddings)


async def test_absent_provider_raises_instead_of_returning_nothing():
    """The fail-closed rule: an empty corpus and a broken one must not look identical."""
    with pytest.raises(EmbeddingsUnavailable):
        await NoEmbeddings().embed(["anything"])


async def test_wrong_width_vectors_are_refused_with_an_actionable_message():
    from app import adapters

    with pytest.raises(EmbeddingsUnavailable) as excinfo:
        adapters._check_width([[0.0] * 512], "some:model")
    assert "512" in str(excinfo.value)
    assert str(adapters.EMBEDDING_DIMENSIONS) in str(excinfo.value)


# ── Ingestion is approval-gated ────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "status",
    [
        SessionStatus.AWAITING_APPROVAL,
        SessionStatus.RUNNING,
        SessionStatus.FAILED,
        SessionStatus.PENDING,
    ],
)
async def test_only_completed_sessions_are_ingested(db, status):
    """A draft awaiting review, a live run and a failure all stay out of memory."""
    user = await make_user(db)
    project = await make_project(db, user, "P")
    session = await make_session(
        db, project, user, prompt="q", status=status, draft_report=SOLAR_REPORT
    )

    result = await memory.ingest_session(db, session, StubEmbeddings())

    assert result.skipped
    assert result.chunks_written == 0
    assert await chunk_count(db, project.id) == 0


async def test_rejected_draft_is_provably_absent_from_retrieval(db):
    """DoD: 'rejected/draft reports are provably absent from retrieval'.

    The strong form of the check — not just "ingestion refused", but "a question whose
    answer is only in the rejected draft retrieves nothing".
    """
    user = await make_user(db)
    project = await make_project(db, user, "Energy")
    rejected = await make_session(
        db,
        project,
        user,
        prompt="solar capacity growth",
        status=SessionStatus.AWAITING_APPROVAL,
        draft_report=SOLAR_REPORT,
    )
    embedder = StubEmbeddings()
    await memory.ingest_session(db, rejected, embedder)

    query = (await embedder.embed(["How fast did solar capacity grow in 2025?"]))[0]
    hits = await memory.retrieve(
        db, project_id=project.id, query_vector=query, embedding_model=embedder.model_id
    )
    assert hits == []


async def test_approved_report_is_ingested_and_retrievable(db):
    user = await make_user(db)
    project = await make_project(db, user, "Energy")
    session = await make_session(
        db, project, user, prompt="solar capacity growth", final_report=SOLAR_REPORT
    )
    embedder = StubEmbeddings()

    result = await memory.ingest_session(db, session, embedder)
    assert result.chunks_written > 0

    query = (await embedder.embed(["How fast did solar photovoltaic capacity grow?"]))[0]
    hits = await memory.retrieve(
        db, project_id=project.id, query_vector=query, embedding_model=embedder.model_id
    )
    assert hits
    assert all(hit.session.id == session.id for hit in hits)
    assert "solar" in hits[0].chunk.text.lower()


async def test_ingestion_is_idempotent(db):
    """Approving twice — a double-click, a redelivered Celery task — must not double the
    corpus or re-run the embedding bill."""
    user = await make_user(db)
    project = await make_project(db, user, "Energy")
    session = await make_session(db, project, user, prompt="q", final_report=SOLAR_REPORT)
    embedder = StubEmbeddings()

    first = await memory.ingest_session(db, session, embedder)
    second = await memory.ingest_session(db, session, embedder)

    assert first.chunks_written > 0
    assert second.skipped
    assert await chunk_count(db, project.id) == first.chunks_written


async def test_reindex_replaces_rather_than_accumulates(db):
    """A forced re-index must not leave the previous run's tail behind as dead rows.

    The first report is deliberately long enough to span several chunks — re-indexing to
    a shorter one is the case where stale high-index rows would survive.
    """
    user = await make_user(db)
    project = await make_project(db, user, "Energy")
    session = await make_session(db, project, user, prompt="q", final_report=SOLAR_REPORT * 5)
    embedder = StubEmbeddings()
    await memory.ingest_session(db, session, embedder)
    before = await chunk_count(db, project.id)
    assert before > 1, "fixture must span multiple chunks for this test to mean anything"

    session.final_report = "# Tiny\n\nOne short approved finding about solar output."
    await db.commit()
    await memory.ingest_session(db, session, embedder, force=True)

    after = await chunk_count(db, project.id)
    assert after < before
    remaining = (
        (await db.execute(select(MemoryChunk).where(MemoryChunk.source_session_id == session.id)))
        .scalars()
        .all()
    )
    assert [c.chunk_index for c in remaining] == list(range(len(remaining)))


# ── Isolation ──────────────────────────────────────────────────────────────────────


async def test_cross_project_isolation(db):
    """DoD: a question about a report in a *different* project returns nothing here.

    The automated isolation test docs/14 §9 requires. Both projects belong to the same
    user, which is the case that a per-user check alone would wave through.
    """
    user = await make_user(db)
    energy = await make_project(db, user, "Energy")
    tax = await make_project(db, user, "Tax")
    embedder = StubEmbeddings()

    solar = await make_session(db, energy, user, prompt="solar", final_report=SOLAR_REPORT)
    residency = await make_session(db, tax, user, prompt="tax residency", final_report=TAX_REPORT)
    await memory.ingest_session(db, solar, embedder)
    await memory.ingest_session(db, residency, embedder)

    question = (await embedder.embed(["What determines corporate tax residency in Ireland?"]))[0]

    from_tax = await memory.retrieve(
        db, project_id=tax.id, query_vector=question, embedding_model=embedder.model_id
    )
    assert from_tax, "the project that owns this research should answer"
    assert {hit.session.id for hit in from_tax} == {residency.id}

    from_energy = await memory.retrieve(
        db, project_id=energy.id, query_vector=question, embedding_model=embedder.model_id
    )
    assert all(hit.session.id == solar.id for hit in from_energy)
    assert residency.id not in {hit.session.id for hit in from_energy}


async def test_another_users_project_is_not_retrievable(db):
    """The same predicate also holds across accounts, not only across one user's projects."""
    alice = await make_user(db)
    bob = await make_user(db)
    alice_project = await make_project(db, alice, "Energy")
    bob_project = await make_project(db, bob, "Energy")
    embedder = StubEmbeddings()

    session = await make_session(
        db, alice_project, alice, prompt="solar", final_report=SOLAR_REPORT
    )
    await memory.ingest_session(db, session, embedder)

    question = (await embedder.embed(["How fast did solar capacity grow?"]))[0]
    hits = await memory.retrieve(
        db, project_id=bob_project.id, query_vector=question, embedding_model=embedder.model_id
    )
    assert hits == []


async def test_vectors_from_another_embedding_model_are_not_ranked(db):
    """Equal width is not equal meaning — mixing models would return confident nonsense."""
    user = await make_user(db)
    project = await make_project(db, user, "Energy")
    session = await make_session(db, project, user, prompt="solar", final_report=SOLAR_REPORT)
    await memory.ingest_session(db, session, StubEmbeddings("stub:old-model"))

    current = StubEmbeddings("stub:new-model")
    question = (await current.embed(["How fast did solar capacity grow?"]))[0]
    hits = await memory.retrieve(
        db, project_id=project.id, query_vector=question, embedding_model=current.model_id
    )
    assert hits == []


# ── Deletion leaves nothing behind ─────────────────────────────────────────────────


async def test_deleting_a_project_deletes_its_memory(db):
    """DoD: 'deleting a project deletes its memory (no orphan vectors)'."""
    user = await make_user(db)
    project = await make_project(db, user, "Energy")
    session = await make_session(db, project, user, prompt="solar", final_report=SOLAR_REPORT)
    await memory.ingest_session(db, session, StubEmbeddings())
    assert await chunk_count(db, project.id) > 0

    await db.delete(project)
    await db.commit()

    total = (await db.execute(select(func.count()).select_from(MemoryChunk))).scalar_one()
    assert total == 0


async def test_deleting_a_session_deletes_only_its_chunks(db):
    user = await make_user(db)
    project = await make_project(db, user, "Energy")
    embedder = StubEmbeddings()
    solar = await make_session(db, project, user, prompt="solar", final_report=SOLAR_REPORT)
    tax = await make_session(db, project, user, prompt="tax", final_report=TAX_REPORT)
    await memory.ingest_session(db, solar, embedder)
    await memory.ingest_session(db, tax, embedder)

    await db.delete(solar)
    await db.commit()

    survivors = (await db.execute(select(MemoryChunk.source_session_id).distinct())).scalars().all()
    assert survivors == [tax.id]


# ── Status makes gaps visible ──────────────────────────────────────────────────────


async def test_status_counts_an_unindexed_report_as_pending(db):
    """A failed ingestion has to be visible somewhere, or it is discovered as 'chat can't
    find my research'."""
    user = await make_user(db)
    project = await make_project(db, user, "Energy")
    embedder = StubEmbeddings()
    indexed = await make_session(db, project, user, prompt="solar", final_report=SOLAR_REPORT)
    await make_session(db, project, user, prompt="tax", final_report=TAX_REPORT)
    await memory.ingest_session(db, indexed, embedder)

    status = await memory.status(db, project_id=project.id, current_model=embedder.model_id)

    assert status.approved_reports == 2
    assert status.indexed_reports == 1
    assert status.pending_reports == 1
    assert status.chunk_count > 0


async def test_status_flags_chunks_written_by_a_retired_model(db):
    user = await make_user(db)
    project = await make_project(db, user, "Energy")
    session = await make_session(db, project, user, prompt="solar", final_report=SOLAR_REPORT)
    await memory.ingest_session(db, session, StubEmbeddings("stub:old-model"))

    status = await memory.status(db, project_id=project.id, current_model="stub:new-model")

    assert status.stale_models == ["stub:old-model"]
    assert status.indexed_reports == 0
    assert status.pending_reports == 1


# ── Citations resolve ──────────────────────────────────────────────────────────────


async def test_grounding_markers_resolve_to_their_reports(db):
    """[R1] must name a real approved report, with the excerpt it was drawn from."""
    from app.api.v1.threads import _grounding

    user = await make_user(db)
    project = await make_project(db, user, "Energy")
    embedder = StubEmbeddings()
    session = await make_session(
        db, project, user, prompt="solar capacity growth", final_report=SOLAR_REPORT
    )
    await memory.ingest_session(db, session, embedder)

    question = (await embedder.embed(["How fast did solar capacity grow?"]))[0]
    hits = await memory.retrieve(
        db, project_id=project.id, query_vector=question, embedding_model=embedder.model_id
    )
    excerpts, citations = _grounding(hits)

    assert citations
    assert [c["marker"] for c in citations] == [f"R{i}" for i in range(1, len(citations) + 1)]
    for citation in citations:
        assert citation["session_id"] == str(session.id)
        assert citation["title"] == "solar capacity growth"
        assert citation["excerpt"] in excerpts
    assert "[R1]" in excerpts


# ── Threads, and the compatibility promise ─────────────────────────────────────────


async def test_thread_messages_and_report_messages_coexist(db):
    """DoD: existing sessions still open, chat and export after the migration."""
    user = await make_user(db)
    project = await make_project(db, user, "Energy")
    session = await make_session(db, project, user, prompt="solar", final_report=SOLAR_REPORT)
    thread = ChatThread(project_id=project.id, title="New chat")
    db.add(thread)
    await db.commit()
    await db.refresh(thread)

    db.add(ChatMessage(session_id=session.id, role="user", content="legacy per-report chat"))
    db.add(ChatMessage(thread_id=thread.id, role="user", content="project thread chat"))
    await db.commit()

    legacy = (
        (await db.execute(select(ChatMessage).where(ChatMessage.session_id == session.id)))
        .scalars()
        .all()
    )
    threaded = (
        (await db.execute(select(ChatMessage).where(ChatMessage.thread_id == thread.id)))
        .scalars()
        .all()
    )
    assert len(legacy) == 1
    assert len(threaded) == 1


async def test_a_message_must_belong_to_exactly_one_conversation(db):
    """Both-null or both-set would be a message that shows up in no history, or two."""
    from sqlalchemy.exc import IntegrityError

    user = await make_user(db)
    project = await make_project(db, user, "Energy")
    session = await make_session(db, project, user, prompt="solar", final_report=SOLAR_REPORT)
    thread = ChatThread(project_id=project.id, title="t")
    db.add(thread)
    await db.commit()
    await db.refresh(thread)

    for kwargs in ({}, {"session_id": session.id, "thread_id": thread.id}):
        db.add(ChatMessage(role="user", content="orphan", **kwargs))
        with pytest.raises(IntegrityError):
            await db.commit()
        await db.rollback()


async def test_deleting_a_project_deletes_its_threads(db):
    user = await make_user(db)
    project = await make_project(db, user, "Energy")
    thread = ChatThread(project_id=project.id, title="t")
    db.add(thread)
    await db.commit()

    await db.delete(project)
    await db.commit()

    remaining = (await db.execute(select(func.count()).select_from(ChatThread))).scalar_one()
    assert remaining == 0


def test_thread_titles_come_from_the_first_message():
    assert derive_title("What did we conclude about solar?") == "What did we conclude about solar?"
    assert derive_title("") == "New chat"
    long_title = derive_title("word " * 40)
    assert len(long_title) <= 61
    assert long_title.endswith("…")


async def test_pgvector_extension_is_actually_installed(db):
    """The prerequisite 0006 exists to guarantee — asserted, not assumed."""
    version = (
        await db.execute(text("SELECT extversion FROM pg_extension WHERE extname = 'vector'"))
    ).scalar()
    assert version is not None
