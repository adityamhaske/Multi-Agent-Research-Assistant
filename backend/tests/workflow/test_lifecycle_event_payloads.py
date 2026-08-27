"""
A session's lifecycle event says the same thing on both hosts (parity Phase 2c).

The server publishes `PLAN_READY` with `{task_count, outline_section_count, cost_usd}`,
`HITL_READY` with `{word_count, source_count, cost_usd}`, `COMPLETED` with
`{elapsed_s, cost_usd}` and `FAILED` with `{reason}`. The desktop published
`make_event(lifecycle, message=outcome.error)` — the right *type*, and `data` set to
`None` for all four.

So every consumer that reads those numbers got nothing on the desktop: no task count at
the design gate, no word or source count at the review gate, no elapsed time or cost on
completion, and a failure reason in `message` where the server puts it in `data.reason`.
Nothing raised, nothing 404'd, and the parity route checks saw two identical event *types*.

The mapping is one function now. These tests pin its output and pin that both hosts use
it, rather than that two implementations currently agree.
"""

from __future__ import annotations

import pytest

from app.services.session_events import lifecycle_event
from research_engine.runner import RunOutcome

PLAN = [{"id": 1, "query": "q", "rationale": "r"}, {"id": 2, "query": "q2", "rationale": "r2"}]


@pytest.mark.parametrize(
    ("outcome", "expected_type", "expected_data"),
    [
        (
            RunOutcome(
                status="awaiting_plan",
                plan_tasks=PLAN,
                plan_outline=["Findings", "Limits"],
                cost_usd=0.0021,
            ),
            "PLAN_READY",
            {"task_count", "outline_section_count", "cost_usd"},
        ),
        (
            RunOutcome(
                status="awaiting_approval",
                draft_report="Recall rose [1]. A second sentence [2].",
                sources=[{"n": 1}, {"n": 2}, {"n": 3}],
                cost_usd=0.004,
            ),
            "HITL_READY",
            {"word_count", "source_count", "cost_usd"},
        ),
        (
            RunOutcome(status="completed", final_report="done", elapsed_seconds=4.5, cost_usd=0.01),
            "COMPLETED",
            {"elapsed_s", "cost_usd"},
        ),
        (
            RunOutcome(status="failed", error="the planner produced no tasks"),
            "FAILED",
            {"reason"},
        ),
    ],
    ids=["plan gate", "review gate", "completed", "failed"],
)
def test_each_outcome_maps_to_one_event_with_the_documented_data(
    outcome, expected_type, expected_data
):
    event = lifecycle_event(outcome)
    assert event["type"] == expected_type
    assert set(event["data"]) == expected_data


def test_the_numbers_are_measured_from_the_outcome_not_defaulted():
    """A payload of zeroes would satisfy a key-set check and tell a client nothing."""
    plan = lifecycle_event(
        RunOutcome(status="awaiting_plan", plan_tasks=PLAN, plan_outline=["A"], cost_usd=0.002)
    )
    assert plan["data"]["task_count"] == 2
    assert plan["data"]["outline_section_count"] == 1

    gate = lifecycle_event(
        RunOutcome(
            status="awaiting_approval",
            draft_report="one two three",
            sources=[{"n": 1}, {"n": 2}],
        )
    )
    assert gate["data"]["word_count"] == 3
    assert gate["data"]["source_count"] == 2


def test_a_failure_reason_travels_in_data_where_the_server_puts_it():
    """The desktop put it in `message`, so a client reading `data.reason` saw nothing."""
    event = lifecycle_event(RunOutcome(status="failed", error="exhausted quota"))
    assert event["data"]["reason"] == "exhausted quota"


def test_every_runner_status_is_mapped():
    """The AGENTS.md trap, at the source rather than in one host's dict literal.

    "A new `RunOutcome.status` → `pipeline_runner::_persist_outcome` *and* **both** dict
    literals in `sidecar::_apply_outcome`." There is one mapping now, so a new status has
    one place to be added — and this fails until it is.
    """
    import typing

    from research_engine.runner import RunStatus

    for status in typing.get_args(RunStatus):
        event = lifecycle_event(RunOutcome(status=status))
        assert event["type"], f"{status} maps to no lifecycle event"
        assert event["data"] is not None, f"{status} publishes a null data payload"


def test_both_hosts_use_this_mapping_rather_than_their_own():
    """Identity, not equality: two functions that agree today are two homes."""
    from app.workers import pipeline_runner
    from desktop import sidecar

    assert pipeline_runner.lifecycle_event is lifecycle_event
    assert sidecar.lifecycle_event is lifecycle_event
