"""The agent-log sink must survive concurrent emitters (docs/12 M5, defect D4).

`agent_log_sink` binds one `AsyncSession` to a whole run. That was safe while the graph
was strictly sequential. M7 gave the executor parallel tasks, and each task emits its own
progress events — so two coroutines could reach `flush()` on the same session at once and
SQLAlchemy raised `InvalidRequestError: Session is already flushing`, failing the run
before it ever reached the review gate.

Nothing in the suite caught it: every other test drives the sink from a single coroutine,
which is exactly the case that works.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest

from app import adapters


class FlushGuardSession:
    """Stand-in for `AsyncSession` that reproduces its re-entrancy guard.

    SQLAlchemy raises when a second `flush()` begins while one is in progress. The
    `await` inside the guarded region is what makes this a real test: it hands control
    back to the event loop mid-flush, so an unsynchronised sink interleaves there and
    trips the guard, precisely as it did against a live Postgres.
    """

    def __init__(self) -> None:
        self._flushing = False
        self.rows: list[object] = []
        self.commits = 0
        self.max_concurrent_flushes = 0

    def add(self, row: object) -> None:
        self.rows.append(row)

    async def flush(self) -> None:
        if self._flushing:
            raise RuntimeError("Session is already flushing")
        self._flushing = True
        self.max_concurrent_flushes = max(self.max_concurrent_flushes, 1)
        try:
            await asyncio.sleep(0)
            for i, row in enumerate(self.rows, start=1):
                if getattr(row, "id", None) is None:
                    row.id = i
        finally:
            self._flushing = False

    async def commit(self) -> None:
        await asyncio.sleep(0)
        self.commits += 1


@pytest.fixture
def captured_publishes(monkeypatch) -> list[int]:
    published: list[int] = []

    async def fake_publish(session_id: str, event: dict) -> None:
        await asyncio.sleep(0)  # a real Redis round-trip yields here too
        published.append(event["id"])

    monkeypatch.setattr(adapters, "publish_event", fake_publish)
    return published


@pytest.mark.asyncio
async def test_parallel_emitters_do_not_overlap_on_the_shared_session(captured_publishes):
    """Twelve concurrent events — the shape M7's parallel executor produces."""
    db = FlushGuardSession()
    sink = adapters.agent_log_sink(db, str(uuid.uuid4()))

    await asyncio.gather(
        *(
            sink("ignored", {"type": "agent_log", "agent": "executor", "message": f"task {i}"})
            for i in range(12)
        )
    )

    assert db.commits == 12
    assert len(captured_publishes) == 12


@pytest.mark.asyncio
async def test_publish_order_matches_commit_order(captured_publishes):
    """`Last-Event-ID` replay needs a monotonic cursor.

    If the lock were released after the commit but before the publish, two emitters could
    reach Redis out of order and a reconnecting client would resume past an event whose id
    is lower than one it had already seen — silently losing it.
    """
    db = FlushGuardSession()
    sink = adapters.agent_log_sink(db, str(uuid.uuid4()))

    await asyncio.gather(
        *(sink("ignored", {"type": "agent_log", "agent": "executor"}) for _ in range(8))
    )

    assert captured_publishes == sorted(captured_publishes)


@pytest.mark.asyncio
async def test_each_event_is_stamped_with_its_own_row_id(captured_publishes):
    """A shared session must not let one event's id leak onto another's payload."""
    db = FlushGuardSession()
    sink = adapters.agent_log_sink(db, str(uuid.uuid4()))

    events = [{"type": "agent_log", "agent": "executor", "n": i} for i in range(6)]
    await asyncio.gather(*(sink("ignored", e) for e in events))

    ids = [e["id"] for e in events]
    assert len(set(ids)) == len(ids), f"duplicate row ids handed out: {ids}"
