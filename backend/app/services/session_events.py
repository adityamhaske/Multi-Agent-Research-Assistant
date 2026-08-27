"""
One `RunOutcome` → one lifecycle event, for both hosts.

A session's pause and terminal events are the only thing a live client has to act on: the
design gate, the review gate, completion and failure. The *type* was already shared
vocabulary. The payload was not — the server published measured numbers and the desktop
published `data: null` for every one of them, so a desktop client had no task count at the
design gate, no word or source count at the review gate, no elapsed time or cost on
completion, and a failure reason in `message` where the server puts it in `data.reason`.

`AGENTS.md` names the trap this closes: *"A new `RunOutcome.status` →
`pipeline_runner::_persist_outcome` **and** both dict literals in
`sidecar::_apply_outcome`."* Three homes for one mapping. This is the one home, and
`tests/workflow/test_lifecycle_event_payloads.py` asserts both hosts resolve to this exact
function rather than to their own copy of it.

Stdlib and `research_engine` only — the desktop imports it, so nothing here may reach
`app.config` (#50).
"""

from __future__ import annotations

from research_engine.events import make_event
from research_engine.runner import RunOutcome

#: `RunOutcome.status` → the event type a client branches on. Both stream stop-lists are
#: written in terms of these names.
EVENT_TYPES: dict[str, str] = {
    "awaiting_plan": "PLAN_READY",
    "awaiting_approval": "HITL_READY",
    "completed": "COMPLETED",
    "failed": "FAILED",
}


def lifecycle_event(outcome: RunOutcome) -> dict:
    """The event to publish once this outcome has been committed.

    Every number is measured off the outcome rather than defaulted. A payload of zeroes
    would satisfy a shape check and tell a client nothing — and on a run that reached a
    gate having spent money, a `cost_usd` of `0.0` would be the unmeasured-vs-zero lie this
    repository treats as a P0 class. `cost_usd` is reported even at the design gate, where
    it is normally zero, because a *resumed* run reaching that gate has a real number.
    """
    event_type = EVENT_TYPES[outcome.status]

    if outcome.status == "awaiting_plan":
        data = {
            "task_count": len(outcome.plan_tasks),
            "outline_section_count": len(outcome.plan_outline),
            "cost_usd": round(outcome.cost_usd, 4),
        }
    elif outcome.status == "awaiting_approval":
        data = {
            "word_count": len((outcome.draft_report or "").split()),
            "source_count": len(outcome.sources),
            "cost_usd": round(outcome.cost_usd, 4),
        }
    elif outcome.status == "failed":
        # In `data`, not `message`: the server has always put it here, and a client
        # reading `data.reason` found nothing on the desktop.
        data = {"reason": outcome.error}
    else:
        data = {
            "elapsed_s": float(outcome.elapsed_seconds or 0),
            "cost_usd": round(outcome.cost_usd, 4),
        }

    return make_event(event_type, data=data)
