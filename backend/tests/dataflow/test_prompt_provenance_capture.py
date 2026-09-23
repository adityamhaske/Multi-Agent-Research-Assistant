"""
The bundle states the prompt a run actually sent, captured as the run composed it (PR-7b).

**Why capture and not recompute.** `system_prompt` is pure over (purpose, the run's frozen
overrides), so re-composing at export *usually* reproduces the same string — and silently
stops doing so the moment the shipped constants change. A protected purpose re-composed
after an upgrade reports the constant shipped *now*, not the one the run was given, and the
bundle would assert a prompt that never executed. That is the failure this file exists to
prevent, so every assertion here is against what was recorded during execution.

**Only what ran is recorded.** Three of the seven research purposes are conditional —
`critic.citation_verify` iterates a possibly-empty batch list, `critic.contradiction_detector`
returns early below two sources, and `synthesizer.repair` fires only on an uncited sentence.
The frozen RFC asks for "each applicable purpose" (§9, AC-D3b), and absence is the honest
record; fabricating the missing three would be inventing execution that did not happen.
"""

from __future__ import annotations

import json

import pytest

from research_engine import prompts
from research_engine.bundle import content_hash
from research_engine.prompt_composition import (
    OVERRIDABLE_PURPOSES,
    PURPOSE_CONSTANTS,
    RUN_PURPOSES,
    recording_provenance,
    system_prompt,
)
from research_engine.runconfig import RunConfig, reset_run_config, set_run_config

BODY = "Answer only with measured quantities."


def _under(overrides, fn):
    token = set_run_config(RunConfig(prompt_overrides=overrides))
    try:
        with recording_provenance() as records:
            fn()
        return records
    finally:
        reset_run_config(token)


# ── What the recorder captures ────────────────────────────────────────────────────


def test_the_captured_string_is_exactly_what_system_prompt_returned():
    seen = {}

    def run():
        for purpose in sorted(RUN_PURPOSES):
            seen[purpose] = system_prompt(purpose)

    records = _under({"planner": BODY, "critic": BODY}, run)
    assert set(records) == set(RUN_PURPOSES)
    for purpose, text in seen.items():
        assert records[purpose]["effective_prompt"] == text


def test_the_digest_is_of_the_captured_string():
    records = _under({"planner": BODY}, lambda: system_prompt("planner.main"))
    captured = records["planner.main"]["effective_prompt"]
    assert content_hash(captured) == content_hash(BODY)
    assert captured == BODY


def test_overridden_comes_from_the_decision_not_a_string_comparison():
    """The sharp case: an override whose text equals the shipped prompt.

    A comparison would call this "not overridden" and the bundle would under-report a
    configured run. The recorder takes the branch that actually ran instead.
    """
    shipped = PURPOSE_CONSTANTS["planner.main"]
    records = _under({"planner": shipped}, lambda: system_prompt("planner.main"))
    assert records["planner.main"]["effective_prompt"] == shipped
    assert records["planner.main"]["overridden"] is True


@pytest.mark.parametrize("purpose", sorted(RUN_PURPOSES - OVERRIDABLE_PURPOSES))
def test_a_protected_purpose_is_captured_as_not_overridden(purpose):
    records = _under(
        {r: BODY for r in ("planner", "executor", "critic", "synthesizer")},
        lambda: system_prompt(purpose),
    )
    assert records[purpose]["overridden"] is False
    assert records[purpose]["policy"] == "PROTECTED"
    assert records[purpose]["effective_prompt"] == PURPOSE_CONSTANTS[purpose]


def test_capture_does_not_disturb_shipped_prompt_identity():
    """`fakes.SCENARIO_BY_PROMPT` resolves a scripted run by `is`."""
    out = {}
    _under({}, lambda: out.update(p=system_prompt("planner.main")))
    assert out["p"] is PURPOSE_CONSTANTS["planner.main"]


def test_nothing_is_recorded_without_a_recorder():
    """Chat turns and ordinary composition must not accumulate anywhere."""
    token = set_run_config(RunConfig(prompt_overrides={}))
    try:
        assert system_prompt("planner.main") is PURPOSE_CONSTANTS["planner.main"]
    finally:
        reset_run_config(token)


# ── Conditional purposes: absence is the record ───────────────────────────────────


CONDITIONAL = ["critic.citation_verify", "critic.contradiction_detector", "synthesizer.repair"]


@pytest.mark.parametrize("skipped", CONDITIONAL)
def test_a_purpose_that_never_executed_is_absent_not_fabricated(skipped):
    """`RUN_PURPOSES` is the universe of what *may* run, never evidence that it did."""
    executed = sorted(RUN_PURPOSES - {skipped})

    def run():
        for purpose in executed:
            system_prompt(purpose)

    records = _under({}, run)
    assert skipped not in records
    assert set(records) == set(executed)


def test_a_conditional_purpose_appears_once_it_executes():
    records = _under({}, lambda: system_prompt("synthesizer.repair"))
    assert records["synthesizer.repair"]["effective_prompt"] == prompts.SYNTHESIZER_REPAIR_PROMPT


def test_a_run_that_composed_nothing_records_nothing():
    records = _under({}, lambda: None)
    assert records == {}


# ── executor.main is composed twice ───────────────────────────────────────────────


def test_both_executor_call_sites_compose_the_same_prompt():
    """`graph.py` composes `executor.main` at two sites — the normal path and forced submit.

    One provenance entry is only honest if they cannot differ. They cannot: `system_prompt`
    is pure over (purpose, overrides) and the run's overrides are frozen for its whole life
    (PR-6). Pinned rather than trusted, because a future call site passing a different
    purpose string would make the single entry a lie.
    """
    seen = []
    records = _under(
        {"executor": BODY},
        lambda: seen.extend([system_prompt("executor.main"), system_prompt("executor.main")]),
    )
    assert seen[0] == seen[1]
    assert records["executor.main"]["effective_prompt"] == seen[0]
    assert len([k for k in records if k == "executor.main"]) == 1


def test_the_graph_composes_executor_main_at_exactly_two_sites():
    """If a third appears, the invariant above needs re-proving against it."""
    import ast
    from pathlib import Path

    src = (Path(__file__).resolve().parents[2] / "research_engine" / "graph.py").read_text("utf-8")
    calls = [
        n
        for n in ast.walk(ast.parse(src))
        if isinstance(n, ast.Call)
        and getattr(n.func, "id", None) == "system_prompt"
        and n.args
        and getattr(n.args[0], "value", None) == "executor.main"
    ]
    assert len(calls) == 2


# ── Status: what the three values look like in captured provenance ────────────────


def test_none_captures_the_shipped_prompts():
    records = _under({}, lambda: [system_prompt(p) for p in sorted(RUN_PURPOSES)])
    assert all(not r["overridden"] for r in records.values())
    for purpose, record in records.items():
        assert record["effective_prompt"] == PURPOSE_CONSTANTS[purpose]


def test_applied_captures_the_composed_prompts():
    records = _under(
        {"planner": BODY, "synthesizer": BODY},
        lambda: [system_prompt(p) for p in sorted(RUN_PURPOSES)],
    )
    assert records["planner.main"]["effective_prompt"] == BODY
    assert records["planner.main"]["overridden"] is True
    # `synthesizer.main` carries the untrusted-content note, so the body is wrapped.
    composed = records["synthesizer.main"]["effective_prompt"]
    assert BODY in composed and composed.startswith(prompts.UNTRUSTED_CONTENT_NOTE)
    assert records["synthesizer.repair"]["overridden"] is False


def test_unusable_captures_the_shipped_prompts_actually_used():
    """An unusable snapshot reaches the engine as `{}` — every purpose runs shipped, and the
    provenance must say so rather than echo what the user had configured."""
    records = _under({}, lambda: [system_prompt(p) for p in sorted(RUN_PURPOSES)])
    assert all(r["effective_prompt"] == PURPOSE_CONSTANTS[p] for p, r in records.items())
    assert all(r["overridden"] is False for r in records.values())


# ── No chat purpose can reach a research bundle ───────────────────────────────────


def test_chat_purposes_are_outside_the_research_universe():
    assert "chat.general" not in RUN_PURPOSES
    assert "chat.project" not in RUN_PURPOSES


def test_a_chat_turn_composed_during_a_run_would_still_be_recorded_separately():
    """The recorder captures whatever composes inside its block, so the *scope* is what keeps
    chat out — a run's block wraps the graph, and chat runs on its own request."""
    records = _under({}, lambda: system_prompt("chat.general"))
    assert set(records) == {"chat.general"}, "scope, not filtering, is what excludes chat"


# ── Serialisation: what lands in the JSON column ──────────────────────────────────


def test_captured_records_are_json_serialisable():
    records = _under({"planner": BODY}, lambda: [system_prompt(p) for p in sorted(RUN_PURPOSES)])
    round_tripped = json.loads(json.dumps(records))
    assert round_tripped == records
    for record in round_tripped.values():
        assert set(record) == {"purpose", "role", "policy", "overridden", "effective_prompt"}
