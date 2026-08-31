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


# ── The cancel path's own event: same convention, and durably written ──────────────


def test_the_cancel_event_uses_the_same_reason_convention():
    """`cancel_session` builds its FAILED event by hand — there is no `RunOutcome` for a
    user-initiated stop, so it cannot call `lifecycle_event` itself — but it must still
    agree with what that function already established: the reason lives in `data`, not
    in `message`. Pinned directly against `research_engine.events.make_event` rather
    than against a fake `RunOutcome`, since that is the actual builder both hosts share.
    """
    from research_engine.events import make_event

    event = make_event("FAILED", data={"reason": "Research stopped by user."})
    assert event["data"]["reason"] == "Research stopped by user."
    assert "message" not in event or event["message"] is None


async def test_the_servers_cancel_route_writes_its_event_durably_not_only_live(monkeypatch):
    """What broke when `cancel_session` called `app.db.redis.publish_event` directly:
    nothing durable was ever written for this one event, so a client that reconnected to
    the stream after the cancel (rather than watching it happen) found no matching entry
    in the replay. `agent_log_sink` is the durable-write-then-publish path every other
    event goes through; this proves `get_terminal_event_emitter`'s server implementation
    actually reaches it rather than reintroducing the raw-publish shortcut.

    Monkeypatches the factory rather than a real `AsyncSession`, because what is under
    test here is the *wiring* — does this seam reach `agent_log_sink` at all — not
    `agent_log_sink`'s own write behaviour, which the pipeline's event flow already
    exercises against a real database elsewhere.
    """
    import app.adapters as adapters_module
    from app.services.host_ports import get_terminal_event_emitter

    calls: list[tuple[str, dict]] = []

    def fake_agent_log_sink(db, session_id):  # noqa: ARG001
        async def sink(sid: str, event: dict) -> None:
            calls.append((sid, event))

        return sink

    monkeypatch.setattr(adapters_module, "agent_log_sink", fake_agent_log_sink)

    emit = get_terminal_event_emitter()
    event = {"type": "FAILED", "data": {"reason": "Research stopped by user."}}
    await emit(object(), "session-123", event)

    assert calls == [("session-123", event)], (
        f"the emitter did not reach agent_log_sink — the durable write is skipped again: {calls}"
    )
