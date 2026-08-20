"""
The **server** bundle route, at the HTTP layer, against real Postgres (issue #49).

`app/api/v1/research.py::export_bundle_json` had no integration test of its own. Its
existence was asserted from the OpenAPI schema and its behaviour only through the browser
journey in `frontend/e2e/golden.spec.ts` — slow, needs the whole stack, and localises a
failure poorly. The desktop twin was covered at this layer; the server one was not, and
the two read different things.

That difference is the point. The server route assembles a bundle from four independent
sources, and only one of them is the session row:

    sessions           → report, sources, routing, costs, demo
    agent_logs         → trace
    audit_log          → approval chain (the hashes the verifier checks)
    Postgres checkpoint→ evidence, contradictions

Nothing here injects a hand-built manifest. The evidence is produced by driving
`research_engine.runner` through both gates against a **real `AsyncPostgresSaver`**, on the
same thread id the route later reads, so what is verified is that the route can read what
the engine actually wrote. A synthetic checkpoint would prove the route can read a shape
this test authored — and would quietly get right the one thing worth testing, that evidence
lives in the checkpoint rather than in `RunOutcome`.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient

from app.dependencies import get_current_user
from app.models.agent_log import AgentLog
from app.models.audit_log import AuditLog
from app.models.project import Project
from app.models.session import Session, SessionStatus
from app.models.user import User
from research_engine import bundle, verify_bundle
from research_engine.runconfig import RunConfig

pytestmark = pytest.mark.asyncio

QUERY = "What are the leading approaches to retrieval-augmented generation?"


async def _drive_engine_through_both_gates(session_id: uuid.UUID, user_id: uuid.UUID):
    """Run the real graph to COMPLETED, leaving a real checkpoint under `session_id`.

    Both gates are taken deliberately. `RunConfig.skip_plan_gate` defaults to True for
    unattended callers, but the approval chain this route emits is supposed to carry a
    `plan_approved` entry as well as an `approved` one, and a run that never paused at the
    design gate cannot produce the first.
    """
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

    from app.services.checkpoints import _dsn
    from research_engine.runner import resume, run

    cfg = RunConfig(llm_mode="fake", skip_plan_gate=False)
    async with AsyncPostgresSaver.from_conn_string(_dsn()) as saver:
        await saver.setup()
        first = await run(
            checkpointer=saver,
            session_id=str(session_id),
            user_id=str(user_id),
            query=QUERY,
            run_config=cfg,
        )
        assert first.status == "awaiting_plan", f"expected the design gate, got {first.status}"

        # `plan={}` is the documented "approve as proposed": both keys optional, an absent
        # key meaning unedited. Distinct from `{"tasks": []}`, which is a reviewer who
        # excluded every task — that would research nothing and produce no evidence.
        second = await resume(
            checkpointer=saver, session_id=str(session_id), plan={}, run_config=cfg
        )
        assert second.status == "awaiting_approval", (
            f"expected the report gate, got {second.status}"
        )

        final = await resume(
            checkpointer=saver, session_id=str(session_id), approved=True, run_config=cfg
        )
        assert final.status == "completed", f"expected completion, got {final.status}"
        return final


@pytest.fixture
async def owner(db):
    now = datetime(2026, 8, 19, tzinfo=UTC)
    user = User(id=uuid.uuid4(), email=f"{uuid.uuid4().hex}@x.invalid", hashed_pw="x")
    db.add(user)
    await db.flush()
    project = Project(id=uuid.uuid4(), user_id=user.id, name="RAG", created_at=now, updated_at=now)
    db.add(project)
    await db.commit()
    return user, project


@pytest.fixture
async def completed(db, owner):
    """A COMPLETED session whose four bundle inputs are all really populated."""
    user, project = owner
    sid = uuid.uuid4()
    outcome = await _drive_engine_through_both_gates(sid, user.id)

    report = outcome.final_report
    session = Session(
        id=sid,
        user_id=user.id,
        project_id=project.id,
        prompt=QUERY,
        status=SessionStatus.COMPLETED,
        research_depth="balanced",
        draft_report=outcome.draft_report,
        final_report=report,
        sources=outcome.sources,
        total_cost_usd=0,
        total_tokens_input=0,
        total_tokens_output=0,
        model_routing={},
    )
    db.add(session)
    await db.flush()

    # The approval chain the verifier checks. `draft_hash` on the REPORT approval must be
    # the hash of the report the bundle carries, which is what ties the artifact to the
    # decision rather than to whatever the row happens to say.
    db.add(
        AuditLog(
            session_id=sid,
            user_id=user.id,
            action="plan_approved",
            draft_hash=bundle.content_hash(""),
        )
    )
    db.add(
        AuditLog(
            session_id=sid,
            user_id=user.id,
            action="approved",
            draft_hash=bundle.content_hash(report),
        )
    )
    db.add(AgentLog(session_id=sid, event_type="COMPLETED", agent_name="finalizer", payload={}))
    await db.commit()
    return session, user, report


@pytest.fixture
async def client(db, owner):  # noqa: ARG001 - the app reads through the same database
    from app.main import app

    user, _ = owner
    app.dependency_overrides[get_current_user] = lambda: user
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c
    app.dependency_overrides.clear()


def _url(sid) -> str:
    return f"/api/v1/research/{sid}/export.bundle.json"


async def test_completed_session_downloads_a_bundle_that_verifies(client, completed):
    """The load-bearing one: what the route serves passes the standalone verifier.

    A bundle that downloads but fails verification is worse than no bundle — it teaches
    the reader that FAIL is normal, which defeats the verifier more thoroughly than a
    missing route would.
    """
    session, _, report = completed
    resp = await client.get(_url(session.id))
    assert resp.status_code == 200, resp.text
    assert f'filename="research-{str(session.id)[:8]}.bundle.json"' in (
        resp.headers.get("content-disposition") or ""
    )

    manifest = bundle.BundleManifest.model_validate_json(resp.content)
    result = verify_bundle.verify(manifest)
    assert result.passed, [c for c in result.checks if not c.passed]

    assert manifest.evidence, "evidence was not read back from the Postgres checkpointer"
    for item in manifest.evidence:
        assert item.content_hash == bundle.content_hash(item.snippet)

    actions = [entry.action for entry in manifest.approval_chain]
    assert "approved" in actions and "plan_approved" in actions
    approved = next(e for e in manifest.approval_chain if e.action == "approved")
    assert approved.draft_hash == manifest.report_hash == bundle.content_hash(report)


async def test_export_is_refused_before_the_session_completes(client, completed, db):
    session, _, _ = completed
    session.status = SessionStatus.AWAITING_APPROVAL
    await db.commit()

    resp = await client.get(_url(session.id))
    assert resp.status_code == 400
    assert "COMPLETED" in resp.json()["detail"]


async def test_another_users_session_is_not_found(client, completed, db):
    """404, never 403 — a distinguishable 403 confirms the id exists to a stranger."""
    session, _, _ = completed
    stranger = User(id=uuid.uuid4(), email=f"{uuid.uuid4().hex}@x.invalid", hashed_pw="x")
    db.add(stranger)
    await db.commit()

    from app.main import app

    app.dependency_overrides[get_current_user] = lambda: stranger
    resp = await client.get(_url(session.id))
    assert resp.status_code == 404


async def test_unauthenticated_is_rejected(completed):
    """No dependency override here — the real `get_current_user` must refuse."""
    from app.main import app

    session, _, _ = completed
    app.dependency_overrides.pop(get_current_user, None)
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.get(_url(session.id))
    assert resp.status_code == 401


async def test_a_demo_bundle_declares_itself_without_stamping_the_prose(client, completed, db):
    """`demo` rides in the hash-covered field; the report body stays untouched.

    Stamping the prose would change the report after the human approved it, so
    `report_hash` would stop matching the recorded `draft_hash` and every demo bundle
    would fail `approval_chain` for a reason unrelated to its integrity.
    """
    session, _, report = completed
    session.demo = True
    await db.commit()

    resp = await client.get(_url(session.id))
    assert resp.status_code == 200
    manifest = bundle.BundleManifest.model_validate_json(resp.content)

    assert manifest.demo is True
    assert manifest.report == report
    assert bundle.DEMO_STAMP_MD.strip() not in manifest.report
    assert verify_bundle.verify(manifest).passed, "a demo bundle must still verify"
