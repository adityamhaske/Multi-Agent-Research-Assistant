"""
The citation judge is named, independent of what it grades, and disclosed (RG-5).

RG-5 asks for "a committed write-once eval result clearing `MIN_CITATION_SUPPORT` with a
disclosed independent judge that actually answered". Until V3 the harness judged with
`get_llm("critic")` — the pipeline's own critic grading the pipeline's own citations — and
wrote no judge into the result at all. The best qualifying number on record (0.90) is
therefore self-judged, and nothing in its file says so.

These tests pin the four properties the gate needs, each on its own:

- **Named, never defaulted.** Judging refuses when no judge is configured, rather than
  falling back to the critic; a real-mode report eval refuses to start without `--judge`,
  before a single query spends anything.
- **Independent.** A judge that is any route the harness runs, the same model reached
  through another provider, or a router alias that could resolve to either, is refused.
- **Disclosed.** The result carries a `judge` block beside `models`: the route, the routes it
  was checked against, and what it actually did for baseline and candidate.
- **Actually answered.** Which model served each ruling is read from the provider's
  response, never copied from the route — so a judge that answered as something else, or
  not at all, shows it.

Thresholds, eval isolation and write-once results are pinned elsewhere and untouched here;
the last test only confirms a judged run still cannot land on an existing file.
"""

from __future__ import annotations

import json
import os
import sys
import types
from dataclasses import replace

import pytest

_ENV_BEFORE = dict(os.environ)
from evals import harness  # noqa: E402
from research_engine.runconfig import get_run_config  # noqa: E402

os.environ.clear()
os.environ.update(_ENV_BEFORE)

#: The routes the harness runs — the system under evaluation, read rather than assumed.
PIPELINE = {role: harness.RUN_CONFIG.models[role] for role in harness._ROLES}
PIPELINE_ROUTE = PIPELINE["critic"]
JUDGE = "anthropic:claude-sonnet-4-6"

REPORT = (
    "# R\n\n## Key Findings\n"
    "- The first substantive finding stated here [1]\n"
    "- The second substantive finding stated here [2]\n\n"
    "## Sources\n[1] https://example.com/1\n[2] https://example.com/2\n"
)
SOURCES = [
    {"index": 1, "url": "https://example.com/1", "title": "S1", "snippet": "alpha"},
    {"index": 2, "url": "https://example.com/2", "title": "S2", "snippet": "beta"},
]


class _Reply:
    def __init__(self, content: str, served: str | None) -> None:
        self.content = content
        self.response_metadata = {"model_name": served} if served else {}


class _Judge:
    """Answers every batch, and records which route the factory was building for."""

    def __init__(self, served: str | None = "claude-sonnet-4-6-20260101") -> None:
        self.served = served
        self.calls = 0

    async def ainvoke(self, messages):  # noqa: ANN001 — mirrors langchain's signature
        self.calls += 1
        return _Reply("Claim 1: YES\nClaim 2: NO", self.served)


@pytest.fixture(autouse=True)
def _no_judge_leaks(monkeypatch):
    """`configure_judge` assigns a module global; this restores it after every test."""
    monkeypatch.setattr(harness, "JUDGE_ROUTE", None)


@pytest.fixture
def factory(monkeypatch):
    """The engine factory, spied on: what it was asked for, and under which routing."""
    built: list[str] = []
    judge = _Judge()

    def get_llm(role):
        built.append(get_run_config().models[role])
        return judge

    monkeypatch.setattr("research_engine.llm_factory.get_llm", get_llm)
    return built, judge


# ── Named, never defaulted ────────────────────────────────────────────────────────


async def test_judging_refuses_without_a_named_judge_rather_than_using_the_critic(factory):
    built, judge = factory
    with pytest.raises(harness.JudgeConfigError, match="never falls back"):
        await harness.judge_citation_support(REPORT, SOURCES)
    assert built == [], "the factory was asked for a model — the critic fallback is back"
    assert judge.calls == 0


async def test_the_named_judge_is_what_gets_built(factory):
    built, _ = factory
    harness.configure_judge(JUDGE)
    await harness.judge_citation_support(REPORT, SOURCES)
    assert built == [JUDGE]
    # Borrowing the critic's slot to build the judge must not outlive the build.
    assert get_run_config().models["critic"] != JUDGE


# ── Independent ───────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("judge", "why"),
    [
        (PIPELINE_ROUTE, "cannot also be its judge"),  # the pipeline's own route
        (  # the same model reached through another provider
            "openrouter:google/" + PIPELINE_ROUTE.partition(":")[2],
            "cannot also be its judge",
        ),
        # A router alias could resolve to anything, the pipeline's own model included.
        ("custom:auto/best-fast", "router alias"),
        ("openrouter:openrouter/auto", "router alias"),
        ("gemini-2.5-pro", "provider:model"),  # no provider
        ("anthropic:", "provider:model"),  # no model
    ],
)
def test_a_judge_that_is_not_independent_is_refused(judge, why):
    with pytest.raises(harness.JudgeConfigError, match=why):
        harness.configure_judge(judge)
    assert harness.JUDGE_ROUTE is None


def test_one_model_under_two_spellings_is_one_model():
    pipeline = {"planner": "ollama:qwen2.5:latest"}
    with pytest.raises(harness.JudgeConfigError, match="planner"):
        harness.validate_judge("ollama:qwen2.5", pipeline)


def test_a_pipeline_on_a_router_alias_cannot_be_shown_independent_of_anything():
    """If the pipeline's own model is unknown, no judge can be proved different from it."""
    with pytest.raises(harness.JudgeConfigError, match="Pin the model"):
        harness.validate_judge(JUDGE, {"synthesizer": "custom:auto/best-fast"})


def test_a_different_pinned_model_is_accepted():
    assert harness.configure_judge(JUDGE) == JUDGE == harness.JUDGE_ROUTE


# ── Disclosed, and actually answered ──────────────────────────────────────────────


async def test_every_ruling_records_the_model_that_served_it(factory):
    _, judge = factory
    harness.configure_judge(JUDGE)
    rate, rows = await harness.judge_citation_support(REPORT, SOURCES)
    assert rate == 0.5
    assert [r["judged_by"] for r in rows] == [judge.served, judge.served]


async def test_an_undisclosed_server_is_recorded_as_undisclosed_not_as_the_route(monkeypatch):
    judge = _Judge(served=None)
    monkeypatch.setattr("research_engine.llm_factory.get_llm", lambda role: judge)
    harness.configure_judge(JUDGE)
    _, rows = await harness.judge_citation_support(REPORT, SOURCES)
    assert [r["judged_by"] for r in rows] == [None, None]
    assert harness.judge_tally([{"claim_verdicts": rows}])["served_models"] == []


def test_the_tally_counts_only_what_the_judge_ruled_on():
    rows = [
        {"claim_verdicts": [{"judged": True, "judged_by": "m1"}, {"judged": False}]},
        {"claim_verdicts": [{"judged": True, "judged_by": "m2"}]},
        {"completed": False},  # a query that never reached the judge
    ]
    assert harness.judge_tally(rows) == {
        "claims_judged": 2,
        "claims_unjudged": 1,
        "served_models": ["m1", "m2"],
    }


def test_a_judge_that_ruled_on_nothing_did_not_answer():
    section = harness.judge_section(JUDGE, [{"claim_verdicts": [{"judged": False}]}], None)
    assert section["answered"] is False
    assert "candidate" not in section


# ── The command line, end to end ──────────────────────────────────────────────────


def _row(query_id: str, *, served: str = "claude-sonnet-4-6-20260101") -> dict:
    return {
        "id": query_id,
        "completed": True,
        "error": None,
        "latency_s": 0.0,
        "citation_support_rate": 1.0,
        "claim_verdicts": [{"claim": "c", "supported": True, "judged": True, "judged_by": served}],
    }


@pytest.fixture
def real_mode(monkeypatch, tmp_path):
    """`main()` in real mode with nothing leaving the process: a scripted `run_one`, no
    sleeps, and results written to a temporary directory."""
    calls: list[dict | None] = []

    async def run_one(query, *, prompt_overrides=None):
        calls.append(prompt_overrides)
        return _row(query["id"])

    async def no_sleep(_seconds):
        return None

    monkeypatch.setattr(harness, "RUN_CONFIG", replace(harness.RUN_CONFIG, llm_mode="real"))
    monkeypatch.setattr(harness, "run_one", run_one)
    monkeypatch.setattr(harness, "asyncio", types.SimpleNamespace(sleep=no_sleep))
    monkeypatch.setattr(harness, "RESULTS_DIR", tmp_path)
    return calls


async def _main(monkeypatch, *argv):
    monkeypatch.setattr(sys, "argv", ["harness", "--limit", "2", "--date", "2026-09-27", *argv])
    await harness.main()


async def test_a_real_run_without_a_judge_refuses_before_any_query(monkeypatch, real_mode):
    with pytest.raises(SystemExit) as exc:
        await _main(monkeypatch)
    assert exc.value.code == 2
    assert real_mode == [], "a query ran — the refusal came after money was spent"


async def test_a_real_run_with_a_self_judge_refuses_before_any_query(monkeypatch, real_mode):
    with pytest.raises(SystemExit) as exc:
        await _main(monkeypatch, "--judge", PIPELINE_ROUTE)
    assert exc.value.code == 2
    assert real_mode == []


async def test_a_scripted_run_rejects_a_judge_it_would_never_call(monkeypatch, tmp_path):
    monkeypatch.setattr(harness, "RESULTS_DIR", tmp_path)
    with pytest.raises(SystemExit) as exc:
        await _main(monkeypatch, "--judge", JUDGE)
    assert exc.value.code == 2


async def test_the_result_discloses_its_judge_beside_the_models_it_graded(
    monkeypatch, tmp_path, real_mode
):
    await _main(monkeypatch, "--judge", JUDGE)
    (written,) = tmp_path.glob("eval-*.json")
    payload = json.loads(written.read_text())

    assert payload["models"] == PIPELINE
    assert payload["judge"] == {
        "route": JUDGE,
        "independent_of": payload["models"],
        "baseline": {
            "claims_judged": 2,
            "claims_unjudged": 0,
            "served_models": ["claude-sonnet-4-6-20260101"],
        },
        "answered": True,
    }
    # Thresholds are the fixed ones; naming a judge changes who grades, not the bar.
    assert payload["release_criteria"]["thresholds"] == {
        "min_completion_rate": harness.MIN_COMPLETION_RATE,
        "min_citation_support": harness.MIN_CITATION_SUPPORT,
    }


async def test_baseline_and_candidate_are_judged_by_the_same_judge_and_both_tallied(
    monkeypatch, tmp_path, real_mode
):
    spec = tmp_path / "spec"
    spec.mkdir()
    (spec / "c.json").write_text(json.dumps({"planner": "Plan in exactly two tasks."}))
    await _main(monkeypatch, "--judge", JUDGE, "--candidate", str(spec / "c.json"))
    (written,) = tmp_path.glob("eval-*-custom.json")
    judge = json.loads(written.read_text())["judge"]

    candidate = {"planner": "Plan in exactly two tasks."}
    assert real_mode == [None, None, candidate, candidate]  # the same two queries, twice
    assert judge["route"] == JUDGE
    assert judge["baseline"]["claims_judged"] == judge["candidate"]["claims_judged"] == 2


async def test_a_judged_run_is_still_write_once(monkeypatch, tmp_path, real_mode):
    await _main(monkeypatch, "--judge", JUDGE)
    (first,) = tmp_path.glob("eval-*.json")
    before = first.read_bytes()
    await _main(monkeypatch, "--judge", JUDGE)
    assert sorted(p.name for p in tmp_path.glob("eval-*.json")) == [
        "eval-2026-09-27-google-run2.json",
        "eval-2026-09-27-google.json",
    ]
    assert first.read_bytes() == before
    with pytest.raises(SystemExit, match="write-once"):
        await _main(monkeypatch, "--judge", JUDGE, "--out", str(first))
