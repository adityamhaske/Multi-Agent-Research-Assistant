"""
The server's own run driver captures provenance — driven through `execute_run` itself.

**Why this file exists.** PR-7b first shipped with `recording_provenance()` named as an item
of `execute_run`'s `async with`. The recorder is synchronous, so that raised `TypeError`
before the graph started and **every server research run failed on entry**. The whole suite
stayed green: the unit tests call `persist_outcome` directly, and the parity harness restates
`execute_run`'s body rather than calling it — so nothing executed the real driver past its
Redis lock. Only golden-e2e's real Celery worker reached the line, and it caught it.

So this drives the real function. What is stubbed is infrastructure the test process cannot
open — Redis, the Postgres checkpointer, and the model call. What stays real is the thing
under test: `execute_run`'s own context management, the recorder, `system_prompt`, and
`persist_outcome` writing the row. The fake graph calls the real `system_prompt`, exactly as
a node does, so the recorder `execute_run` installs is the one that must catch it.
"""

from __future__ import annotations

import contextlib
import uuid
from datetime import UTC, datetime

from sqlalchemy import insert

from app import run_lifecycle
from app.models.project import Project
from app.models.research import ResearchRun
from app.models.user import User
from research_engine.prompt_composition import PURPOSE_CONSTANTS, system_prompt
from research_engine.runner import RunOutcome
from tests.sqlite_support import open_db


async def _noop(*_a, **_k):
    return None


async def _granted(*_a, **_k):
    return True


class _Saver:
    async def setup(self) -> None:
        return None


@contextlib.asynccontextmanager
async def _saver_cm(*_a, **_k):
    yield _Saver()


class _Engine:
    async def dispose(self) -> None:
        return None


async def _stage(tmp_path, monkeypatch, fake_graph):
    """A real run row, the real driver, infrastructure swapped for things a test can open."""
    from langgraph.checkpoint.postgres import aio as pg_aio

    import app.adapters as adapters
    import app.db.base as db_base
    import app.db.redis as redis_mod
    import research_engine.runner as runner_mod

    ctx = open_db(tmp_path / "execute.sqlite")
    maker = await ctx.__aenter__()

    now = datetime(2026, 9, 23, tzinfo=UTC)
    uid, pid = uuid.uuid4(), uuid.uuid4()
    async with maker() as db:
        await db.execute(
            insert(User).values(
                id=uid, email=f"{uid}@x.invalid", hashed_pw="x", is_active=True, created_at=now
            )
        )
        await db.execute(
            insert(Project).values(id=pid, user_id=uid, name="P", created_at=now, updated_at=now)
        )
        await db.commit()
        run = await run_lifecycle.create_run(
            db, owner_id=uid, project_id=pid, question="q", depth="fast"
        )
        await db.commit()
        run_id = str(run.id)

    for name in ("init_redis_pool", "close_redis_pool", "release_session_lock"):
        monkeypatch.setattr(redis_mod, name, _noop)
    monkeypatch.setattr(redis_mod, "acquire_session_lock", _granted)
    monkeypatch.setattr(db_base, "AsyncSessionLocal", maker)
    monkeypatch.setattr(db_base, "engine", _Engine())
    monkeypatch.setattr(pg_aio.AsyncPostgresSaver, "from_conn_string", _saver_cm)
    monkeypatch.setattr(adapters, "RedisCache", lambda: None)
    monkeypatch.setattr(adapters, "agent_log_sink", lambda *_a, **_k: _noop)
    monkeypatch.setattr(runner_mod, "run", fake_graph)
    return ctx, maker, run_id


async def test_execute_run_enters_its_recorder_and_reaches_the_graph(tmp_path, monkeypatch):
    """The regression, stated as its symptom: the graph must actually be reached."""
    from app import run_execution

    reached = []

    async def graph(**_kwargs):
        reached.append(True)
        system_prompt("planner.main")
        return RunOutcome(status="awaiting_plan", plan_tasks=[], plan_outline=[])

    ctx, maker, run_id = await _stage(tmp_path, monkeypatch, graph)
    try:
        await run_execution.execute_run(run_id)
    finally:
        await ctx.__aexit__(None, None, None)

    assert reached, "execute_run never reached the graph — the recorder failed to enter"


async def test_execute_run_persists_what_the_graph_composed(tmp_path, monkeypatch):
    """End to end through the real driver: composed in a node, persisted on the row.

    Ends at the plan gate on purpose — the invocation whose early return in
    `persist_outcome` once dropped the planner's prompt. Two fixed defects, one path.
    """
    from app import run_execution

    async def graph(**_kwargs):
        system_prompt("planner.main")
        return RunOutcome(status="awaiting_plan", plan_tasks=[], plan_outline=[])

    ctx, maker, run_id = await _stage(tmp_path, monkeypatch, graph)
    try:
        await run_execution.execute_run(run_id)
        async with maker() as db:
            run = await db.get(ResearchRun, uuid.UUID(run_id))
            provenance = run.effective_prompt_provenance
            status = run.status
    finally:
        await ctx.__aexit__(None, None, None)

    assert status == "AWAITING_PLAN"
    assert provenance is not None, "the server driver recorded nothing"
    assert set(provenance) == {"planner.main"}
    assert provenance["planner.main"]["effective_prompt"] == PURPOSE_CONSTANTS["planner.main"]


async def test_the_recorder_is_uninstalled_once_the_driver_returns(tmp_path, monkeypatch):
    """A Celery worker runs many tasks on one process; nothing may leak into the next."""
    from app import run_execution
    from research_engine.prompt_composition import _provenance

    async def graph(**_kwargs):
        system_prompt("planner.main")
        return RunOutcome(status="awaiting_plan", plan_tasks=[], plan_outline=[])

    ctx, _maker, run_id = await _stage(tmp_path, monkeypatch, graph)
    try:
        await run_execution.execute_run(run_id)
    finally:
        await ctx.__aexit__(None, None, None)

    assert _provenance.get() is None


def test_no_synchronous_prompt_context_is_entered_with_async_with():
    """The defect class, for every call site rather than the one that shipped.

    `recording_provenance` and `chat_prompt_context` are plain `@contextmanager`s. Named in
    an `async with` they raise `TypeError` on entry — and only at runtime, so the failure
    surfaces wherever that line first executes, which for `execute_run` was nowhere but
    the real worker. The behavioural tests above cover `execute_run`; this covers the rest.
    """
    import ast
    from pathlib import Path

    synchronous = {"recording_provenance", "chat_prompt_context"}
    backend = Path(__file__).resolve().parents[2]
    offenders = []
    for path in sorted([*(backend / "app").rglob("*.py"), *(backend / "desktop").glob("*.py")]):
        for node in ast.walk(ast.parse(path.read_text("utf-8"))):
            if not isinstance(node, ast.AsyncWith):
                continue
            for item in node.items:
                func = getattr(item.context_expr, "func", None)
                name = getattr(func, "id", None) or getattr(func, "attr", None)
                if name in synchronous:
                    offenders.append(f"{path.relative_to(backend)}:{node.lineno}")
    assert not offenders, f"synchronous prompt context entered with `async with`: {offenders}"
