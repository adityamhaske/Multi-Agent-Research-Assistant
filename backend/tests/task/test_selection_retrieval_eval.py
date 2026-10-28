"""
`evals/selection_retrieval.py` scores what it claims to (RFC V3.1 §17).

The eval needs a real embedder and is run by hand, so these pin its arithmetic and its
dataset without one:
- leakage is the share of hits outside the selection, and `None`, never 0, for no hits;
- document metrics read each file once, so a capped ranking cannot score above perfect;
- passage recall counts overlaps with verbatim anchors;
- the dataset's selections, grades and anchors all name real text.
"""

from __future__ import annotations

import json

import pytest

from evals import selection_retrieval as ev
from research_engine.corpus import CorpusStore
from research_engine.documents import extract
from tests.dataflow.test_corpus_store import FakeEmbeddings

DATA = json.loads(ev.DATASET.read_text(encoding="utf-8"))


def _hit(file, start=0, end=100):
    return {"file": file, "start": start, "end": end}


def test_a_file_returned_twice_is_ranked_once():
    scores = ev._scores([_hit("a.md"), _hit("a.md", 100, 200), _hit("b.md")], {"a.md": 2}, {})
    assert scores["ndcg@5"] <= 1.0
    assert scores["passages"] == 3
    assert scores["recall"]["@1"] == 1.0


def test_passage_recall_counts_overlap_with_each_anchor():
    anchors = {"a.md": [[10, 20], [500, 520]]}
    assert ev._passage_recall([_hit("a.md", 0, 50)], anchors) == 0.5
    assert ev._passage_recall([_hit("a.md", 0, 50), _hit("a.md", 480, 600)], anchors) == 1.0
    assert ev._passage_recall([_hit("b.md", 0, 1000)], anchors) == 0.0
    assert ev._passage_recall([_hit("a.md")], {}) is None


def test_leakage_with_no_hits_is_unmeasured_not_zero():
    scored = ev._scores([], {}, {})
    rows = [
        {"leakage": None, "with_cap": scored, "one_per_document": scored},
        {"leakage": 0.0, "with_cap": scored, "one_per_document": scored},
        {"leakage": 0.25, "with_cap": scored, "one_per_document": scored},
    ]
    leak = ev.aggregate(rows)["leakage"]
    assert leak["max"] == 0.25
    assert (leak["queries_measured"], leak["queries_with_no_hits"]) == (2, 1)
    assert leak["queries_leaking"] == 1
    assert ev.aggregate(rows[:1])["leakage"]["max"] is None, "no measurement is not a 0"


async def test_a_leak_would_be_measured(tmp_path):
    """The query path the eval uses reports an outside file when one comes back, so a 0 from
    it is a measurement. Driven with a store whose `search` ignores the selection."""
    store = CorpusStore(tmp_path / "c.sqlite", FakeEmbeddings())
    inside = await store.ingest("in.txt", b"Enrolment rose 12% in 2021.")
    outside = await store.ingest("out.txt", b"Enrolment rose 12% in 2021 across the district.")

    class Leaky(CorpusStore):
        async def search(self, query, max_results, *, document_ids=None, per_document=1):
            return await super().search(query, max_results)

    leaky = Leaky(tmp_path / "c.sqlite", FakeEmbeddings())
    ids = {"in.txt": inside.doc_id, "out.txt": outside.doc_id}
    names = {v: k for k, v in ids.items()}
    query = {"id": "q", "query": "enrolment 2021", "selection": ["in.txt"], "grades": {}}
    row = await ev.evaluate_query(leaky, query, ids, names)
    assert row["leakage"] and row["leakage"] > 0
    assert row["outside_selection"] == ["out.txt"]


def test_every_selection_grade_and_anchor_names_real_text():
    files = {p.name: p for p in ev._corpus_files(DATA)}
    for query in DATA["queries"]:
        assert set(query["selection"]) <= set(files), query["id"]
        assert set(query["grades"]) <= set(query["selection"]), query["id"]
        for name, anchors in query.get("passage_anchors", {}).items():
            text = extract(name, files[name].read_bytes()).text
            for anchor in anchors:
                assert anchor in text, (query["id"], anchor)


@pytest.mark.parametrize("query", DATA["queries"], ids=[q["id"] for q in DATA["queries"]])
def test_every_query_has_something_outside_its_selection_to_leak(query):
    """A selection holding the whole corpus could not leak, and would measure nothing."""
    assert len(ev._corpus_files(DATA)) > len(query["selection"])
