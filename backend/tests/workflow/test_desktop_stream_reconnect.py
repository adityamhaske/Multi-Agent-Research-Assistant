"""
The desktop SSE cursor is one number, not two (parity Phase 2a).

**The defect.** `PersistingSink` assigned each event an id from `SessionEventBus`, a
per-session counter starting at 1, and wrote that number into `payload["id"]` and into the
live frame. The *backlog* — what a reconnecting client replays — is read from `agent_logs`
and framed with `agent_logs.id`, a global autoincrement. Two id spaces for one cursor.

The server never had this: `adapters.agent_log_sink` writes the row, flushes, and sets
`event["id"] = row.id`. One number.

**Why it was invisible.** On the first session of a fresh database the two counters happen
to coincide, and every test gets a fresh `tmp_path` and drives one session. In a real
installed app the first-launch demo seed guarantees the user's *first real run* is the
second session, where they do not.

**What it cost.** A client reconnecting with `Last-Event-ID` taken from the live tail (a
small number) replays the whole backlog again, because every row id exceeds it — duplicate
events in the UI — and then sets `seen_max` to a large row id, after which
`if eid <= seen_max: continue` drops **every subsequent live event**. The stream appears to
freeze until the run terminates. It affected both the session stream and the run stream.

So the invariant these tests pin is the one the server already had: **the id a client sees
live is the same number it would see replaying that event from the backlog.**
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.models.agent_log import AgentLog
from desktop.sidecar import PersistingSink, SessionEventBus, create_sidecar_app

TOKEN = "test-reconnect-token"


@pytest.fixture
async def host(tmp_path):
    """A sidecar with its demo seed suppressed, so session numbering starts where we say."""
    from desktop.sidecar import mark_demo_seeded

    mark_demo_seeded(tmp_path)
    app = create_sidecar_app(data_dir=tmp_path, token=TOKEN, fake=True)
    async with app.router.lifespan_context(app):
        yield app


async def _emit(app, session_id: uuid.UUID, count: int) -> SessionEventBus:
    bus: SessionEventBus = app.state.sidecar["bus"]
    sink = PersistingSink(bus, app.state.sidecar["db"])
    for i in range(count):
        await sink(str(session_id), {"type": "agent_log", "message": f"event {i}"})
    return bus


async def _row_ids(app, session_id: uuid.UUID) -> list[int]:
    async with app.state.sidecar["db"]() as db:
        rows = (
            (
                await db.execute(
                    select(AgentLog)
                    .where(AgentLog.session_id == session_id)
                    .order_by(AgentLog.id.asc())
                )
            )
            .scalars()
            .all()
        )
        return [row.id for row in rows]


async def test_the_live_id_and_the_replay_id_are_the_same_number(host):
    """Two sessions, because on the first one the two counters coincide by accident."""
    first, second = uuid.uuid4(), uuid.uuid4()
    await _emit(host, first, 5)
    bus = await _emit(host, second, 3)

    live = [eid for eid, _ in bus.backlog(str(second))]
    replay = await _row_ids(host, second)

    assert live == replay, (
        f"the live tail hands clients {live} and the backlog hands them {replay} for the "
        "same three events — a reconnecting client cannot reconcile the two"
    )


async def test_the_persisted_payload_carries_the_id_the_row_was_given(host):
    """`payload["id"]` is what a bundle's trace and any offline reader see."""
    session_id = uuid.uuid4()
    await _emit(host, uuid.uuid4(), 4)
    await _emit(host, session_id, 2)

    async with host.state.sidecar["db"]() as db:
        rows = (
            (
                await db.execute(
                    select(AgentLog)
                    .where(AgentLog.session_id == session_id)
                    .order_by(AgentLog.id.asc())
                )
            )
            .scalars()
            .all()
        )
    mismatched = [
        (row.id, row.payload.get("id")) for row in rows if row.payload.get("id") != row.id
    ]
    assert not mismatched, f"(row.id, payload['id']) disagree: {mismatched}"


async def test_ids_stay_monotonic_across_sessions_so_a_cursor_never_goes_backwards(host):
    """`Last-Event-ID` is compared with `<=`, so a second session restarting at 1 would
    make every one of its events look already-seen to a client holding a larger cursor."""
    first, second = uuid.uuid4(), uuid.uuid4()
    await _emit(host, first, 3)
    bus = await _emit(host, second, 3)

    first_ids = [eid for eid, _ in bus.backlog(str(first))]
    second_ids = [eid for eid, _ in bus.backlog(str(second))]
    assert min(second_ids) > max(first_ids), (
        f"session two restarts its ids at {min(second_ids)} while session one reached "
        f"{max(first_ids)} — the cursor is not global"
    )
