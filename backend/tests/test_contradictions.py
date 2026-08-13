"""
Contradiction detection tests (docs/12 M11).

Three layers, each pinned separately:

1. The pure module (grouping, validation, block rendering, placement) — no model.
2. The graph node's fail-closed behavior — stubbed `_structured`, no model.
3. End-to-end fake-mode pipeline runs — the default run must stay contradiction-free
   (golden stability), and a corpus run whose documents plant the fixture sentinel must
   surface a first-class block before the reference list.

The real-model recall/FP bar lives in evals/contradiction_eval.py with its curated
fixtures; these tests pin the mechanism that bar is measured through.
"""

from __future__ import annotations

import pytest
from langgraph.checkpoint.memory import MemorySaver

from evals import metrics
from research_engine import contradictions
from research_engine.corpus import CorpusStore
from research_engine.runconfig import RunConfig
from research_engine.runner import run
from research_engine.schemas import ContradictionPair
from tests.test_corpus_store import FakeEmbeddings

URL_A = "https://example.org/a"
URL_B = "https://example.net/b"

EVIDENCE = [
    {"task_id": 1, "source_url": URL_A, "source_title": "A", "snippet": "the output was 42 units"},
    {"task_id": 1, "source_url": URL_A, "source_title": "A", "snippet": "extra detail from A"},
    {"task_id": 2, "source_url": URL_B, "source_title": "B", "snippet": "the output was 17 units"},
]


def _pair(**over) -> ContradictionPair:
    base = {
        "claim_a": "the output was 42 units",
        "snippet_a": "the output was 42 units",
        "source_a": URL_A,
        "claim_b": "the output was 17 units",
        "snippet_b": "the output was 17 units",
        "source_b": URL_B,
        "nature": "Incompatible values for the same measurement.",
    }
    base.update(over)
    return ContradictionPair(**base)


# ── The pure module ────────────────────────────────────────────────────────────────


def test_grouping_preserves_order_dedupes_and_caps():
    evidence = list(EVIDENCE) + [
        # duplicate snippet — dropped
        {"task_id": 1, "source_url": URL_A, "source_title": "A", "snippet": "the output was 42 units"},
        # blank url/snippet — dropped
        {"task_id": 1, "source_url": "", "source_title": "X", "snippet": "no home"},
        {"task_id": 1, "source_url": URL_B, "source_title": "B", "snippet": "   "},
    ]
    by_source = contradictions.group_snippets_by_source(evidence)
    assert list(by_source) == [URL_A, URL_B]
    assert by_source[URL_A] == ["the output was 42 units", "extra detail from A"]
    assert by_source[URL_B] == ["the output was 17 units"]

    # Caps: 4 snippets per source, 12 sources total. URL_A goes first so it survives
    # the source cap; its 9 snippets still shrink to the per-source cap.
    many = [
        {"task_id": 1, "source_url": URL_A, "source_title": "A", "snippet": f"n{j}"} for j in range(9)
    ] + [
        {"task_id": 1, "source_url": f"https://example.org/{i}", "source_title": "", "snippet": f"s{i}"}
        for i in range(20)
    ]
    capped = contradictions.group_snippets_by_source(many)
    assert len(capped) == contradictions.MAX_SOURCES
    assert len(capped[URL_A]) == contradictions.MAX_SNIPPETS_PER_SOURCE


def test_detector_input_wraps_snippets_as_untrusted():
    by_source = contradictions.group_snippets_by_source(EVIDENCE)
    text = contradictions.build_detector_input(by_source)
    assert f"Source: {URL_A}" in text and f"Source: {URL_B}" in text
    assert text.count("<untrusted_web_content>") == 2 == text.count("</untrusted_web_content>")


def test_validation_drops_unknown_self_and_duplicate_pairs():
    by_source = contradictions.group_snippets_by_source(EVIDENCE)
    known = _pair()
    unknown = _pair(source_b="https://evil.example/injected")
    self_conflict = _pair(source_b=URL_A, claim_b="a different claim")
    duplicate = _pair(claim_a="the output was 17 units", claim_b="the output was 42 units")

    out = contradictions.validate_pairs([known, unknown, self_conflict, duplicate], by_source)
    assert len(out) == 1
    assert out[0]["source_a"] == URL_A and out[0]["source_b"] == URL_B


def test_block_quotes_both_sides_and_refuses_to_resolve():
    by_source = contradictions.group_snippets_by_source(EVIDENCE)
    [pair] = contradictions.validate_pairs([_pair()], by_source)
    block = contradictions.render_block([pair], {URL_A: 1, URL_B: 2})

    assert block.startswith("## Conflicting evidence")
    assert "does **not**" in block, "the block must state it does not resolve the conflict"
    assert "[1] claims that the output was 42 units" in block
    assert "[2] claims that the output was 17 units" in block
    assert "Nature of disagreement: Incompatible values" in block
    assert 'Verbatim: "the output was 42 units" vs "the output was 17 units"' in block


def test_block_is_inserted_before_the_reference_list():
    draft = "# T\n\n## Analysis\nBody [1].\n\n## Sources\n[1] https://example.org/a\n"
    placed = contradictions.insert_block(draft, "## Conflicting evidence\n\n1. ...")
    assert placed.index("## Conflicting evidence") < placed.index("## Sources")
    assert placed.index("## Analysis") < placed.index("## Conflicting evidence")

    # A report with no recognizable reference heading gets the block appended.
    bare = contradictions.insert_block("# T\n\nBody.", "BLOCK")
    assert bare.endswith("BLOCK")


# ── The eval metric ────────────────────────────────────────────────────────────────


def test_contradictions_surfaced_counts_numbered_items_only():
    report = (
        "# T\n\n## Analysis\nFacts [1].\n\n## Conflicting evidence\n\n"
        "1. [1] claims X — [2] claims Y.\n"
        "   Nature of disagreement: incompatible.\n\n"
        "2. [1] claims P — [3] claims Q.\n\n"
        "## Sources\n[1] a\n[2] b\n"
    )
    assert metrics.contradictions_surfaced(report) == 2
    assert metrics.contradictions_surfaced("no conflicts here") == 0
    assert metrics.report_metrics(report, [])["contradictions_surfaced"] == 2


def test_conflict_block_is_not_judged_as_claims():
    """The block quotes both sides of a conflict; its lines are meta-prose, not claims
    the citation-support judge should rule on."""
    report = (
        "# T\n\n## Analysis\nA real claim [1].\n\n## Conflicting evidence\n\n"
        "1. [1] claims that the output was 42 units — [2] claims that it was 17 units.\n\n"
        "## Sources\n[1] a\n[2] b\n"
    )
    claims = metrics.claim_lines(report)
    assert claims == ["A real claim [1]."]


# ── The graph node, fail-closed ────────────────────────────────────────────────────


def _state(evidence):
    return {
        "session_id": "t",
        "original_query": "q",
        "evidence": evidence,
        "cost_usd": 0.0,
        "tokens_input": 0,
        "tokens_output": 0,
    }


@pytest.mark.asyncio
async def test_single_source_never_calls_the_model(monkeypatch):
    from research_engine import graph

    async def boom(*a, **k):  # pragma: no cover - must not run
        raise AssertionError("detector must not call a model for one source")

    monkeypatch.setattr(graph, "_structured", boom)
    one = [{"task_id": 1, "source_url": URL_A, "source_title": "A", "snippet": "only one source"}]
    out = await graph.contradiction_detector_node(_state(one))
    assert out["contradictions"] == []


@pytest.mark.asyncio
async def test_unavailable_detector_surfaces_nothing(monkeypatch):
    """Fail closed: an erroring/unparseable detector reports nothing, never invents."""
    from research_engine import graph

    async def unavailable(*a, **k):
        return None, 0.0, 0, 0

    monkeypatch.setattr(graph, "_structured", unavailable)
    out = await graph.contradiction_detector_node(_state(EVIDENCE))
    assert out["contradictions"] == []


@pytest.mark.asyncio
async def test_validated_pairs_reach_state(monkeypatch):
    from research_engine import graph

    class _Parsed:
        pairs = [_pair(), _pair(source_b="https://unknown.example")]

    async def structured(*a, **k):
        return _Parsed(), 0.01, 5, 5

    monkeypatch.setattr(graph, "_structured", structured)
    out = await graph.contradiction_detector_node(_state(EVIDENCE))
    assert len(out["contradictions"]) == 1, "the unknown-source pair must be dropped"
    assert out["cost_usd"] == 0.01


# ── End-to-end through the real graph ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_default_fake_run_stays_contradiction_free():
    """Golden stability: consistent fixture evidence produces no block."""
    outcome = await run(
        checkpointer=MemorySaver(),
        session_id="m11-default",
        user_id="u",
        query="What is retrieval-augmented generation?",
        run_config=RunConfig(llm_mode="fake"),
    )
    assert outcome.status == "awaiting_approval"
    assert "Conflicting evidence" not in (outcome.draft_report or "")
    assert metrics.contradictions_surfaced(outcome.draft_report or "") == 0


# Corpus documents that plant the scripted detector's sentinel AND disagree on a value;
# they reuse the scripted planner's fixed task queries so retrieval is non-vacuous.
CONFLICT_DOC_A = (
    "Background and definitions: the reactor output was measured at 42 units. "
    "Current state and data confirm the reading held steady. CONTRADICTION-FIXTURE"
)
CONFLICT_DOC_B = (
    "Background and definitions: the reactor output was measured at 17 units. "
    "Current state and data confirm the reading held steady. CONTRADICTION-FIXTURE"
)


@pytest.mark.asyncio
async def test_corpus_run_surfaces_the_conflict_block(tmp_path):
    store = CorpusStore(tmp_path / "corpus.sqlite", FakeEmbeddings())
    await store.ingest("reading-a.txt", CONFLICT_DOC_A.encode())
    await store.ingest("reading-b.txt", CONFLICT_DOC_B.encode())

    outcome = await run(
        checkpointer=MemorySaver(),
        session_id="m11-conflict",
        user_id="u",
        query="What was the reactor output?",
        run_config=RunConfig(llm_mode="fake", corpus_mode=True),
        corpus=store,
    )
    assert outcome.status == "awaiting_approval"
    draft = outcome.draft_report or ""

    # The block is present, cites both corpus sources, and sits before the reference
    # list — a first-class finding, not an appendix.
    assert metrics.contradictions_surfaced(draft) == 1
    assert "does **not**" in draft
    assert draft.index("## Conflicting evidence") < draft.index("## Sources")

    # The surfaced conflict is grounded in the actual corpus text.
    block = draft.split("## Conflicting evidence")[1]
    assert "42 units" in block and "17 units" in block
