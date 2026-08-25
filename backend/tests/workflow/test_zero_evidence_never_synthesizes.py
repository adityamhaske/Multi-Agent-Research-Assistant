"""A run that gathered nothing must fail, not write a report from the model's memory.

The scar this pins (run `63091d21`, 2026-08-25): a local planner proposed four subtopics
and marked every one of them `include: false`. The V2 plan-review endpoint had no guard —
V1's `research.submit_plan` has always had one, and V2 shipped without it — so the plan
was approved as proposed. `plan_gate_node` then filtered the task list down to `[]`, the
executor ran nothing, the critic evaluated "0 task(s)", and the synthesizer still produced
a fluent 347-word report. Its citation-repair pass then attached markers `[1]`–`[7]` to
sentences whose sources did not exist, and the run parked at the report gate offering an
approvable artifact backed by zero evidence.

That is the exact artifact this product exists to make impossible, so it is guarded in
three places:

  1. the API refuses the approval          (`submit_plan_review`)
  2. the graph refuses to execute a plan   (`route_after_plan_gate`, `route_after_planner`)
  3. the graph refuses to synthesize       (`route_after_critic`)

This module covers 2 and 3, which are pure functions over graph state. Guard 1 is an HTTP
concern and is tested in `test_v2_api.py`, next to the fixture that builds a run parked at
the design gate — the desktop sidecar imports that same handler, so both hosts are covered
by it (AGENTS.md, "two hosts, one contract").

Each test below was verified to FAIL with its own guard reverted; the negative controls
are the `*_still_*` tests, which fail if a guard is made unconditional and starts killing
runs that legitimately have work to do.
"""

from __future__ import annotations

import time

from research_engine import graph as graph_mod

# A state that has genuinely gathered something. Used as the negative control throughout:
# every guard here must leave this state alone.
_ONE_PIECE_OF_EVIDENCE = [{"source_url": "https://example.com/a", "snippet": "verbatim text"}]


def _critic_state(**overrides) -> dict:
    state = {
        "cost_usd": 0.0,
        "tokens_input": 0,
        "started_at": time.time(),
        "tasks": [{"id": 1}],
        "verdicts": {"1": {"passed": True}},
        "retries": {},
        "evidence": _ONE_PIECE_OF_EVIDENCE,
    }
    state.update(overrides)
    return state


# ── 2. The graph refuses to execute a plan with nothing in it ──────────────────────


def test_a_plan_gate_that_selected_nothing_routes_to_failer():
    """The reviewer excluded every subtopic, so there is nothing to search.

    `plan_gate_node` has always filtered `include: false` out of the task list; what was
    missing is that the router then sent the empty result to the executor regardless.
    """
    assert graph_mod.route_after_plan_gate({"tasks": []}) == "failer"


def test_a_plan_gate_with_work_left_still_reaches_the_executor():
    assert graph_mod.route_after_plan_gate({"tasks": [{"id": 1, "query": "q"}]}) == "executor"


def test_a_planner_that_proposed_nothing_routes_to_failer():
    """Fails before the gate, so the skip-gate path cannot slide through to a report.

    `skip_plan_gate` is `True` for the CLI and the eval harness, which is precisely the
    population that would otherwise reach the synthesizer with an empty task list and no
    human anywhere to notice.
    """
    assert graph_mod.route_after_planner({"tasks": []}) == "failer"


def test_a_planner_error_still_wins_over_the_empty_task_check():
    """A provider error must keep reporting itself, not be relabelled 'nothing selected'.

    Ordering control: the planner's own error is the more specific cause, and `graph.py`
    has been burned before by a real provider failure surfacing as a vague message.
    """
    assert graph_mod.route_after_planner(
        {"error": "planner: provider error — 429", "tasks": []}
    ) == ("failer")
    reason = graph_mod.failer_node({"error": "planner: provider error — 429", "tasks": []})["error"]
    assert "429" in reason


# ── 3. The graph refuses to synthesize what it cannot cite ─────────────────────────


def test_every_task_finishing_with_no_evidence_routes_to_failer():
    """Tasks ran, found nothing, and the run stops instead of drafting from memory."""
    assert graph_mod.route_after_critic(_critic_state(evidence=[])) == "failer"


def test_a_run_that_gathered_evidence_still_reaches_the_synthesizer():
    assert graph_mod.route_after_critic(_critic_state()) == "contradiction_detector"


def test_the_budget_guard_still_outranks_the_no_evidence_guard():
    """A run killed by its cost ceiling must say so, not blame the empty evidence list.

    Both conditions hold at once here; the breach is the actionable one.
    """
    from research_engine.runconfig import RunConfig, reset_run_config, set_run_config

    token = set_run_config(RunConfig(max_cost_per_session_usd=0.50))
    try:
        state = _critic_state(cost_usd=999.0, evidence=[])
        assert graph_mod.route_after_critic(state) == "failer"
        assert "cost ceiling" in graph_mod.failer_node(state)["error"]
    finally:
        reset_run_config(token)


# ── The failure a user actually reads ──────────────────────────────────────────────


def test_the_two_nothing_to_research_failures_are_worded_apart():
    """ "Nothing was selected" and "nothing was found" need different remedies.

    Collapsing them would send a user to check their search providers when what really
    happened is that they unchecked every subtopic — which is exactly what happened in
    the run this module documents.
    """
    nothing_selected = graph_mod.failer_node({"tasks": [], "evidence": []})["error"]
    nothing_found = graph_mod.failer_node({"tasks": [{"id": 1}], "evidence": []})["error"]

    assert "no research tasks were selected" in nothing_selected
    assert "subtopic" in nothing_selected

    assert "no evidence was gathered" in nothing_found
    assert "search provider" in nothing_found

    assert nothing_selected != nothing_found


def test_a_healthy_run_reaching_the_failer_still_reports_the_retry_limit():
    """Negative control: the guards must not swallow the pre-existing failure reason."""
    reason = graph_mod.failer_node(
        {"tasks": [{"id": 1}], "evidence": _ONE_PIECE_OF_EVIDENCE},
    )["error"]
    assert "retry limit reached" in reason


# ── The wiring, not just the functions ─────────────────────────────────────────────


def test_the_plan_gate_can_actually_reach_the_failer_node():
    """A router returning 'failer' is inert unless the compiled edge map carries it.

    `add_conditional_edges` raises at runtime on a branch the map does not name, so this
    would be a crash inside a background task — the failure mode AGENTS.md records for a
    missing key in `sidecar._apply_outcome`: the run sits there with nothing in the log.
    """
    edges = {
        (e.source, e.target) for e in graph_mod.build_graph(checkpointer=None).get_graph().edges
    }
    assert ("plan_gate", "failer") in edges
    assert ("planner", "failer") in edges
    assert ("critic", "failer") in edges
    # The paths that must survive: guarding the empty case cannot cost the normal one.
    assert ("plan_gate", "executor") in edges
    assert ("critic", "contradiction_detector") in edges
