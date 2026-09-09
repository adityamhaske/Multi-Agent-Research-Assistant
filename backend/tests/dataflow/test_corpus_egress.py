"""
Zero-egress proof for corpus-only mode (docs/12 M10 DoD).

The DoD says a network-egress test must prove zero outbound connections in
corpus-only mode. The guard below records every `socket.connect` and DNS lookup
the process attempts and fails the test at the moment one leaves loopback — so
the proof is not "the run finished" but "the run never reached for the network".

The pipeline itself runs in fake LLM mode with a REAL corpus store: the scripted
executor searches the store and submits its corpus:// locations as evidence, so
the assertions about citations resolve against actual document bytes.
"""

from __future__ import annotations

import socket
import uuid
from datetime import UTC, datetime

import pytest
from langgraph.checkpoint.memory import MemorySaver
from sqlalchemy import insert

from app import run_execution, run_lifecycle
from app.models.project import Project
from app.models.session import Session as SessionRow
from app.models.user import User
from research_engine import retrievers
from research_engine.corpus import CorpusStore, parse_corpus_url, reset_corpus, set_corpus
from research_engine.embeddings import EmbeddingsUnavailable, LocalEmbeddings
from research_engine.runconfig import RunConfig, reset_run_config, set_run_config
from research_engine.runner import run
from research_engine.tools import read_webpage, web_search
from tests.dataflow.test_corpus_store import SOLAR_TEXT, VENTS_TEXT, FakeEmbeddings
from tests.sqlite_support import open_db

_LOOPBACK = {"127.0.0.1", "::1", "localhost"}


@pytest.fixture
def no_egress(monkeypatch):
    """Record every outbound connection/DNS attempt; only loopback may proceed.

    Anything non-loopback raises immediately — the test fails at the attempt,
    not after it succeeds.
    """
    attempts: list[str] = []
    real_connect = socket.socket.connect
    real_getaddrinfo = socket.getaddrinfo

    def guarded_connect(self, address):
        host = str(address[0] if isinstance(address, tuple) else address)
        attempts.append(host)
        if host in _LOOPBACK:
            return real_connect(self, address)
        raise AssertionError(f"network egress attempted by corpus-only code path: {host}")

    def guarded_getaddrinfo(host, *args, **kwargs):
        attempts.append(str(host))
        if str(host) in _LOOPBACK:
            return real_getaddrinfo(host, *args, **kwargs)
        raise AssertionError(f"DNS resolution attempted by corpus-only code path: {host}")

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    monkeypatch.setattr(socket, "getaddrinfo", guarded_getaddrinfo)
    return attempts


@pytest.fixture
async def corpus_store(tmp_path) -> CorpusStore:
    store = CorpusStore(tmp_path / "corpus.sqlite", FakeEmbeddings())
    await store.ingest("solar.txt", SOLAR_TEXT.encode())
    await store.ingest("vents.txt", VENTS_TEXT.encode())
    return store


@pytest.mark.asyncio
async def test_corpus_only_run_zero_egress_and_exact_citations(corpus_store, no_egress):
    outcome = await run(
        checkpointer=MemorySaver(),
        session_id="corpus-egress",
        user_id="u",
        query="How do photovoltaic cells convert sunlight?",
        run_config=RunConfig(llm_mode="fake", corpus_mode=True),
        corpus=corpus_store,
    )

    assert no_egress == [], f"a corpus-only run opened sockets to: {no_egress}"
    assert outcome.status == "awaiting_approval", "the HITL gate is unchanged by corpus mode"
    assert outcome.error is None

    # Every citation is a corpus location, and every one resolves to the exact
    # document position whose text contains the cited snippet (docs/12 M10 DoD).
    assert outcome.sources, "corpus evidence must surface as numbered sources"
    for source in outcome.sources:
        assert source["url"].startswith("corpus://"), source["url"]
        assert parse_corpus_url(source["url"]) is not None
        resolved = await corpus_store.read(source["url"])
        assert resolved["error"] is None, resolved
        snippets = source["snippets"] or [source["snippet"]]
        for snippet in snippets:
            assert snippet in resolved["text"], (
                f"citation {source['url']} does not resolve to its exact location"
            )


@pytest.mark.asyncio
async def test_read_webpage_refuses_the_web_in_corpus_mode(corpus_store, no_egress):
    cfg = RunConfig(llm_mode="fake", corpus_mode=True)
    token_cfg = set_run_config(cfg)
    token_corpus = set_corpus(corpus_store)
    try:
        blocked = await read_webpage.ainvoke({"url": "https://example.com/looks-plausible"})
        assert blocked["error"] and "corpus-only" in blocked["error"]

        # A corpus location still resolves — it is the only thing readable.
        hits = await corpus_store.search("photovoltaic sunlight", max_results=1)
        assert hits
        page = await read_webpage.ainvoke({"url": hits[0]["url"]})
        assert page["error"] is None and hits[0]["snippet"] in page["text"]
    finally:
        reset_corpus(token_corpus)
        reset_run_config(token_cfg)

    assert no_egress == []


class RemoteEmbeddings(FakeEmbeddings):
    """A hosted embedder, i.e. what `HostedEmbeddings` is when EMBEDDINGS_PROVIDER is
    google or openai. Computes locally so the test needs no network — the point is the
    *declaration*, which is what the airgap guard reads."""

    is_local = False

    @property
    def model_id(self) -> str:
        return "google:text-embedding-004"


@pytest.mark.asyncio
async def test_corpus_mode_refuses_a_remote_embedder(tmp_path, no_egress):
    """The hole this suite could not see until M18.

    The query embedding is the one model call corpus retrieval makes, and the original
    test injected a FakeEmbeddings — stubbing out precisely the call that egresses. So a
    server with EMBEDDINGS_PROVIDER=google shipped a "no network calls at all" claim while
    sending every corpus query to a hosted API, and this file stayed green.

    Corpus mode must now refuse rather than quietly phone out.
    """
    store = CorpusStore(tmp_path / "corpus.sqlite", RemoteEmbeddings())
    await store.ingest("solar.txt", SOLAR_TEXT.encode())

    token = set_run_config(RunConfig(llm_mode="fake", corpus_mode=True))
    try:
        with pytest.raises(EmbeddingsUnavailable, match="zero network calls"):
            await store.search("photovoltaic sunlight", max_results=1)
    finally:
        reset_run_config(token)

    assert no_egress == [], "the refusal must happen before any socket is opened"


@pytest.mark.asyncio
async def test_remote_embedder_is_allowed_outside_corpus_mode(tmp_path):
    """Only corpus-only mode makes the zero-egress promise. A hosted embedder is the
    normal, correct choice for ordinary project memory, so the guard must stay silent."""
    store = CorpusStore(tmp_path / "corpus.sqlite", RemoteEmbeddings())
    await store.ingest("solar.txt", SOLAR_TEXT.encode())

    token = set_run_config(RunConfig(llm_mode="fake", corpus_mode=False))
    try:
        hits = await store.search("photovoltaic sunlight", max_results=1)
        assert hits, "a non-airgapped run must still be able to search the corpus"
    finally:
        reset_run_config(token)


def test_locality_is_decided_by_endpoint_not_class_name():
    """`LocalEmbeddings` is named for its intent, not its configuration: point
    OLLAMA_BASE_URL at a remote host and it is a network client wearing a local name."""
    assert LocalEmbeddings("nomic-embed-text", "http://localhost:11434/v1").is_local
    assert LocalEmbeddings("nomic-embed-text", "http://127.0.0.1:11434/v1").is_local
    # map_local_host rewrites localhost to this inside a container.
    assert LocalEmbeddings("nomic-embed-text", "http://host.docker.internal:11434/v1").is_local
    assert not LocalEmbeddings("nomic-embed-text", "https://ollama.example.com/v1").is_local
    assert not LocalEmbeddings("nomic-embed-text", "http://10.0.0.5:11434/v1").is_local


@pytest.mark.asyncio
async def test_search_fails_closed_when_no_corpus_installed(no_egress):
    """corpus_mode with nothing installed must fail loudly, never fall back to the web."""
    cfg = RunConfig(llm_mode="fake", corpus_mode=True)
    token = set_run_config(cfg)
    try:
        result = await web_search.ainvoke({"query": "anything", "max_results": 3})
        assert len(result) == 1
        assert "no corpus is installed" in result[0]["snippet"]
    finally:
        reset_run_config(token)

    assert no_egress == []


# ── The host wiring ───────────────────────────────────────────────────────────────
#
# Every test above builds `RunConfig(corpus_mode=True)` by hand — the one thing a real
# request never does. A request sets `corpus_mode` on the *row*; something then has to
# carry it from the row into the engine config, because `retrievers.search` and
# `read_webpage` both branch on `get_run_config().corpus_mode` and neither can see a
# database. That hop is what these tests drive.
#
# Its absence is why this file stayed green while the server shipped the defect: installing
# the corpus *port* (which `execute_run` and `pipeline_runner._execute` both did) only
# decides what `get_corpus()` answers — it does not make anything ask. AGENTS.md names the
# class: "a test that stubs the thing it is testing proves nothing", and a hand-built
# `RunConfig` stubs exactly the hop that was broken.


class _SessionDb:
    """Enough AsyncSession for `_run_config_for`, which commits the routing snapshot.

    Mirrors `test_scripted_runs_are_recorded_as_demo._Db`. The session builder takes no
    ORM row from the database — it is handed one — so the only database work under test is
    the routing snapshot commit.
    """

    async def commit(self) -> None:
        return None

    async def execute(self, *_a, **_k):
        class _R:
            def scalar_one_or_none(self):
                return None

        return _R()


@pytest.fixture
async def server_run(tmp_path):
    """A real `research_runs` row, created the way `POST /runs` creates one."""
    async with open_db(tmp_path / "airgap.sqlite") as maker, maker() as db:
        now = datetime(2026, 9, 9, tzinfo=UTC)
        uid, pid = uuid.uuid4(), uuid.uuid4()
        await db.execute(
            insert(User).values(
                id=uid, email=f"{uid}@x.invalid", hashed_pw="x", is_active=True, created_at=now
            )
        )
        await db.execute(
            insert(Project).values(id=pid, user_id=uid, name="P", created_at=now, updated_at=now)
        )
        await db.commit()
        row = await run_lifecycle.create_run(
            db, owner_id=uid, project_id=pid, question="q", depth="fast", corpus_mode=True
        )
        await db.commit()
        yield db, row


async def test_a_run_row_asking_for_corpus_mode_produces_a_corpus_mode_config(server_run):
    """The runs pipeline, on both hosts. The defect as it shipped on the server."""
    db, row = server_run
    assert row.corpus_mode is True, "fixture precondition"

    cfg = await run_execution.run_config_for_run(db, row)

    assert cfg.corpus_mode is True, (
        "the run is recorded as airgapped and the engine config says otherwise — "
        "`retrievers.search` would run the web chain and `read_webpage` would fetch it"
    )


async def test_a_session_row_asking_for_corpus_mode_produces_a_corpus_mode_config():
    """The sessions pipeline, server-side. Same defect, second home."""
    import app.workers.pipeline_runner as runner_mod

    row = SessionRow(prompt="q", research_depth="fast")
    row.corpus_mode = True
    row.demo = False

    cfg = await runner_mod._run_config_for(_SessionDb(), row, str(uuid.uuid4()))

    assert cfg.corpus_mode is True, "a session recorded as airgapped would research the open web"


async def test_a_run_that_did_not_ask_for_corpus_mode_is_not_silently_restricted(tmp_path):
    """The control, and it is not decoration.

    Unconditionally setting `corpus_mode=True` would pass the two tests above and break
    every ordinary run into an airgapped one. The desktop's own corpus-mode fix shipped
    with this same control for the same reason.
    """
    async with open_db(tmp_path / "open.sqlite") as maker, maker() as db:
        now = datetime(2026, 9, 9, tzinfo=UTC)
        uid, pid = uuid.uuid4(), uuid.uuid4()
        await db.execute(
            insert(User).values(
                id=uid, email=f"{uid}@x.invalid", hashed_pw="x", is_active=True, created_at=now
            )
        )
        await db.execute(
            insert(Project).values(id=pid, user_id=uid, name="P", created_at=now, updated_at=now)
        )
        await db.commit()
        row = await run_lifecycle.create_run(
            db, owner_id=uid, project_id=pid, question="q", depth="fast"
        )
        await db.commit()

        cfg = await run_execution.run_config_for_run(db, row)

    assert cfg.corpus_mode is False, "an ordinary run must still reach the web"


async def test_a_session_that_did_not_ask_for_corpus_mode_is_not_silently_restricted():
    import app.workers.pipeline_runner as runner_mod

    row = SessionRow(prompt="q", research_depth="fast")
    row.corpus_mode = False
    row.demo = False

    cfg = await runner_mod._run_config_for(_SessionDb(), row, str(uuid.uuid4()))

    assert cfg.corpus_mode is False


async def test_the_config_the_server_builds_makes_retrieval_corpus_only(
    server_run, corpus_store, no_egress
):
    """The whole hop, end to end: row → host config builder → engine → zero egress.

    The two assertions above prove the field arrives. This proves the field *does* what the
    airgap promise says, using the config the server actually builds rather than one this
    test wrote — which is the difference between the version of this file that caught the
    defect and the version that did not.
    """
    db, row = server_run
    cfg = await run_execution.run_config_for_run(db, row)

    token_cfg = set_run_config(cfg)
    token_corpus = set_corpus(corpus_store)
    try:
        hits = await retrievers.search("photovoltaic sunlight", max_results=2)
        assert hits, "the corpus must answer an airgapped search"
        for hit in hits:
            assert hit["url"].startswith("corpus://"), (
                f"an airgapped run retrieved a non-corpus source: {hit['url']}"
            )

        blocked = await read_webpage.ainvoke({"url": "https://example.com/looks-plausible"})
        assert blocked["error"] and "corpus-only" in blocked["error"]
    finally:
        reset_corpus(token_corpus)
        reset_run_config(token_cfg)

    assert no_egress == [], f"an airgapped run opened sockets to: {no_egress}"
