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

import pytest
from langgraph.checkpoint.memory import MemorySaver

from research_engine.corpus import CorpusStore, parse_corpus_url, reset_corpus, set_corpus
from research_engine.embeddings import EmbeddingsUnavailable, LocalEmbeddings
from research_engine.runconfig import RunConfig, reset_run_config, set_run_config
from research_engine.runner import run
from research_engine.tools import read_webpage, web_search
from tests.test_corpus_store import SOLAR_TEXT, VENTS_TEXT, FakeEmbeddings

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
