"""
The SSE frame generator, driven rather than grepped (parity Phase 6).

There were four copies of this loop — the server's session stream and run stream, and the
desktop's two — and no test drove any of them. `test_stream_replay_rules` checks them by
*reading their source*: it finds the `for ... in backlog` loop with a regex and asserts
which names are compared inside it. That is an honest response to code that could not be
called (each loop was a closure inside a route, over a Redis subscription or an in-process
bus), but it can only assert what the source looks like, never what a client receives.

Extracting the loop is what makes it testable. The hosts still build their own backlog and
their own live iterator — Redis pub/sub on one, an in-process bus on the other, which is a
real infrastructure difference — and hand both to one generator.

Every rule below was previously encoded four times.
"""

from __future__ import annotations

import json

import pytest

from app.services.event_stream import sse_frames

REPLAY_STOP = ("COMPLETED", "FAILED")
TERMINAL = ("COMPLETED", "FAILED", "HITL_READY", "PLAN_READY")


def _event(kind: str, **extra) -> dict:
    return {"type": kind, **extra}


async def _live(*items):
    for item in items:
        yield item


async def _collect(**kw) -> list[str]:
    return [frame async for frame in sse_frames(**kw)]


def _payloads(frames: list[str]) -> list[dict]:
    return [json.loads(f.split("data: ", 1)[1].strip()) for f in frames if "data: " in f]


def _ids(frames: list[str]) -> list[str | None]:
    return [
        f.split("id: ", 1)[1].split("\n", 1)[0] if f.startswith("id: ") else None for f in frames
    ]


# ── The connected preamble ────────────────────────────────────────────────────────


async def test_the_stream_opens_with_the_connected_frame_the_client_waits_for():
    frames = await _collect(
        connected={"type": "connected", "run_id": "r1"},
        backlog=[],
        live=_live(),
        replay_stop=REPLAY_STOP,
        terminal_stop=TERMINAL,
        already_done=True,
    )
    assert _payloads(frames)[0] == {"type": "connected", "run_id": "r1"}


# ── Replay ────────────────────────────────────────────────────────────────────────


async def test_replay_does_not_stop_at_a_gate():
    """The defect `test_stream_replay_rules` was written for. A client reconnecting with no
    `Last-Event-ID` replays from 0; stopping at the design gate hides everything the run did
    after it."""
    frames = await _collect(
        connected={"type": "connected"},
        backlog=[(1, _event("PLAN_READY")), (2, _event("agent_log")), (3, _event("COMPLETED"))],
        live=_live(),
        replay_stop=REPLAY_STOP,
        terminal_stop=TERMINAL,
        already_done=True,
    )
    assert [p["type"] for p in _payloads(frames)] == [
        "connected",
        "PLAN_READY",
        "agent_log",
        "COMPLETED",
    ]


async def test_replay_stops_at_a_true_terminal_and_drops_what_follows():
    frames = await _collect(
        connected={"type": "connected"},
        backlog=[(1, _event("COMPLETED")), (2, _event("agent_log"))],
        live=_live(),
        replay_stop=REPLAY_STOP,
        terminal_stop=TERMINAL,
        already_done=True,
    )
    assert [p["type"] for p in _payloads(frames)] == ["connected", "COMPLETED"]


async def test_every_replayed_event_carries_its_id_so_a_reconnect_can_resume():
    frames = await _collect(
        connected={"type": "connected"},
        backlog=[(7, _event("agent_log")), (9, _event("agent_log"))],
        live=_live(),
        replay_stop=REPLAY_STOP,
        terminal_stop=TERMINAL,
        already_done=True,
    )
    assert _ids(frames)[1:] == ["7", "9"]


# ── The live tail ─────────────────────────────────────────────────────────────────


async def test_the_live_tail_is_not_reached_when_the_run_is_already_finished():
    """`already_done` exists so a stream on a settled run closes after the backlog instead
    of waiting on a subscription nothing will ever publish to."""
    frames = await _collect(
        connected={"type": "connected"},
        backlog=[(1, _event("agent_log"))],
        live=_live((2, _event("agent_log", message="must not appear"))),
        replay_stop=REPLAY_STOP,
        terminal_stop=TERMINAL,
        already_done=True,
    )
    assert len(_payloads(frames)) == 2


async def test_the_live_tail_stops_at_a_gate_because_nothing_more_will_be_published():
    frames = await _collect(
        connected={"type": "connected"},
        backlog=[],
        live=_live((1, _event("agent_log")), (2, _event("PLAN_READY")), (3, _event("agent_log"))),
        replay_stop=REPLAY_STOP,
        terminal_stop=TERMINAL,
        already_done=False,
    )
    assert [p["type"] for p in _payloads(frames)] == ["connected", "agent_log", "PLAN_READY"]


async def test_an_event_already_replayed_is_not_delivered_twice():
    """The backlog snapshot and the live subscription overlap by construction — the
    subscription is opened before the backlog is read, so both can carry the same event."""
    frames = await _collect(
        connected={"type": "connected"},
        backlog=[(5, _event("agent_log", message="from backlog"))],
        live=_live((5, _event("agent_log", message="duplicate")), (6, _event("agent_log"))),
        replay_stop=REPLAY_STOP,
        terminal_stop=TERMINAL,
        already_done=False,
    )
    assert [p.get("message") for p in _payloads(frames)[1:]] == ["from backlog", None]


async def test_an_event_whose_durable_write_failed_is_delivered_without_advancing_the_cursor():
    """Phase 2a's other half. An event with no id was never stored, so a client cannot
    resume from it — it is shown, and `Last-Event-ID` stays where it was."""
    frames = await _collect(
        connected={"type": "connected"},
        backlog=[(4, _event("agent_log"))],
        live=_live((None, _event("agent_log", message="unstored")), (5, _event("COMPLETED"))),
        replay_stop=REPLAY_STOP,
        terminal_stop=TERMINAL,
        already_done=False,
    )
    assert [p.get("message") for p in _payloads(frames)[1:]] == [None, "unstored", None]
    assert _ids(frames) == [None, "4", None, "5"]


async def test_an_unstored_terminal_event_still_closes_the_stream():
    """It has no id, but it is still the last thing this run will say."""
    frames = await _collect(
        connected={"type": "connected"},
        backlog=[],
        live=_live((None, _event("COMPLETED")), (1, _event("agent_log", message="after the end"))),
        replay_stop=REPLAY_STOP,
        terminal_stop=TERMINAL,
        already_done=False,
    )
    assert [p["type"] for p in _payloads(frames)] == ["connected", "COMPLETED"]


# ── The two stop-lists are genuinely different ────────────────────────────────────


@pytest.mark.parametrize("gate", ["PLAN_READY", "HITL_READY"])
async def test_a_gate_ends_the_tail_but_not_the_replay(gate):
    """Stated once here, where it used to be stated in four places and got it wrong in
    three of them."""
    after_gate = await _collect(
        connected={"type": "connected"},
        backlog=[(1, _event(gate)), (2, _event("agent_log"))],
        live=_live(),
        replay_stop=REPLAY_STOP,
        terminal_stop=TERMINAL,
        already_done=True,
    )
    assert len(_payloads(after_gate)) == 3, "replay must continue past the gate"

    tail = await _collect(
        connected={"type": "connected"},
        backlog=[],
        live=_live((1, _event(gate)), (2, _event("agent_log"))),
        replay_stop=REPLAY_STOP,
        terminal_stop=TERMINAL,
        already_done=False,
    )
    assert len(_payloads(tail)) == 2, "the tail must close at the gate"
