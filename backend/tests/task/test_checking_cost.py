"""
`evals/checking_cost.py` measures what gate G-5 asks (RFC V3.1 §14.1, §14.3).

The measurement needs a real model and refuses a scripted one. This drives one selection
run per size through the real graph with scripted models, the deterministic embedder and
the shipped grounding check, and pins the plumbing:
- a run's §9 time and calls come back from its grounding report;
- "without §9" is that run less its own §9 share;
- an unpriced route's cost is reported unmeasured, never as $0.00.
"""

from __future__ import annotations

import pytest

from evals import checking_cost as cc
from research_engine.corpus import CorpusStore
from research_engine.runconfig import RunConfig
from tests.dataflow.test_corpus_store import FakeEmbeddings


@pytest.fixture
async def store(tmp_path):
    s = CorpusStore(tmp_path / "c.sqlite", FakeEmbeddings())
    # The scripted planner always researches retrieval-augmented generation, so the first
    # file, which every selection here includes, is the one that answers it.
    rag = next(p for p in cc.CORPUS if p.name == "retrieval-augmented-generation.md")
    paths = [rag, *[p for p in cc.CORPUS if p is not rag][:11]]
    ids = [(await s.ingest(p.name, p.read_bytes())).doc_id for p in paths]
    return s, ids


async def test_a_selection_run_reports_its_check_apart_from_its_research(store):
    s, ids = store
    rows = [
        await cc.one_run(s, ids, size, cc.QUESTIONS[0], RunConfig(llm_mode="fake"))
        for size in (1, 3, 10)
    ]
    for r in rows:
        assert r["status"] == "awaiting_approval", r["error"]
        assert r["grounding_status"] == "complete"
        assert r["check_calls"] >= 1 and r["check_seconds"] is not None
        assert 0 <= r["check_seconds"] <= r["wall_seconds"]

    summary = cc.summarise(rows, priced=False)
    assert summary["cost_measured"] is False
    assert all(v["check_cost_usd_median"] is None for v in summary["by_selection_size"].values())
    p50 = summary["latency_p50"]
    assert p50["without_check"] <= p50["with_check"]


def test_the_corpus_is_large_enough_for_a_fifty_file_selection():
    assert len(cc.CORPUS) >= max(cc.SIZES)
    assert len({p.name for p in cc.CORPUS}) == len(cc.CORPUS), "a filename is a document identity"


def test_a_custom_or_openrouter_route_is_unpriced():
    assert not cc._priced("custom:auto/best-fast")
    assert not cc._priced("openrouter:any/model")
    assert cc._priced("anthropic:claude-sonnet-4-5")
