"""
Fake mode must not embed against a live provider.

Found by running `./start.sh --fake` — advertised as "keyless demo mode (scripted models,
no API key needed)" — and uploading a document. The API raised:

    EmbeddingsUnavailable: Embedding provider 'google' failed: 404 NOT_FOUND
    models/text-embedding-004 is not found for API version v1beta

`app.adapters.embeddings_for` never consulted `llm_mode`, so a demo run built a real
`HostedEmbeddings` from whatever key happened to be in `.env`. Two things wrong with that,
and the 404 is the lesser one:

1. **It spends.** A user who ran the keyless demo, with a valid key present, was billed
   for embeddings on a run the product told them was free and offline. `llm_mode="fake"`
   gates every model call in the engine precisely so a demo reaches no provider; corpus
   ingestion went around that gate because it lives in a host adapter.
2. **It fails closed on a broken key, which looks like a broken product.** The demo path
   is the first thing a new user touches, and it died on a provider error about a model
   nobody chose.

Fixed by giving fake mode a deterministic in-process embedder. Deterministic rather than
random because the corpus is a *retrieval* store: identical text must land in the same
place across a restart, or a demo's search results change under it for no reason.
"""

from __future__ import annotations

import math

import pytest

from research_engine.embeddings import FakeEmbeddings


@pytest.mark.asyncio
async def test_the_same_text_always_embeds_to_the_same_vector():
    """A restart must not move a document. `MemorySaver`-style randomness would make a
    demo's retrieval results differ between launches for no reason the user can see."""
    a = await FakeEmbeddings().embed(["grounding metrics"])
    b = await FakeEmbeddings().embed(["grounding metrics"])
    assert a == b


@pytest.mark.asyncio
async def test_different_texts_embed_differently():
    """Otherwise every chunk collides and retrieval returns arbitrary rows — a demo that
    appears to work while proving nothing, which is worse than one that fails."""
    vectors = await FakeEmbeddings().embed(["grounding metrics", "retrieval recall"])
    assert vectors[0] != vectors[1]


@pytest.mark.asyncio
async def test_vectors_are_unit_length_and_uniform_width():
    """Cosine similarity over the corpus assumes both. `CorpusStore` stacks the vectors
    into one matrix, so a ragged width is a hard failure at search time, not ingest."""
    vectors = await FakeEmbeddings().embed(["one", "two", "a much longer passage of text"])
    assert len({len(v) for v in vectors}) == 1, "ragged vectors break the search matrix"
    for v in vectors:
        assert math.isclose(math.sqrt(sum(x * x for x in v)), 1.0, rel_tol=1e-6)


def test_it_declares_itself_local_so_the_airgap_guard_accepts_it():
    """The corpus egress guard defaults to *remote* for any embedder that does not
    declare itself local (AGENTS.md). An in-process embedder that forgot to say so would
    be refused in corpus mode — the guard doing its job against the wrong target."""
    assert FakeEmbeddings().is_local is True


def test_its_model_id_passes_the_corpus_mode_check_and_names_itself_fake():
    """`pipeline_runner` admits corpus mode only for `ollama:`/`local:` model ids, so the
    prefix has to be one of those — and the rest of the id has to say "fake", because a
    model id is what gets recorded as the thing that ran."""
    model_id = FakeEmbeddings().model_id
    assert model_id.startswith("local:")
    assert "fake" in model_id


@pytest.mark.asyncio
async def test_embedding_nothing_returns_nothing():
    assert await FakeEmbeddings().embed([]) == []


@pytest.mark.asyncio
async def test_fake_mode_never_builds_a_hosted_embedder(monkeypatch):
    """The actual defect: `embeddings_for` ignored `llm_mode` entirely.

    Asserted with a Google key deliberately present, because that is the configuration
    that broke — a developer's real `.env` plus `--fake`. Without the key the old code
    would have fallen through to `NoEmbeddings` and this test would pass against the bug.
    """
    from app import adapters
    from app.config import settings

    monkeypatch.setattr(settings, "llm_mode", "fake")
    monkeypatch.setattr(settings, "google_api_key", "a-real-looking-key")
    monkeypatch.setattr(settings, "embeddings_provider", "auto")

    embedder = await adapters.embeddings_for({"google": "another-real-looking-key"})

    assert isinstance(embedder, FakeEmbeddings)
    assert embedder.is_local is True


@pytest.mark.asyncio
async def test_real_mode_is_untouched(monkeypatch):
    """The bypass must be exactly one branch wide: a real run with a key still gets the
    hosted embedder it always did."""
    from app import adapters
    from app.adapters import HostedEmbeddings
    from app.config import settings

    monkeypatch.setattr(settings, "llm_mode", "real")
    monkeypatch.setattr(settings, "embeddings_provider", "google")
    monkeypatch.setattr(settings, "google_api_key", "a-real-looking-key")

    embedder = await adapters.embeddings_for()

    assert isinstance(embedder, HostedEmbeddings)
