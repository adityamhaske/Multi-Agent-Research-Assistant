"""Cancellation is authoritative: a stopped run cannot be un-stopped by its own outcome.

Issue #54. Cancellation was advisory on every path — it recorded an intent and nothing
enforced it — so the run continued and the outcome writer moved the row back out of the
terminal state when it finished:

    t0  user clicks Stop        → the row goes terminal, the UI says stopped
    t1  the pipeline finishes   → the outcome writer overwrites it
    t2  user reloads            → a live run awaiting their approval

These tests **force that order** rather than avoid it. `test_desktop_contract_gaps.py`
already has a `held_run` fixture that holds the pipeline open so a cancel test stops racing
the pipeline; that made the *test* deterministic and left the *product* race intact, which
is what this file exists to close. Here the outcome is delivered deliberately, after the
cancel, on every writer the product has.

There are three writers and therefore three homes of one rule (AGENTS.md, "two hosts, one
contract" — here it is two hosts *and* two generations):

    V2 runs        `app/v2_execution.py::persist_outcome`
    V1 server      `app/workers/pipeline_runner.py::_persist_outcome`
    V1 desktop     `desktop/sidecar.py::_apply_outcome`

Every test below was verified to fail with its guard removed; the negative controls are
recorded in the docstrings so a future reader can re-run them rather than trust this note.

What is *not* claimed: that the run stops. It does not. Cancellation stays
cooperative-by-omission on both hosts — nothing interrupts the Celery task or the sidecar's
`asyncio.Task` — and `docs/user-guide/25` says so. What is enforced is that the user's
decision outlives the run that ignored it.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

import httpx
import pytest
from sqlalchemy import insert, select

from app import v2_execution, v2_runtime
from app.models.project import Project
from app.models.research import ResearchRun
from app.models.session import Session as SessionRow
from app.models.session import SessionStatus
from app.models.user import User
from desktop.sidecar import create_sidecar_app
from research_engine.runner import RunOutcome
from tests.sqlite_support import open_db

TOKEN = "test-cancel-token"

#: The outcome a pipeline that ignored the stop eventually delivers. Deliberately the
#: *good* case — a run that succeeded — because that is the one that overwrites a stopped
#: session with something a reviewer can approve. Money on it is non-zero so the spend
#: assertions measure something.
COMPLETING_OUTCOME = RunOutcome(
    status="awaiting_approval",
    draft_report="# Findings\n\nThe retriever improved recall [1].",
    sources=[{"index": 1, "title": "A paper", "url": "https://example.invalid/a"}],
    cost_usd=0.5,
    tokens_input=1200,
    tokens_output=340,
)


# ── V2: the primary release path ───────────────────────────────────────────────────


@pytest.fixture
async def v2_run(tmp_path):
    """A real ResearchRun on a real database, mid-flight.

    A real DB rather than a fake session because the guard's absence used to be caught by
    `ck_run_cancelled` — the CHECK constraint that ties CANCELLED to `cancelled_at` — and a
    fake would not have that constraint. Reproducing the original failure needs the schema
    that produced it.
    """
    async with open_db(tmp_path / "v2.sqlite") as maker, maker() as db:
        now = datetime(2026, 8, 24, tzinfo=UTC)
        uid, pid = uuid.uuid4(), uuid.uuid4()
        await db.execute(
            insert(User).values(
                id=uid, email=f"{uid}@x.invalid", hashed_pw="x", is_active=True, created_at=now
            )
        )
        await db.execute(
            insert(Project).values(id=pid, user_id=uid, name="P", created_at=now, updated_at=now)
        )
        await db.commit()
        run = await v2_runtime.create_run(
            db, owner_id=uid, project_id=pid, question="q", depth="fast"
        )
        await v2_runtime.set_status(db, run, "RUNNING")
        await db.commit()
        yield db, run, uid


async def _reload(db, run_id) -> ResearchRun:
    """Re-read the row, never a cached attribute. What a user's reload at t2 would see."""
    return (await db.execute(select(ResearchRun).where(ResearchRun.id == run_id))).scalars().one()


async def test_v2_a_cancelled_run_survives_a_completing_outcome(v2_run):
    """t0 → t1 → t2 on the V2 adapter.

    Negative control: delete the `run.status == "CANCELLED"` guard at the top of
    `persist_outcome` and this fails — not with AWAITING_REVIEW, but with an IntegrityError
    on `ck_run_cancelled`, because the schema refuses the status change the code attempted.
    That accident is what kept the data correct before this fix; it is not a decision, and
    it cost the spend (see the next test).
    """
    db, run, _ = v2_run
    await v2_runtime.request_cancel(db, run, by=run.owner_id)
    await db.commit()
    assert (await _reload(db, run.id)).status == "CANCELLED"

    result = await v2_execution.persist_outcome(
        db, await _reload(db, run.id), COMPLETING_OUTCOME, state={"evidence": []}
    )
    await db.commit()

    assert result.status == "CANCELLED", "the adapter reported a status the user did not choose"
    after = await _reload(db, run.id)
    assert after.status == "CANCELLED", f"a stopped run came back as {after.status}"
    assert after.cancelled_at is not None


async def test_v2_a_cancelled_run_keeps_the_spend_it_incurred(v2_run):
    """Tokens burned between the stop and the pipeline noticing are real money.

    This is the half the CHECK constraint could never have saved: before the guard the whole
    transaction rolled back, so a run cancelled after $0.50 recorded $0.00 and the spend
    vanished from usage totals.
    """
    db, run, _ = v2_run
    await v2_runtime.request_cancel(db, run, by=run.owner_id)
    await db.commit()

    await v2_execution.persist_outcome(
        db, await _reload(db, run.id), COMPLETING_OUTCOME, state={"evidence": []}
    )
    await db.commit()

    after = await _reload(db, run.id)
    assert float(after.cost_usd) == pytest.approx(0.5)
    assert after.tokens_input == 1200
    assert after.tokens_output == 340


async def test_v2_a_cancelled_run_writes_no_evidence_and_no_revision(v2_run):
    """The run's conclusion is withheld — only the money is kept.

    A revision is what a reviewer approves, so writing one for a run the user abandoned is
    the whole defect restated one table down.
    """
    db, run, _ = v2_run
    await v2_runtime.request_cancel(db, run, by=run.owner_id)
    await db.commit()

    result = await v2_execution.persist_outcome(
        db,
        await _reload(db, run.id),
        COMPLETING_OUTCOME,
        state={
            "evidence": [{"source_url": "https://example.invalid/a", "snippet": "recall improved"}]
        },
    )
    await db.commit()

    assert result.revision_version is None
    assert result.evidence_count == 0
    # The tri-state stays honest: nothing was read, and that is not the same as "no
    # evidence existed" — the checkpoint was never consulted.
    assert result.evidence_outcome == "NOT_READ"


def test_v2_a_cancelled_result_does_not_announce_completed():
    """`lifecycle_event` falls through to COMPLETED for anything it does not name.

    So the guard returning a new status was only half a fix: without a branch here the run
    the user stopped would publish COMPLETED to the workspace. FAILED is the right event —
    it is already on both hosts' `_TERMINAL_EVENTS`, so the stream closes, and `CANCELLED`
    is on neither.
    """
    event = v2_execution.lifecycle_event(
        v2_execution.PersistResult(status="CANCELLED", evidence_outcome="NOT_READ")
    )
    assert event["type"] == "FAILED"
    assert "stopped by user" in event["data"]["reason"].lower()


async def test_v2_cancellation_survives_a_worker_restart(tmp_path):
    """Durability, which is why this is a column and not the Redis key it replaced.

    The old server flag was `session:{id}:cancelled` with a 1h TTL and no reader anywhere.
    Here the process that cancels and the process that later writes the outcome share
    nothing but the database — which is the actual production topology, where the API
    container cancels and a Celery worker (restarted or not) delivers the outcome.
    """
    db_path = tmp_path / "restart.sqlite"
    async with open_db(db_path) as maker, maker() as db:
        now = datetime(2026, 8, 24, tzinfo=UTC)
        uid, pid = uuid.uuid4(), uuid.uuid4()
        await db.execute(
            insert(User).values(
                id=uid, email=f"{uid}@x.invalid", hashed_pw="x", is_active=True, created_at=now
            )
        )
        await db.execute(
            insert(Project).values(id=pid, user_id=uid, name="P", created_at=now, updated_at=now)
        )
        await db.commit()
        run = await v2_runtime.create_run(
            db, owner_id=uid, project_id=pid, question="q", depth="fast"
        )
        run_id = run.id
        await v2_runtime.set_status(db, run, "RUNNING")
        await v2_runtime.request_cancel(db, run, by=uid)
        await db.commit()

    # A different engine, a different session, nothing carried over in memory.
    async with open_db(db_path) as maker, maker() as db:
        reloaded = await _reload(db, run_id)
        assert reloaded.status == "CANCELLED"
        result = await v2_execution.persist_outcome(
            db, reloaded, COMPLETING_OUTCOME, state={"evidence": []}
        )
        await db.commit()
        assert result.status == "CANCELLED"
        assert (await _reload(db, run_id)).status == "CANCELLED"


async def test_v2_a_later_failure_cannot_overwrite_a_cancelled_run(v2_run):
    """The error path is a *separate* writer, and it had the same defect.

    `persist_outcome`'s guard covers outcomes the adapter delivers. It does not cover a
    crash: `execute_run`'s corpus guard and `tasks._mark_v2_failed` both write FAILED
    directly through `record_failure`, and on a cancelled run that violates
    `ck_run_cancelled` and raises `IntegrityError` — from `_mark_v2_failed`, whose own
    docstring promises it never raises, so the original error is lost too.

    Found live rather than by reading: cancelling a run mid-flight and letting its worker
    hit any error produced exactly this, and the run's own error_message ended up being the
    constraint violation.

    Negative control: drop the `run.status == "CANCELLED"` branch from
    `v2_runtime.record_failure` and this raises IntegrityError instead of asserting.
    """
    db, run, _ = v2_run
    await v2_runtime.request_cancel(db, run, by=run.owner_id)
    await db.commit()

    await v2_runtime.record_failure(db, await _reload(db, run.id), "worker crashed")
    await db.commit()

    after = await _reload(db, run.id)
    assert after.status == "CANCELLED", f"a stopped run was moved to {after.status}"
    assert after.cancelled_at is not None
    # The message is still worth keeping — what went wrong is knowable even when the run's
    # fate was already decided by the user.
    assert after.error_message == "worker crashed"


async def test_v2_an_uncancelled_run_still_records_failure(v2_run):
    """The control: ordinary failures must still land FAILED."""
    db, run, _ = v2_run
    await v2_runtime.set_status(db, run, "RUNNING")
    await v2_runtime.record_failure(db, run, "provider quota exhausted")
    await db.commit()

    after = await _reload(db, run.id)
    assert after.status == "FAILED"
    assert after.error_message == "provider quota exhausted"


async def test_v2_set_status_refuses_to_move_a_cancelled_run(v2_run):
    """A cancelled run is terminal, and no bare status write may leave it.

    The constraint already enforced this from below, but as an `IntegrityError` three layers
    down inside whatever background task attempted it. Refusing here names the caller.

    Negative control: drop the `run.status == "CANCELLED"` check from `set_status` and this
    raises IntegrityError at the flush instead of LifecycleError.
    """
    db, run, _ = v2_run
    await v2_runtime.request_cancel(db, run, by=run.owner_id)
    await db.commit()

    with pytest.raises(v2_runtime.LifecycleError, match="cancelled"):
        await v2_runtime.set_status(db, await _reload(db, run.id), "RUNNING")


# ── V1 server: the Celery worker's writer ──────────────────────────────────────────


class _CountingDb:
    """Just enough AsyncSession for `_persist_outcome`, which only ever commits.

    Same shape as `test_plan_gate.py::_FakeDb`. Faking the session is safe *here* — unlike
    the V2 tests above — because the V1 guard is a plain attribute read with no constraint
    behind it, so there is no schema behaviour to reproduce.
    """

    def __init__(self) -> None:
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1


def _cancelled_session() -> SessionRow:
    """A session the user stopped: exactly what `cancel_session` leaves behind."""
    row = SessionRow(prompt="q", research_depth="fast")
    row.status = SessionStatus.FAILED
    row.error_message = "Research stopped by user."
    row.cancelled_at = datetime.now(UTC)
    return row


async def test_server_v1_leaves_a_cancelled_session_terminal_and_silent():
    """t0 → t1 on the V1 server writer.

    Negative control: remove the `session.is_cancelled` block from `_persist_outcome` and
    the status becomes AWAITING_APPROVAL and a HITL_READY event is published — the run
    reappears at the review gate, which is the user-visible bug in the issue.
    """
    from app.workers.pipeline_runner import _persist_outcome

    published: list[dict] = []

    async def sink(_session_id: str, event: dict) -> None:
        published.append(event)

    row = _cancelled_session()
    db = _CountingDb()
    await _persist_outcome(db, row, "s-1", COMPLETING_OUTCOME, sink)

    assert row.status == SessionStatus.FAILED, f"a stopped run came back as {row.status}"
    assert row.error_message == "Research stopped by user."
    assert published == [], f"a stopped run announced itself: {published}"
    # The draft is what a reviewer would be offered; it must never have been written.
    assert row.draft_report is None
    assert db.commits == 1, "the spend still has to be committed"


async def test_server_v1_cancelled_session_keeps_the_spend():
    """Same rule as V2: withhold the conclusion, keep the money."""
    from app.workers.pipeline_runner import _persist_outcome

    async def sink(_session_id: str, _event: dict) -> None:  # pragma: no cover - never called
        raise AssertionError("a cancelled session must publish nothing")

    row = _cancelled_session()
    await _persist_outcome(_CountingDb(), row, "s-2", COMPLETING_OUTCOME, sink)

    assert row.total_cost_usd == pytest.approx(0.5)
    assert row.total_tokens_input == 1200
    assert row.total_tokens_output == 340


async def test_server_v1_an_uncancelled_session_still_reaches_the_gate():
    """The guard must not swallow ordinary runs — the control that makes the others mean something.

    Without this, deleting the whole `_persist_outcome` body would pass every test above.
    """
    from app.workers.pipeline_runner import _persist_outcome

    published: list[dict] = []

    async def sink(_session_id: str, event: dict) -> None:
        published.append(event)

    row = SessionRow(prompt="q", research_depth="fast")
    assert row.is_cancelled is False
    await _persist_outcome(_CountingDb(), row, "s-3", COMPLETING_OUTCOME, sink)

    assert row.status == SessionStatus.AWAITING_APPROVAL
    assert row.draft_report == COMPLETING_OUTCOME.draft_report
    assert [e["type"] for e in published] == ["HITL_READY"]


# ── V1 desktop: the sidecar's writer, over real HTTP ───────────────────────────────


@pytest.fixture
async def gated_sidecar(tmp_path, monkeypatch):
    """A sidecar whose pipeline is held at a gate the test opens.

    `held_run` in `test_desktop_contract_gaps.py` makes the pipeline never finish, which is
    enough to test the cancel *route*. It cannot test the race, because the race needs the
    run to finish **after** the cancel. This replaces the module-global `run` with a
    coroutine that waits on an Event the test sets, then returns a completing outcome — so
    t0 and t1 happen in a fixed order, every time, through the real background task and the
    real `_apply_outcome`.
    """
    import desktop.sidecar as sidecar_module

    release = asyncio.Event()

    async def _finishes_when_released(**_kwargs):
        await release.wait()
        return COMPLETING_OUTCOME

    monkeypatch.setattr(sidecar_module, "run", _finishes_when_released)

    app = create_sidecar_app(data_dir=tmp_path, token=TOKEN, fake=True)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:9") as client:
            yield client, release


def _auth() -> dict:
    return {"Authorization": f"Bearer {TOKEN}"}


async def test_desktop_v1_a_cancelled_session_survives_the_late_outcome(gated_sidecar):
    """The full t0 → t1 → t2 sequence on the desktop host, through the real routes.

    Negative control: remove the `session.is_cancelled` block from `_apply_outcome` and t2
    reads AWAITING_APPROVAL with a draft report attached — the desktop half of the issue.
    """
    client, release = gated_sidecar

    start = await client.post(
        "/api/v1/research",
        headers=_auth(),
        json={"query": "What is retrieval-augmented generation?", "depth": "fast"},
    )
    assert start.status_code == 202
    session_id = start.json()["session_id"]

    # t0 — the user stops it while the pipeline is held.
    cancel = await client.post(f"/api/v1/research/{session_id}/cancel", headers=_auth())
    assert cancel.status_code == 200
    assert cancel.json()["status"] == SessionStatus.FAILED.value

    # t1 — the pipeline, which never saw the stop, delivers a completing outcome.
    release.set()
    deadline = asyncio.get_event_loop().time() + 30
    while asyncio.get_event_loop().time() < deadline:
        detail = (await client.get(f"/api/v1/research/{session_id}", headers=_auth())).json()
        if detail["total_cost_usd"]:
            break  # the writer ran: the spend it committed is the observable signal
        await asyncio.sleep(0.05)

    # t2 — what the user's reload sees.
    detail = (await client.get(f"/api/v1/research/{session_id}", headers=_auth())).json()
    assert detail["status"] == SessionStatus.FAILED.value, (
        f"a stopped run came back as {detail['status']}"
    )
    assert detail["error_message"] == "Research stopped by user."
    assert float(detail["total_cost_usd"]) == pytest.approx(0.5), "the spend was dropped"


async def test_desktop_v1_an_uncancelled_session_still_reaches_the_gate(gated_sidecar):
    """The control: the same fixture, without the cancel, must still finish normally."""
    client, release = gated_sidecar

    start = await client.post(
        "/api/v1/research",
        headers=_auth(),
        json={"query": "What is retrieval-augmented generation?", "depth": "fast"},
    )
    session_id = start.json()["session_id"]

    release.set()
    deadline = asyncio.get_event_loop().time() + 30
    while asyncio.get_event_loop().time() < deadline:
        detail = (await client.get(f"/api/v1/research/{session_id}", headers=_auth())).json()
        if detail["status"] == SessionStatus.AWAITING_APPROVAL.value:
            break
        await asyncio.sleep(0.05)

    assert detail["status"] == SessionStatus.AWAITING_APPROVAL.value
    assert detail["draft_report"] == COMPLETING_OUTCOME.draft_report


# ── The flag that never did anything ───────────────────────────────────────────────


def test_the_write_only_redis_cancellation_key_is_gone():
    """`session:{id}:cancelled` was set by the server and read by nothing, with a 1h TTL.

    Asserted against the source because the defect was an *absence* of a reader, and no
    behavioural test can observe a key nobody consults. Issue #54 required it be given a
    reader or removed; `sessions.cancelled_at` is the reader's replacement, so the key is
    removed and this keeps it from drifting back in.

    Read through the AST rather than as text, so only a **string literal** counts. The first
    draft of this test grepped the file and failed on its own explanatory comments — which
    is the "a guard cannot tell a use from a mention" trap `AGENTS.md` records against the
    frontend's CI greps, reproduced here. A key name in prose is documentation; a key name
    in a literal is the defect.
    """
    import ast
    from pathlib import Path

    backend = Path(__file__).resolve().parents[2]
    offenders: list[str] = []
    for package in (backend / "app", backend / "desktop", backend / "research_engine"):
        for source in package.rglob("*.py"):
            tree = ast.parse(source.read_text(), filename=str(source))
            for node in ast.walk(tree):
                # An f-string's fixed halves are `Constant` children of `JoinedStr`, so
                # `f"session:{id}:cancelled"` is caught by walking every Constant.
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    if ":cancelled" in node.value:
                        offenders.append(f"{source.relative_to(backend)}:{node.lineno}")

    assert not offenders, (
        "the TTL'd cancellation key that nothing reads is back in a string literal: "
        + ", ".join(offenders)
    )
