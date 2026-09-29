"""A failing research task fails its node alone: siblings stop, and the recorded reason is its own.

The defect this pins: `executor_node` fanned out with `asyncio.gather`, which returns the
first exception while the other children keep running. The orphans kept calling the model
after the run had failed, and kept writing events through the host's sink — on the server a
sink bound to the *same* `AsyncSession` the run driver closes on the way out. The close met a
write in flight and SQLAlchemy refused it, so the run was recorded as failing on

    Method 'close()' can't be called here; method '_connection_for_bind()' is already in
    progress ...

and the provider error that actually stopped it survived only as `__context__`, which no
host records. That breaks the one rule a failure reason has: say what failed.

**The integration test needs Postgres.** The masking reproduced 200/200 on asyncpg and 0/200
on aiosqlite, whose close does not race the write the same way — a SQLite harness here would
pass with the defect present. It also keeps the real `agent_log_sink`: stubbing the sink
would stub the collision under test. Only `publish_event` (Redis) is replaced, as in
`test_sink_concurrency.py`.
"""

from __future__ import annotations

import asyncio
import dataclasses
import time
import uuid

import pytest

from research_engine import graph as graph_mod
from research_engine.concurrency import gather_or_cancel
from research_engine.events import emit, reset_emitter, set_emitter
from research_engine.runconfig import get_run_config, reset_run_config, set_run_config
from tests.conftest import requires_db

# ── The fan-out ─────────────────────────────────────────────────────────────────────


async def test_results_come_back_in_argument_order_whatever_finishes_first():
    async def after(delay, value):
        await asyncio.sleep(delay)
        return value

    assert await gather_or_cancel(after(0.03, "a"), after(0.0, "b"), after(0.01, "c")) == [
        "a",
        "b",
        "c",
    ]
    assert await gather_or_cancel() == []


async def test_a_failure_cancels_the_siblings_and_waits_them_out_before_raising():
    boom = RuntimeError("Event loop is closed")
    finished_sleeping = []
    siblings: list[asyncio.Task] = []

    async def slow_sibling():
        siblings.append(asyncio.current_task())
        await asyncio.sleep(3600)
        finished_sleeping.append(True)

    async def failer():
        await asyncio.sleep(0.01)
        raise boom

    with pytest.raises(RuntimeError) as raised:
        await gather_or_cancel(slow_sibling(), failer(), slow_sibling())

    assert raised.value is boom, "the original exception object, traceback intact"
    assert all(t.done() and t.cancelled() for t in siblings), "a sibling outlived the fan-out"
    assert finished_sleeping == []


async def test_the_failure_reported_is_the_one_that_happened_first_not_the_first_argument():
    """A failure often breaks state its siblings share — the sink's session and lock — so the
    next sibling to touch it fails too, within the same turn of the loop. The one reported must
    be the cause, not a consequence that happens to sit earlier in the argument list."""
    lock = asyncio.Lock()
    broken = False

    async def consequence():
        await asyncio.sleep(0.01)
        async with lock:
            if broken:
                raise RuntimeError("This session is in 'committed' state")

    async def cause():
        nonlocal broken
        async with lock:
            await asyncio.sleep(0.05)
            broken = True
            raise RuntimeError("provider quota exhausted")

    with pytest.raises(RuntimeError, match="provider quota exhausted"):
        await gather_or_cancel(consequence(), cause())


async def test_cancelling_the_fan_out_stops_its_children_too():
    children: list[asyncio.Task] = []

    async def child():
        children.append(asyncio.current_task())
        await asyncio.sleep(3600)

    fan_out = asyncio.ensure_future(gather_or_cancel(child(), child()))
    await asyncio.sleep(0.01)
    fan_out.cancel()
    with pytest.raises(asyncio.CancelledError):
        await fan_out

    assert len(children) == 2 and all(t.cancelled() for t in children)


async def test_a_fan_out_cancelled_while_it_waits_out_a_failure_still_waits():
    """The fan-out's own caller can be cancelled while it waits for a failed round's siblings
    to stop — a worker's soft time limit unwinds the task exactly that way. Giving up the wait
    there would leave siblings running their cleanup (an event write landing) with nothing
    left to await them."""
    children: list[asyncio.Task] = []

    async def slow_to_stop():
        children.append(asyncio.current_task())
        try:
            await asyncio.sleep(3600)
        finally:
            await asyncio.sleep(0.05)

    async def failer():
        await asyncio.sleep(0.01)
        raise RuntimeError("provider failed")

    fan_out = asyncio.ensure_future(gather_or_cancel(slow_to_stop(), failer()))
    await asyncio.sleep(0.02)
    fan_out.cancel()
    with pytest.raises(asyncio.CancelledError):
        await fan_out

    assert children and all(t.done() for t in children), "a sibling outlived the fan-out"


async def test_an_event_being_written_when_the_sibling_is_cancelled_is_written_whole():
    """Cancellation lands between writes, never inside one: interrupting the host's commit
    halfway leaked the pooled connection on aiosqlite and dropped it on asyncpg."""
    written: list[str] = []
    write_started = asyncio.Event()

    async def slow_sink(_sid, event):
        write_started.set()
        await asyncio.sleep(0.05)
        written.append(event["message"])

    async def emitting_sibling():
        await emit("sid", "agent_log", message="in flight")
        await emit("sid", "agent_log", message="never started")

    async def failer():
        await write_started.wait()
        raise RuntimeError("provider failed")

    token = set_emitter(slow_sink)
    try:
        with pytest.raises(RuntimeError, match="provider failed"):
            await gather_or_cancel(emitting_sibling(), failer())
    finally:
        reset_emitter(token)

    assert written == ["in flight"]


# ── The nodes that fan out ──────────────────────────────────────────────────────────


@pytest.fixture
def tasks_run_concurrently():
    """These tests need siblings in flight together, and `max_parallel_tasks` otherwise comes
    from the environment — at 1 (a documented setting, and what a rate-limited local router
    needs) the failing task waits on a sibling the semaphore never starts, and the test hangs
    rather than failing."""
    token = set_run_config(dataclasses.replace(get_run_config(), max_parallel_tasks=3))
    yield
    reset_run_config(token)


def _state(n_tasks: int, session_id: str = "masking-test") -> dict:
    return {
        "session_id": session_id,
        "tasks": [{"id": i, "query": f"task {i}"} for i in range(1, n_tasks + 1)],
        "evidence": [],
        "verdicts": {},
        "retries": {},
        "research_round": 0,
        "cost_usd": 0.0,
        "tokens_input": 0,
        "tokens_output": 0,
        "started_at": time.time(),
    }


@pytest.mark.usefixtures("tasks_run_concurrently")
@pytest.mark.parametrize(
    ("node", "child"),
    [(graph_mod.executor_node, "_research_one"), (graph_mod.critic_node, "_criticize_one")],
    ids=["executor", "critic"],
)
async def test_a_node_whose_task_fails_stops_its_other_tasks(node, child, monkeypatch):
    """Orphans after a failure call the model for a run that has already failed — spend the
    failed node never returns, so no state update can record it."""
    still_calling_the_model = []

    async def fake_child(state, task, *_rest):
        if task["id"] == 1:
            await asyncio.sleep(0.01)
            raise RuntimeError("Event loop is closed")
        await asyncio.sleep(3600)
        still_calling_the_model.append(task["id"])

    monkeypatch.setattr(graph_mod, child, fake_child)

    with pytest.raises(RuntimeError, match="Event loop is closed"):
        await asyncio.wait_for(node(_state(3)), timeout=5)

    await asyncio.sleep(0)
    pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    assert pending == [], f"tasks still running after the node failed: {pending}"
    assert still_calling_the_model == []


@requires_db
@pytest.mark.usefixtures("tasks_run_concurrently")
async def test_the_recorded_failure_is_the_provider_error_not_the_session_close(
    migrated_database,  # noqa: ARG001 - schema must exist
    monkeypatch,
):
    """`execute_run`'s shape exactly: one session, the real sink bound to it, the executor run
    inside, and the session closed on the way out while a sibling is mid-write.

    The sibling is parked inside `_connection_for_bind` by a pool listener — the state the
    production traceback names — so the collision is deterministic rather than a timing
    sweep; it is released shortly after the failing task raises."""
    from sqlalchemy import event
    from sqlalchemy.util import await_only

    from app import adapters
    from app.db.base import AsyncSessionLocal, engine

    async def no_redis(_session_id, _event):
        return None

    monkeypatch.setattr(adapters, "publish_event", no_redis)

    park = {"armed": False, "inside": asyncio.Event(), "release": asyncio.Event()}

    def park_checkout(*_args):
        if park["armed"]:
            park["armed"] = False
            park["inside"].set()
            await_only(park["release"].wait())

    async def fake_research(state, task, guard):
        if task["id"] == 1:
            await park["inside"].wait()
            asyncio.get_running_loop().call_later(0.3, park["release"].set)
            raise RuntimeError("Event loop is closed")
        park["armed"] = True
        await emit(state["session_id"], "agent_log", agent="executor", message="Researching")
        await asyncio.sleep(3600)

    monkeypatch.setattr(graph_mod, "_research_one", fake_research)
    event.listen(engine.sync_engine, "checkout", park_checkout)
    run_id = str(uuid.uuid4())
    try:
        with pytest.raises(RuntimeError) as raised:
            async with AsyncSessionLocal() as db:
                token = set_emitter(adapters.agent_log_sink(db, run_id))
                try:
                    await graph_mod.executor_node(_state(2, session_id=run_id))
                finally:
                    reset_emitter(token)

        assert str(raised.value) == "Event loop is closed", (
            f"recorded {type(raised.value).__name__}: {raised.value}"
        )
        assert park["inside"].is_set(), "the sibling never reached the database"
        pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
        assert pending == [], f"tasks still running after the session closed: {pending}"
        assert engine.pool.checkedout() == 0, "a connection was left checked out"
    finally:
        event.remove(engine.sync_engine, "checkout", park_checkout)
        park["release"].set()
        await engine.dispose()
