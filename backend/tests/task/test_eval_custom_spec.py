"""
Custom-spec evaluation: the same query set, twice, against the same thresholds (RFC §14.2).

A candidate spec is measured by running the fixed ten-query set once with the shipped prompts
and once with the candidate, then reporting both against `MIN_CITATION_SUPPORT` and
`MIN_COMPLETION_RATE`. A spec below threshold is **reported, not blocked**.

**What fake mode can and cannot show.** These tests run the real graph with scripted models.
That proves the mechanism — the candidate reaches the pipeline, the file records both runs,
the thresholds apply identically — but it cannot show that any prompt is *better*: the judge
only runs against a real provider, so `citation_support_rate` is `None` for both runs here,
and the scripted models answer by role, so a candidate produces the baseline's output. A
quality comparison needs a real-mode run, which is a release activity, not a test.
"""

from __future__ import annotations

import json
import os
import sys

import pytest

_ENV_BEFORE = dict(os.environ)
from evals import harness  # noqa: E402
from research_engine.prompt_composition import recording_provenance  # noqa: E402
from research_engine.runconfig import get_run_config  # noqa: E402

os.environ.clear()
os.environ.update(_ENV_BEFORE)

BODY = "Plan in exactly two tasks, each naming one measurable quantity."
QUERY = json.loads((harness.EVALS_DIR / "queries.json").read_text())["queries"][0]


def _spec(tmp_path, content) -> str:
    path = tmp_path / "candidate.json"
    path.write_text(content if isinstance(content, str) else json.dumps(content))
    return str(path)


# ── Loading a candidate: one validator, the production one ────────────────────────


def test_a_valid_spec_loads(tmp_path):
    assert harness.load_candidate(_spec(tmp_path, {"planner": BODY})) == {"planner": BODY}


@pytest.mark.parametrize(
    ("content", "why"),
    [
        ({}, "replaces no prompt"),
        ({"planner": BODY, "not_a_role": "x"}, "unknown role"),
        ({"planner": "   "}, "not non-empty text"),
        ({"planner": 7}, "not non-empty text"),
        ("[1, 2]", "unknown role"),
        ("{not json", "cannot read"),
    ],
    ids=["empty", "unknown-role", "blank", "non-string", "not-a-mapping", "malformed-json"],
)
def test_an_unusable_spec_is_refused_not_evaluated_as_shipped(tmp_path, content, why):
    """In production an unusable snapshot falls back to shipped prompts and says so. Here the
    same fallback would publish the baseline's numbers under the candidate's name."""
    with pytest.raises(harness.CandidateSpecError, match=why):
        harness.load_candidate(_spec(tmp_path, content))


def test_a_missing_file_is_refused(tmp_path):
    with pytest.raises(harness.CandidateSpecError, match="cannot read"):
        harness.load_candidate(str(tmp_path / "absent.json"))


def test_validation_is_the_production_rule_not_a_copy():
    """`usable_overrides` is the one home of the all-or-nothing rule. A second copy here
    would accept or refuse specs differently from the runs it claims to predict."""
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(harness.load_candidate))
    called = {getattr(n.func, "id", None) for n in ast.walk(tree) if isinstance(n, ast.Call)}
    assert "usable_overrides" in called


def test_the_candidate_never_comes_from_a_stored_row():
    """The harness may take exactly the validator from `app`, and nothing that can reach a
    database: a candidate read from a user's preferences would measure that user's live
    edits under a spec file's name, and the override allowlist admits this module only on
    the promise that it never does."""
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(harness))
    from_app = {
        (n.module, alias.name)
        for n in ast.walk(tree)
        if isinstance(n, ast.ImportFrom) and (n.module or "").split(".")[0] == "app"
        for alias in n.names
    }
    plain = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    assert not {name for name in plain if name.split(".")[0] == "app"}
    assert from_app == {
        ("app.services.run_config", "OVERRIDES_APPLIED"),
        ("app.services.run_config", "usable_overrides"),
    }


# ── The candidate half of the result ──────────────────────────────────────────────


def _row(completed=True, support=None):
    return {"id": "q", "completed": completed, "citation_support_rate": support, "latency_s": 1.0}


def test_the_candidate_is_judged_against_the_same_thresholds():
    section = harness.candidate_section({"planner": BODY}, [_row(support=0.96)])
    assert section["release_criteria"]["thresholds"] == {
        "min_completion_rate": harness.MIN_COMPLETION_RATE,
        "min_citation_support": harness.MIN_CITATION_SUPPORT,
    }


def test_a_candidate_below_threshold_is_reported_not_raised():
    """§14.2: the user chose it; the eval measures, it does not refuse."""
    section = harness.candidate_section({"planner": BODY}, [_row(support=0.50)])
    assert section["release_criteria"]["citation_support_ok"] is False
    assert section["aggregate"]["citation_support_rate"] == 0.5


def test_the_candidate_records_exactly_what_was_measured():
    import hashlib

    section = harness.candidate_section({"planner": BODY}, [_row()])
    assert section["prompt_overrides"] == {"planner": BODY}
    assert section["prompt_sha256"] == {"planner": hashlib.sha256(BODY.encode()).hexdigest()}


def test_an_unmeasured_candidate_is_not_a_failure():
    """AC-13 applies to the candidate half as much as the baseline."""
    section = harness.candidate_section({"planner": BODY}, [])
    assert section["aggregate"]["completion_rate"] is None
    assert section["release_criteria"]["completion_rate_ok"] is None


# ── Where the result goes ─────────────────────────────────────────────────────────


def test_a_custom_spec_result_has_its_own_stem(monkeypatch, tmp_path):
    monkeypatch.setattr(harness, "RESULTS_DIR", tmp_path)
    path = harness._result_path("2026-09-24", custom_spec=True)
    assert path.name.endswith("-custom.json")
    assert path != harness._result_path("2026-09-24")


def test_a_custom_spec_result_never_lands_on_a_baseline_file(monkeypatch, tmp_path):
    monkeypatch.setattr(harness, "RESULTS_DIR", tmp_path)
    baseline = harness._result_path("2026-09-24")
    baseline.write_text("{}")
    custom = harness._result_path("2026-09-24", custom_spec=True)
    assert custom != baseline and not custom.exists()


def test_a_second_custom_run_the_same_day_is_numbered_not_overwritten(monkeypatch, tmp_path):
    monkeypatch.setattr(harness, "RESULTS_DIR", tmp_path)
    first = harness._result_path("2026-09-24", custom_spec=True)
    first.write_text("{}")
    second = harness._result_path("2026-09-24", custom_spec=True)
    assert second.name.endswith("-custom-run2.json")


# ── The real graph, in scripted mode ──────────────────────────────────────────────


async def test_the_candidate_reaches_the_real_pipeline():
    """Not a stand-in: the compiled graph, whose planner node composes through the real
    `system_prompt`. The PR-7b recorder shows what that node was actually given."""
    with recording_provenance() as seen:
        row = await harness.run_one(QUERY, prompt_overrides={"planner": BODY})
    assert row["completed"], row.get("error")
    assert seen["planner.main"]["effective_prompt"] == BODY
    assert seen["planner.main"]["overridden"] is True


async def test_the_baseline_real_pipeline_is_given_the_shipped_prompt():
    from research_engine import prompts

    with recording_provenance() as seen:
        await harness.run_one(QUERY)
    assert seen["planner.main"]["effective_prompt"] == prompts.PLANNER_PROMPT_V2
    assert seen["planner.main"]["overridden"] is False


async def test_nothing_remains_installed_after_a_real_candidate_run():
    await harness.run_one(QUERY, prompt_overrides={"planner": BODY})
    assert get_run_config().prompt_overrides == {}


async def test_a_repeated_run_gives_the_same_measurements():
    """Determinism, within what scripted mode is deterministic about. Latency is wall-clock
    time and is excluded; every measured field is compared."""
    first = await harness.run_one(QUERY, prompt_overrides={"planner": BODY})
    second = await harness.run_one(QUERY, prompt_overrides={"planner": BODY})
    measured = {k: v for k, v in first.items() if k != "latency_s"}
    assert measured == {k: v for k, v in second.items() if k != "latency_s"}


# ── The command line, end to end ──────────────────────────────────────────────────


async def _main(monkeypatch, tmp_path, *argv) -> dict:
    monkeypatch.setattr(harness, "RESULTS_DIR", tmp_path)
    monkeypatch.setattr(sys, "argv", ["harness", "--limit", "1", "--date", "2026-09-24", *argv])
    await harness.main()
    (written,) = list(tmp_path.glob("eval-*.json"))
    return json.loads(written.read_text()), written


async def test_a_plain_run_keeps_its_existing_shape(monkeypatch, tmp_path):
    """Without `--candidate`, nothing about the file changes."""
    payload, path = await _main(monkeypatch, tmp_path)
    assert set(payload) == {
        "date",
        "generated_at",
        "llm_mode",
        "mode",
        "models",
        "method",
        "aggregate",
        "release_criteria",
        "results",
    }
    assert "custom" not in path.name


async def test_a_custom_run_reports_both_side_by_side(monkeypatch, tmp_path):
    spec = tmp_path / "spec"
    spec.mkdir()
    payload, path = await _main(
        monkeypatch, tmp_path, "--candidate", _spec(spec, {"planner": BODY})
    )
    assert path.name.endswith("-custom.json")
    # The baseline stays where a plain run puts it; the candidate sits beside it.
    assert payload["aggregate"]["queries"] == payload["candidate"]["aggregate"]["queries"] == 1
    assert (
        payload["release_criteria"]["thresholds"]
        == payload["candidate"]["release_criteria"]["thresholds"]
    )
    assert payload["candidate"]["prompt_overrides"] == {"planner": BODY}


async def test_a_candidate_with_the_memory_eval_is_a_usage_error(monkeypatch, tmp_path):
    with pytest.raises(SystemExit) as exc:
        await _main(
            monkeypatch,
            tmp_path,
            "--mode",
            "memory",
            "--candidate",
            _spec(tmp_path, {"chat": BODY}),
        )
    assert exc.value.code == 2


async def test_an_unusable_candidate_is_a_usage_error_before_any_work(monkeypatch, tmp_path):
    ran = []
    monkeypatch.setattr(harness, "run_one", lambda *a, **k: ran.append(1))
    with pytest.raises(SystemExit) as exc:
        await _main(monkeypatch, tmp_path, "--candidate", _spec(tmp_path, {"not_a_role": BODY}))
    assert exc.value.code == 2
    assert ran == [], "an invalid spec must be refused before a single query runs"


async def test_a_threshold_miss_never_stops_the_process(monkeypatch, tmp_path):
    """The only `SystemExit` in `main()` is the write-once guard; a miss is reported."""

    async def failing(query, *, prompt_overrides=None):
        return {"id": query["id"], "completed": False, "error": "scripted miss", "latency_s": 0.0}

    monkeypatch.setattr(harness, "run_one", failing)
    spec = tmp_path / "spec"
    spec.mkdir()
    payload, _ = await _main(monkeypatch, tmp_path, "--candidate", _spec(spec, {"planner": BODY}))
    assert payload["release_criteria"]["completion_rate_ok"] is False
    assert payload["candidate"]["release_criteria"]["completion_rate_ok"] is False


# ── How "unmeasured" reads, to a machine and to a person ──────────────────────────


async def test_the_file_stores_null_and_the_console_says_n_a(monkeypatch, tmp_path, capsys):
    """Two representations of one fact, and they must not be confused.

    The committed file stores `null` — typed, and what every consumer already reads. The
    terminal says `n/a (unmeasured)`, the words `benchmark.py` and `retrieval.py` already
    print, so nobody reading a run's summary sees a bare `null` and wonders if it meant zero.
    Scripted mode never judges, so `citation_support_rate` is unmeasured here by construction.
    """
    payload, _ = await _main(monkeypatch, tmp_path)
    assert payload["aggregate"]["citation_support_rate"] is None
    assert payload["release_criteria"]["citation_support_ok"] is None

    out = capsys.readouterr().out
    summary = next(line for line in out.splitlines() if line.startswith("Aggregate:"))
    assert '"citation_support_rate": "n/a (unmeasured)"' in summary
    assert "null" not in summary


def test_the_console_uses_the_repositorys_existing_words():
    """One phrase across all three eval tools, or a reader has to learn three."""
    from pathlib import Path

    evals = Path(harness.__file__).parent
    for tool in ("benchmark.py", "retrieval.py"):
        assert harness.UNMEASURED in (evals / tool).read_text("utf-8"), tool
