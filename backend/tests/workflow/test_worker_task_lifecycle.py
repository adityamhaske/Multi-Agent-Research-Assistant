"""A worker process runs real-mode research task after task, and recovers from a provider failure.

The defect this guards: a Celery child ran each task on a loop of its own while provider SDKs
kept their HTTP client process-wide, so the plan-approval task — routinely handed to the child
that ran the start — met a keep-alive connection from a closed loop and died on its first
model call. The session close that followed then replaced that error as the recorded reason.

So these tests drive the **production path**, not a model of it: the real Celery task bodies
(`tasks.run_research_pipeline` → plan approval through the real route handler →
`tasks.resume_research_plan_gate`), `execute_run` with its own sessions, Redis lock, Postgres
checkpointer and event sink, and `LLM_MODE=real` — the real factory building a real
`ChatOpenAI` over real HTTP/1.1 keep-alive to `tests.fake_provider`. Only two things are
substituted, and neither is under test: the provider's *answers* (scripted, so the run is
deterministic) and retrieval (fixture pages, so nothing leaves the machine).

Concurrency, honestly scoped: a prefork child runs one task at a time (`--concurrency` is
processes, `worker_prefetch_multiplier=1`), and `event_loop.run` refuses a second thread. What
*is* concurrent inside one process is a run's own fan-out — research tasks sharing one cached
client and one session — and, on the desktop, several runs on one loop. Both are driven below.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
import uuid

import pytest
from langgraph.checkpoint.memory import MemorySaver
from sqlalchemy import func, select, text

from app.workers import event_loop
from tests.conftest import _TRUNCATE, requires_db, requires_redis
from tests.fake_provider import FAILURE_MESSAGE, ROLES, FakeProvider, page_for

pytestmark = [requires_db, requires_redis]


# ── Harness ─────────────────────────────────────────────────────────────────────────


class _Fixture:
    def __init__(self, fn):
        self.ainvoke = fn


async def _read_webpage(args):
    task = int(str(args["url"]).rstrip("/").rsplit("/", 1)[-1])
    return page_for(task)


async def _web_search(args):
    return [{"title": "Fixture page 1", "url": page_for(1)["url"], "snippet": "Fixture."}]


@pytest.fixture
def provider():
    p = FakeProvider()
    yield p
    p.close()


@pytest.fixture
def real_mode(provider, migrated_database, monkeypatch):  # noqa: ARG001 - schema must exist
    """Configure the server the way a Custom/OmniRoute deployment is: real mode, every role
    on a `custom:` route, the custom endpoint pointing at the fake provider."""
    from app.config import settings
    from research_engine import graph, llm_factory

    for role in ROLES:
        monkeypatch.setattr(settings, f"model_{role}", f"custom:{role}")
    monkeypatch.setattr(settings, "llm_mode", "real")
    monkeypatch.setattr(settings, "custom_base_url", provider.base_url)
    monkeypatch.setattr(settings, "custom_api_key", "test-key")
    monkeypatch.setattr(settings, "max_parallel_tasks", 2)
    # Only a container rewrites localhost; the provider runs on this host.
    monkeypatch.setattr(llm_factory, "map_local_host", lambda url: url)
    monkeypatch.setattr(
        graph,
        "_TOOLS_BY_NAME",
        {"read_webpage": _Fixture(_read_webpage), "web_search": _Fixture(_web_search)},
    )
    event_loop.run(_reset_database())
    yield
    event_loop.shutdown()


class _Captured:
    """The dispatcher the routes are handed: records what they would have queued."""

    def __init__(self):
        self.calls: list[tuple] = []

    async def start(self, run_id, user_id):
        self.calls.append(("start", run_id, user_id))

    async def resume_plan(self, run_id, user_id, plan):
        self.calls.append(("resume_plan", run_id, user_id, plan))

    async def rework(self, run_id, user_id, feedback):
        self.calls.append(("rework", run_id, user_id, feedback))


async def _reset_database():
    from app.db.base import AsyncSessionLocal, engine

    async with AsyncSessionLocal() as db:
        await db.execute(text(_TRUNCATE))
        await db.execute(text("TRUNCATE TABLE research_runs RESTART IDENTITY CASCADE"))
        await db.commit()
    await engine.dispose()


async def _seed_user() -> tuple[str, str]:
    from app.db.base import AsyncSessionLocal, engine
    from app.models.project import Project
    from app.models.user import User

    now = dt.datetime.now(dt.UTC)
    async with AsyncSessionLocal() as db:
        user = User(id=uuid.uuid4(), email=f"{uuid.uuid4().hex}@x.invalid", hashed_pw="x")
        db.add(user)
        await db.flush()
        project = Project(
            id=uuid.uuid4(), user_id=user.id, name="lifecycle", created_at=now, updated_at=now
        )
        db.add(project)
        await db.commit()
        ids = (str(user.id), str(project.id))
    await engine.dispose()
    return ids


async def _create_run(user_id: str, project_id: str, question: str) -> str:
    from app.api.v1.runs import create_run
    from app.db.base import AsyncSessionLocal, engine
    from app.models.user import User
    from app.schemas.runs import CreateRunRequest

    async with AsyncSessionLocal() as db:
        user = await db.get(User, uuid.UUID(user_id))
        out = await create_run(
            CreateRunRequest(
                project_id=uuid.UUID(project_id),
                question=question,
                depth="fast",
                skip_plan_gate=False,
            ),
            db,
            user,
            _Captured(),
        )
        await db.commit()
    await engine.dispose()
    return out["run_id"]


async def _approve_plan(run_id: str, user_id: str) -> dict:
    from app.api.v1.runs import submit_plan_review
    from app.db.base import AsyncSessionLocal, engine
    from app.models.user import User
    from app.schemas.runs import PlanReviewRequest

    captured = _Captured()
    async with AsyncSessionLocal() as db:
        user = await db.get(User, uuid.UUID(user_id))
        await submit_plan_review(uuid.UUID(run_id), PlanReviewRequest(), db, user, captured)
        await db.commit()
    await engine.dispose()
    return next(call[3] for call in captured.calls if call[0] == "resume_plan")


async def _run_row(run_id: str) -> dict:
    from app.db.base import AsyncSessionLocal, engine
    from app.models.research import Evidence, ResearchRun

    async with AsyncSessionLocal() as db:
        run = await db.get(ResearchRun, uuid.UUID(run_id))
        evidence = (
            await db.execute(
                select(func.count()).select_from(Evidence).where(Evidence.run_id == run.id)
            )
        ).scalar_one()
        row = {
            "status": run.status,
            "error": run.error_message,
            "evidence_outcome": run.evidence_outcome,
            "evidence": evidence,
            "demo": run.demo,
        }
    await engine.dispose()
    return row


async def _stranded_transactions() -> int:
    """Server-side sessions left open mid-transaction — what a close that never completed
    leaves behind, and what would make the next task's work wait on a lock."""
    from app.db.base import AsyncSessionLocal, engine

    async with AsyncSessionLocal() as db:
        count = (
            await db.execute(
                text(
                    "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database() "
                    "AND pid <> pg_backend_pid() AND state LIKE 'idle in transaction%'"
                )
            )
        ).scalar_one()
    await engine.dispose()
    return count


def _gated_run(user_id: str, project_id: str, question: str) -> tuple[str, dict]:
    """One run the way the product drives it: two Celery tasks with a human gate between."""
    from app.workers import tasks

    run_id = event_loop.run(_create_run(user_id, project_id, question))
    tasks.run_research_pipeline(run_id, user_id)
    assert event_loop.run(_run_row(run_id))["status"] == "AWAITING_PLAN"
    plan = event_loop.run(_approve_plan(run_id, user_id))
    tasks.resume_research_plan_gate(run_id, user_id, plan)
    return run_id, event_loop.run(_run_row(run_id))


def _retries(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records if "Retrying request" in r.getMessage()]


# ── 1, 4, 5. Sequential runs on one worker process ──────────────────────────────────


@pytest.mark.usefixtures("real_mode")
def test_one_worker_process_runs_five_real_mode_runs_in_a_row(provider, caplog):
    """Ten task boundaries in one process — the boundary the original bug lived on, each
    plan-approval task reusing the provider connection the task before it left in the pool."""
    caplog.set_level(logging.INFO)
    user_id, project_id = event_loop.run(_seed_user())

    rows = [_gated_run(user_id, project_id, f"Question {n}")[1] for n in range(1, 6)]

    for n, row in enumerate(rows, 1):
        assert row["status"] == "AWAITING_REVIEW", f"run {n}: {row}"
        assert row["error"] is None, f"run {n} recorded {row['error']!r}"
        assert row["evidence_outcome"] == "READ" and row["evidence"] > 0, f"run {n}: {row}"
        assert row["demo"] is False, f"run {n} was recorded as a scripted demo"
    assert _retries(caplog) == [], "a call needed a retry to survive a task boundary"
    assert set(provider.requests) >= {"planner", "executor", "critic", "synthesizer"}
    # Keep-alive actually carried requests across task boundaries: far fewer connections
    # than requests. A per-task loop could not reuse one, and failed when it tried.
    assert provider.connections < len(provider.requests) / 2, (
        f"{provider.connections} connections for {len(provider.requests)} requests"
    )
    assert event_loop.run(_stranded_transactions()) == 0


# ── 3, 4, 5. A provider failure, then the next run ──────────────────────────────────


@pytest.mark.usefixtures("real_mode")
def test_a_provider_failure_fails_its_run_cleanly_and_the_next_run_succeeds(provider, caplog):
    """The failure lands where the original one did — the executor's first model call in the
    plan-approval task — in one research task while its sibling is still working on the shared
    session. Whether the session close then meets the sibling *mid-write* is timing, so the
    collision itself is pinned deterministically in `test_node_failure_is_not_masked.py`;
    this test holds the rest of the contract: the provider's own message is what gets
    recorded, nothing is left open, and the same worker runs the next run."""
    from app.workers import tasks

    caplog.set_level(logging.INFO)
    user_id, project_id = event_loop.run(_seed_user())

    run_id = event_loop.run(_create_run(user_id, project_id, "A run whose provider fails"))
    tasks.run_research_pipeline(run_id, user_id)
    plan = event_loop.run(_approve_plan(run_id, user_id))
    provider.fail_roles, provider.fail_tasks, provider.latency = {"executor"}, {1}, 0.05
    tasks.resume_research_plan_gate(run_id, user_id, plan)
    provider.fail_roles, provider.fail_tasks, provider.latency = set(), set(), 0.0

    failed = event_loop.run(_run_row(run_id))
    assert failed["status"] == "FAILED"
    assert FAILURE_MESSAGE in (failed["error"] or ""), (
        f"recorded {failed['error']!r} — the provider's own message must be the reason"
    )
    assert "IllegalStateChangeError" not in failed["error"]
    assert "can't be called here" not in failed["error"]
    assert event_loop.run(_stranded_transactions()) == 0
    leftover = [t for t in asyncio.all_tasks(event_loop._process_runner().get_loop())]
    assert leftover == [], f"tasks left on the worker loop after the failure: {leftover}"

    _, recovered = _gated_run(user_id, project_id, "The next run on the same worker")
    assert recovered["status"] == "AWAITING_REVIEW", recovered
    assert recovered["error"] is None and recovered["evidence"] > 0
    assert _retries(caplog) == []
    assert event_loop.run(_stranded_transactions()) == 0


# ── 2. Concurrency inside one process ───────────────────────────────────────────────


@pytest.mark.usefixtures("real_mode")
def test_concurrent_runs_on_one_worker_loop_stay_separate_across_task_boundaries(provider, caplog):
    """Four runs at once on the worker's loop — the desktop's model, and the worst case for a
    process-wide client — started in one task and resumed in the next, as a gate splits them.
    Each fans out its own research tasks over the same cached client."""
    from research_engine import runner
    from research_engine.runconfig import RunConfig

    caplog.set_level(logging.INFO)
    saver = MemorySaver()
    config = RunConfig(
        llm_mode="real",
        models={role: f"custom:{role}" for role in ROLES},
        provider_keys={"custom": "test-key", "custom_base_url": provider.base_url},
        enforce_ssrf_guards=False,
        skip_plan_gate=False,
        max_parallel_tasks=2,
    )
    events: dict[str, list[dict]] = {f"concurrent-{n}": [] for n in range(4)}

    def sink_for(sid):
        async def sink(event_sid, event):
            events[sid].append({**event, "_sid": event_sid})

        return sink

    async def start_all():
        return await asyncio.gather(
            *(
                runner.run(
                    checkpointer=saver,
                    session_id=sid,
                    user_id="user",
                    query=f"Concurrent question {sid}",
                    depth="fast",
                    run_config=config,
                    event_sink=sink_for(sid),
                )
                for sid in events
            )
        )

    async def resume_all(plans):
        return await asyncio.gather(
            *(
                runner.resume(
                    checkpointer=saver,
                    session_id=sid,
                    plan={"tasks": plan},
                    run_config=config,
                    event_sink=sink_for(sid),
                )
                for sid, plan in zip(events, plans, strict=True)
            )
        )

    started = event_loop.run(start_all())
    assert [o.status for o in started] == ["awaiting_plan"] * 4
    finished = event_loop.run(resume_all([o.plan_tasks for o in started]))

    for sid, outcome in zip(events, finished, strict=True):
        assert outcome.status == "awaiting_approval", (sid, outcome.status, outcome.error)
        assert outcome.draft_report, sid
        # Nothing from another run reached this run's sink.
        assert {e["_sid"] for e in events[sid]} == {sid}
    assert _retries(caplog) == []
