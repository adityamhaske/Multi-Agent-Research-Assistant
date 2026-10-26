"""
A run's selection is enforced at the corpus port (internal/rfcs/V3.1-corpus-scope.md §8.4).

Every test here drives a REAL `CorpusStore` on a real SQLite file. The thing under test is
which rows the store's own query admits, so stubbing `search`/`read` would replace exactly
the code that decides (root AGENTS.md: a test that stubs the thing it tests proves nothing).
"""

from __future__ import annotations

import pytest

from research_engine.corpus import OUTSIDE_SELECTION, CorpusStore, ScopedCorpus, corpus_url
from tests.dataflow.test_corpus_store import SOLAR_TEXT, VENTS_TEXT, FakeEmbeddings

TIDES_TEXT = (
    "Tidal power captures the energy of moving sea water. Barrages across estuaries hold "
    "back the rising tide and release it through turbines, while tidal stream generators "
    "sit on the seabed like underwater wind turbines. Tides are predictable decades ahead."
)


@pytest.fixture
async def store(tmp_path) -> CorpusStore:
    return CorpusStore(tmp_path / "corpus.sqlite", FakeEmbeddings())


async def _ingest(store: CorpusStore, name: str, text: str, **kw) -> str:
    result = await store.ingest(name, text.encode(), **kw)
    return result.doc_id


async def test_search_returns_only_selected_documents(store):
    solar = await _ingest(store, "solar.txt", SOLAR_TEXT)
    await _ingest(store, "vents.txt", VENTS_TEXT)
    await _ingest(store, "tides.txt", TIDES_TEXT)

    scoped = ScopedCorpus(store, frozenset({solar}))
    # A query that matches the UNSELECTED documents far better than the selected one:
    # if the filter leaked, these would rank first.
    hits = await scoped.search(
        "tidal turbines hydrothermal vent bacteria electricity", max_results=5
    )

    assert hits, "the selected document is still searchable"
    assert {h["url"].split("#")[0] for h in hits} == {f"corpus://{solar}"}


async def test_read_refuses_a_document_outside_the_selection(store):
    solar = await _ingest(store, "solar.txt", SOLAR_TEXT)
    vents = await _ingest(store, "vents.txt", VENTS_TEXT)
    scoped = ScopedCorpus(store, frozenset({solar}))

    # A well-formed URL for a real, unselected document — what an invented or injected
    # citation looks like. The bare store would serve it.
    url = corpus_url(vents, start=0, end=40, page=None)
    assert (await store.read(url))["error"] is None, "precondition: the store itself serves it"

    page = await scoped.read(url)
    assert page["error"] == OUTSIDE_SELECTION
    assert page["text"] == "" and page["title"] == "", "a refusal carries nothing quotable"

    own = await scoped.read(corpus_url(solar, start=0, end=40, page=None))
    assert own["error"] is None and SOLAR_TEXT[:40] in own["text"]


async def test_refusal_does_not_reveal_whether_a_document_exists(store):
    solar = await _ingest(store, "solar.txt", SOLAR_TEXT)
    vents = await _ingest(store, "vents.txt", VENTS_TEXT)
    scoped = ScopedCorpus(store, frozenset({solar}))

    real = await scoped.read(corpus_url(vents, start=0, end=10, page=None))
    missing = await scoped.read(corpus_url("no-such-document", start=0, end=10, page=None))
    assert real["error"] == missing["error"] == OUTSIDE_SELECTION


async def test_a_selected_version_stays_readable_and_searchable_after_it_is_superseded(store):
    first = await store.ingest("paper.txt", SOLAR_TEXT.encode())
    scoped = ScopedCorpus(store, frozenset({first.doc_id}))

    # A newer version arrives mid-run. The run's frozen selection names the OLD version.
    newer = await store.ingest("paper.txt", TIDES_TEXT.encode(), doc_key=first.doc_key)
    assert newer.doc_id != first.doc_id

    hits = await scoped.search("photovoltaic silicon sunlight", max_results=3)
    assert {h["url"].split("#")[0] for h in hits} == {f"corpus://{first.doc_id}"}
    # ...and the new version, which the run was never given, is refused.
    assert (await scoped.read(corpus_url(newer.doc_id, start=0, end=10, page=None)))[
        "error"
    ] == OUTSIDE_SELECTION


async def test_an_unselected_superseded_version_is_refused(store):
    first = await store.ingest("paper.txt", SOLAR_TEXT.encode())
    newer = await store.ingest("paper.txt", TIDES_TEXT.encode(), doc_key=first.doc_key)
    scoped = ScopedCorpus(store, frozenset({newer.doc_id}))

    page = await scoped.read(corpus_url(first.doc_id, start=0, end=10, page=None))
    assert page["error"] == OUTSIDE_SELECTION


async def test_a_generated_report_is_never_evidence_even_when_selected(store):
    report = await _ingest(store, "report-1.md", TIDES_TEXT, origin="generated")
    scoped = ScopedCorpus(store, frozenset({report}))

    with pytest.raises(RuntimeError, match="auto-saved reports"):
        await scoped.search("tidal turbines", max_results=3)


async def test_selection_diagnostics_describe_the_selection_not_the_corpus(store):
    await _ingest(store, "solar.txt", SOLAR_TEXT)
    scoped = ScopedCorpus(store, frozenset({"deleted-document-id"}))

    with pytest.raises(RuntimeError) as err:
        await scoped.search("photovoltaic", max_results=3)
    message = str(err.value)
    assert "selected" in message
    assert "corpus is empty" not in message, "the corpus is not empty; the selection is"


async def test_selection_indexed_with_another_model_says_so(tmp_path):
    path = tmp_path / "corpus.sqlite"
    old = CorpusStore(path, FakeEmbeddings(name="old"))
    doc = await _ingest(old, "solar.txt", SOLAR_TEXT)

    scoped = ScopedCorpus(CorpusStore(path, FakeEmbeddings(name="new")), frozenset({doc}))
    with pytest.raises(RuntimeError, match="different embedding model"):
        await scoped.search("photovoltaic", max_results=3)


async def test_a_large_selection_does_not_hit_the_sqlite_parameter_limit(store):
    solar = await _ingest(store, "solar.txt", SOLAR_TEXT)
    # Well past SQLite's default host-parameter limit if the ids were bound one by one.
    many = frozenset({solar, *(f"absent-{i}" for i in range(40_000))})

    hits = await ScopedCorpus(store, many).search("photovoltaic", max_results=3)
    assert {h["url"].split("#")[0] for h in hits} == {f"corpus://{solar}"}


def test_an_empty_selection_is_refused(store):
    with pytest.raises(ValueError, match="at least one"):
        ScopedCorpus(store, frozenset())


async def test_unscoped_search_is_unchanged(store):
    solar = await _ingest(store, "solar.txt", SOLAR_TEXT)
    vents = await _ingest(store, "vents.txt", VENTS_TEXT)

    hits = await store.search("sunlight", max_results=5)
    assert {h["url"].split("#")[0] for h in hits} == {f"corpus://{solar}", f"corpus://{vents}"}
