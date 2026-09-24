"""Unit tests for the eval metrics (docs/08 §5) — the numbers in a committed eval run
are only trustworthy if the metric functions are tested."""

from evals import metrics

FAKE_REPORT = (
    "# Fixture Report\n\n## Executive Summary\nDeterministic summary [1].\n\n"
    "## Key Findings\n- A citable fact [1]\n- A corroborating fact [2]\n\n"
    "## Detailed Analysis\nAnalysis grounded in evidence [1][2].\n\n"
    "## Limitations\nFixture data only.\n\n"
    "## Sources\n[1] https://example.com/fixture/1\n[2] https://example.com/fixture/2\n"
)
FAKE_SOURCES = [
    {"index": 1, "url": "https://example.com/fixture/1", "title": "S1", "snippet": "a"},
    {"index": 2, "url": "https://example.com/fixture/2", "title": "S2", "snippet": "b"},
]


def test_extract_citations_preserves_order_and_duplicates():
    assert metrics.extract_citations("a [1] b [2] c [1]") == [1, 2, 1]


def test_citation_stats_all_resolve():
    stats = metrics.citation_stats(FAKE_REPORT, FAKE_SOURCES)
    assert stats["total_citations"] == 5  # 1 + 1 + 1 + 2 (in [1][2])
    assert stats["unresolved_citations"] == 0
    assert stats["resolution_rate"] == 1.0


def test_citation_stats_flags_unresolved():
    stats = metrics.citation_stats("Claim [1] and [9].", FAKE_SOURCES)
    assert stats["total_citations"] == 2
    assert stats["unresolved_citations"] == 1  # [9] has no source
    assert stats["resolution_rate"] == 0.5


def test_resolution_rate_is_none_without_citations():
    assert metrics.citation_stats("No citations here.", FAKE_SOURCES)["resolution_rate"] is None


def test_uncited_claim_count_excludes_limitations_and_sources():
    # Every line carries a citation; "Fixture data only." sits in Limitations, which is
    # hedging rather than a factual claim (metrics v3, D5) — so nothing is uncited.
    assert metrics.uncited_claim_count(FAKE_REPORT) == 0


def test_limitations_lines_are_not_claims_even_when_cited():
    """The citation-support judge measures factual claims. A cited sentence in
    Limitations — 'the evidence does not cover X [1]' — is exactly the honesty the
    synthesizer is instructed to write, and must not be judged against snippets."""
    text = (
        "A real cited claim about the topic [1].\n\n"
        "## Limitations\nThe snippets do not cover the follow-up question, as outlined in [1].\n\n"
        "## Sources\n[1] https://x\n"
    )
    claims = metrics.claim_lines(text)
    assert claims == ["A real cited claim about the topic [1]."]
    # A later section after Limitations is claims again (the skip is scoped to the section).
    text2 = (
        "## Limitations\nHedging sentence here.\n\n## Detailed Analysis\n"
        "A real cited claim about the topic [1].\n"
    )
    assert metrics.claim_lines(text2) == ["A real cited claim about the topic [1]."]


def test_uncited_claim_ignores_headings_and_short_lines():
    text = "# Title\n\nok\n\nThis is a substantial uncited claim about the world.\n"
    assert metrics.uncited_claim_count(text) == 1  # heading + "ok" ignored


def test_sources_after_heading_are_not_claims():
    text = (
        "A real cited claim about the topic [1].\n\n## References\nSome uncited reference line.\n"
    )
    assert metrics.uncited_claim_count(text) == 0


def test_report_metrics_shape():
    m = metrics.report_metrics(FAKE_REPORT, FAKE_SOURCES)
    assert m["source_count"] == 2
    assert m["uncited_claim_count"] == 0
    assert m["resolution_rate"] == 1.0
    assert m["word_count"] > 0


# ── AC-13: a threshold that can say "unmeasured" (RFC §14.3) ──────────────────────
#
# The harness published `0.0` for a rate over zero queries, and for an average latency over
# none. A rate over nothing is not a rate of zero: `0.0` completion reads as "every query
# failed", and against a 0.90 threshold it reports a failure that never happened. AC-13
# makes this an explicit contract, so it is tested at `n == 0` directly rather than relying
# on the fixed query set never being empty.

import ast as _ast  # noqa: E402
import json as _json  # noqa: E402
import os as _os  # noqa: E402

_ENV_BEFORE = dict(_os.environ)
from evals import harness as _harness  # noqa: E402

_os.environ.clear()
_os.environ.update(_ENV_BEFORE)


def _row(completed: bool, **extra) -> dict:
    return {"id": "q", "completed": completed, "latency_s": 1.0, **extra}


# The boundaries, exactly: `>=` is inclusive, so the threshold itself passes.


def test_support_at_the_threshold_passes():
    assert (
        _harness.check_release_criteria({"completion_rate": 1.0, "citation_support_rate": 0.95})[
            "citation_support_ok"
        ]
        is True
    )


def test_support_just_below_the_threshold_fails():
    assert (
        _harness.check_release_criteria({"completion_rate": 1.0, "citation_support_rate": 0.9499})[
            "citation_support_ok"
        ]
        is False
    )


def test_completion_at_the_threshold_passes():
    assert (
        _harness.check_release_criteria({"completion_rate": 0.90, "citation_support_rate": None})[
            "completion_rate_ok"
        ]
        is True
    )


def test_completion_just_below_the_threshold_fails():
    assert (
        _harness.check_release_criteria({"completion_rate": 0.8999, "citation_support_rate": None})[
            "completion_rate_ok"
        ]
        is False
    )


def test_the_thresholds_are_the_frozen_ones():
    """§14.1: fixed, and not user-settable. A drift here is a changed contract."""
    assert _harness.MIN_CITATION_SUPPORT == 0.95
    assert _harness.MIN_COMPLETION_RATE == 0.90


# n > 0 is measured, exactly as before.


def test_a_measured_completion_rate_is_unchanged():
    rows = [_row(True)] * 9 + [_row(False)]
    assert _harness.aggregate(rows)["completion_rate"] == 0.9


# n == 0 is unmeasured — never zero, never a failure.


def test_zero_queries_is_an_unmeasured_completion_rate():
    assert _harness.aggregate([])["completion_rate"] is None


def test_zero_queries_is_not_a_completion_failure():
    """The distinction that matters: `None` is "could not tell", `False` is "failed"."""
    criteria = _harness.check_release_criteria(_harness.aggregate([]))
    assert criteria["completion_rate_ok"] is None
    assert criteria["completion_rate_ok"] is not False


def test_zero_queries_has_no_averages():
    agg = _harness.aggregate([])
    for key in ("avg_source_count", "avg_latency_s", "avg_cost_usd", "citation_support_rate"):
        assert agg[key] is None, key


def test_an_unmeasured_result_serialises_as_null_not_zero():
    """The committed file is what a reader sees. `null` is the repository's existing
    representation for "unmeasured" (`citation_support_ok` already uses it); a `0.0`
    anywhere in these fields would be the defect this section fixes."""
    agg = _harness.aggregate([])
    criteria = _harness.check_release_criteria(agg)
    encoded = _json.loads(_json.dumps({"aggregate": agg, "release_criteria": criteria}))
    assert encoded["aggregate"]["completion_rate"] is None
    assert encoded["release_criteria"]["completion_rate_ok"] is None
    assert "0.0" not in _json.dumps(encoded["aggregate"])


# The memory eval had the same defect in two places, inline in `main()`.


def test_a_measured_memory_pass_rate_is_unchanged():
    rows = [{"pass_test": True, "latency_s": 2.0}] * 9 + [{"pass_test": False, "latency_s": 2.0}]
    agg = _harness.aggregate_memory(rows)
    assert agg["pass_rate"] == 0.9
    assert agg["avg_latency_s"] == 2.0
    assert _harness.check_memory_criteria(agg)["pass_rate_ok"] is True


def test_the_memory_pass_threshold_is_inclusive():
    assert _harness.check_memory_criteria({"pass_rate": 0.90})["pass_rate_ok"] is True
    assert _harness.check_memory_criteria({"pass_rate": 0.8999})["pass_rate_ok"] is False


def test_zero_memory_queries_is_unmeasured_not_a_failure():
    agg = _harness.aggregate_memory([])
    assert agg["pass_rate"] is None
    assert agg["avg_latency_s"] is None
    assert _harness.check_memory_criteria(agg)["pass_rate_ok"] is None


# ── The two support-rate homes agree (AGENTS.md: "change both") ───────────────────


def _benchmark_calc_support_rate():
    """`benchmark.calc_support_rate`, executed from its own source.

    It is nested inside `benchmark.main()`, so it cannot be imported, and `benchmark.py` is
    outside this change. Extracting the function's syntax tree and compiling exactly that
    source tests the real code without editing the file. It is self-contained — no free
    variables from `main()` — which is checked below rather than assumed.
    """
    from pathlib import Path

    src = (Path(__file__).resolve().parents[2] / "evals" / "benchmark.py").read_text("utf-8")
    main = next(
        n
        for n in _ast.walk(_ast.parse(src))
        if isinstance(n, _ast.AsyncFunctionDef) and n.name == "main"
    )
    fn = next(
        n
        for n in _ast.walk(main)
        if isinstance(n, _ast.FunctionDef) and n.name == "calc_support_rate"
    )
    namespace: dict = {}
    exec(compile(_ast.Module(body=[fn], type_ignores=[]), "benchmark.py", "exec"), namespace)  # noqa: S102
    return namespace["calc_support_rate"]


def test_the_extracted_benchmark_rule_is_self_contained():
    """If `calc_support_rate` ever closed over `main()`'s locals, executing it in isolation
    would test something other than what runs — so that is refused, not assumed."""
    import builtins
    from pathlib import Path

    src = (Path(__file__).resolve().parents[2] / "evals" / "benchmark.py").read_text("utf-8")
    fn = next(
        n
        for n in _ast.walk(_ast.parse(src))
        if isinstance(n, _ast.FunctionDef) and n.name == "calc_support_rate"
    )
    used = {n.id for n in _ast.walk(fn) if isinstance(n, _ast.Name)}
    bound = {a.arg for a in fn.args.args}
    bound |= {
        t.id
        for n in _ast.walk(fn)
        for t in (n.targets if isinstance(n, _ast.Assign) else [getattr(n, "target", None)])
        if isinstance(t, _ast.Name)
    }
    assert not (used - bound - set(dir(builtins)))


class _Reply:
    def __init__(self, content: str) -> None:
        self.content = content


class _Scripted:
    def __init__(self, reply: str) -> None:
        self.reply = reply

    async def ainvoke(self, messages):  # noqa: ANN001
        return _Reply(self.reply)


def _report_with(n: int) -> tuple[str, list]:
    lines = [f"- Substantive finding number {i} stated here [1]" for i in range(1, n + 1)]
    report = "# R\n\n## Key Findings\n" + "\n".join(lines) + "\n\n## Sources\n[1] https://e.x/1\n"
    return report, [{"index": 1, "url": "https://e.x/1", "title": "S", "snippet": "s"}]


import pytest as _pytest  # noqa: E402

# One verdict per claim: True supported, False unsupported, None never ruled on. At most four,
# so a single scripted judge reply covers the whole report (the harness batches by four).
_CASES = [
    [True, False],
    [True, True, True, True],
    [False, False],
    [True, None],
    [None, None],
    [None],
    [],
]


@_pytest.mark.parametrize("verdicts", _CASES, ids=repr)
async def test_both_support_homes_agree(monkeypatch, verdicts):
    """Same claims, same rulings, same answer — including `None` when nothing was judged."""
    reply = "\n".join(
        f"Claim {i}: {'YES' if v else 'NO'}" for i, v in enumerate(verdicts, 1) if v is not None
    )
    monkeypatch.setattr("research_engine.llm_factory.get_llm", lambda role: _Scripted(reply))
    report, sources = _report_with(len(verdicts))
    harness_rate, _ = await _harness.judge_citation_support(report, sources)

    traces = [
        {"judge_verdict": None if v is None else ("SUPPORTED" if v else "UNSUPPORTED")}
        for v in verdicts
    ]
    assert harness_rate == _benchmark_calc_support_rate()(traces)
