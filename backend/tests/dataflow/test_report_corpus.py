"""
Auto-saving an approved report into its project's corpus (app/services/report_corpus.py).

The load-bearing property under test is the one AGENTS.md calls P0: an approved report
must be saveable to its project's corpus WITHOUT becoming citable evidence for the next
report. `origin="generated"` is the mechanism; `_search_sync`'s `origin != 'generated'`
filter (research_engine/corpus.py) is where it is enforced. These tests prove the filter
holds even in the adversarial case — a generated document that is the closest possible
match to the query — because that is exactly the shape of a report citing itself.
"""

from __future__ import annotations

import pytest

from app.services.report_corpus import ingest_report
from research_engine.corpus import CorpusStore
from tests.dataflow.test_corpus_store import FakeEmbeddings

pytestmark = pytest.mark.asyncio


async def test_ingest_report_writes_a_document_tagged_generated(tmp_path):
    store = CorpusStore(tmp_path / "corpus.sqlite", FakeEmbeddings())
    result = await ingest_report(
        store, session_id="s1", report_markdown="# Solar Report\n\nSolar power is growing."
    )
    assert result is not None and not result.skipped

    docs = await store.documents()
    assert len(docs) == 1
    assert docs[0]["origin"] == "generated"
    assert docs[0]["filename"] == "report-s1.md"


async def test_a_generated_report_never_surfaces_as_a_search_result(tmp_path):
    """The adversarial case: the generated report is a near-verbatim match for the next
    query, and must still be excluded — an exact-content match is the case a citation
    resolves cleanly against, which is exactly what makes self-citation dangerous.

    A corpus holding only generated reports raises rather than returning an empty list —
    the same "loud failure over silent emptiness" the store already uses for an empty or
    wrong-model corpus (`_search_sync`), and the error says why in terms a user can act on.
    """
    store = CorpusStore(tmp_path / "corpus.sqlite", FakeEmbeddings())
    verbatim = "Solar power capacity has grown for three decades running."
    await ingest_report(store, session_id="s1", report_markdown=verbatim)

    with pytest.raises(RuntimeError, match="only auto-saved reports"):
        await store.search(verbatim, max_results=5)


async def test_a_generated_report_is_excluded_alongside_a_real_uploaded_match(tmp_path):
    """The non-degenerate case: an uploaded document is present, so search succeeds — and
    a generated report that would otherwise be the closer match must still not appear."""
    store = CorpusStore(tmp_path / "corpus.sqlite", FakeEmbeddings())
    real = "Wind turbines convert kinetic energy into electricity."
    await store.ingest("wind.txt", real.encode("utf-8"))
    verbatim = "Solar power capacity has grown for three decades running."
    await ingest_report(store, session_id="s1", report_markdown=verbatim)

    # Query the uploaded document's own text, not the generated report's — FakeEmbeddings
    # is bag-of-words with no shared vocabulary between "wind" and "solar", so a solar
    # query would score both at ~0 and prove nothing either way.
    results = await store.search(real, max_results=5)
    assert [r["title"] for r in results] == ["wind.txt"], (
        "only the uploaded document may surface, never the generated report"
    )


async def test_an_uploaded_document_still_surfaces_normally(tmp_path):
    """Confirms the exclusion is scoped to `origin='generated'`, not a regression that
    broke retrieval altogether."""
    store = CorpusStore(tmp_path / "corpus.sqlite", FakeEmbeddings())
    text = "Solar power capacity has grown for three decades running."
    await store.ingest("upload.txt", text.encode("utf-8"))  # default origin="uploaded"

    results = await store.search(text, max_results=5)
    assert len(results) == 1
    assert results[0]["title"] == "upload.txt"


async def test_ingest_report_is_idempotent_per_session(tmp_path):
    """A retried approval (duplicate webhook, retried Celery task) must not double the
    corpus — `CorpusStore` dedupes on (filename, sha256), and the filename is keyed by
    session id specifically so this holds."""
    store = CorpusStore(tmp_path / "corpus.sqlite", FakeEmbeddings())
    await ingest_report(store, session_id="s1", report_markdown="same content")
    second = await ingest_report(store, session_id="s1", report_markdown="same content")

    assert second is not None and second.skipped
    docs = await store.documents()
    assert len(docs) == 1


async def test_ingest_report_never_raises_and_returns_none_on_failure(tmp_path, monkeypatch):
    """A failed save must not propagate — see the module docstring: an already-approved
    run must not fail retroactively because the corpus write did not work."""
    store = CorpusStore(tmp_path / "corpus.sqlite", FakeEmbeddings())

    async def _boom(*args, **kwargs):
        raise RuntimeError("disk full")

    monkeypatch.setattr(store, "ingest", _boom)
    result = await ingest_report(store, session_id="s1", report_markdown="content")
    assert result is None


async def test_ingest_report_skips_a_blank_report(tmp_path):
    """No text, nothing to embed or store — must be a clean no-op, not an empty document
    or a chunking failure."""
    store = CorpusStore(tmp_path / "corpus.sqlite", FakeEmbeddings())
    result = await ingest_report(store, session_id="s1", report_markdown="   ")
    assert result is None
    assert await store.documents() == []
