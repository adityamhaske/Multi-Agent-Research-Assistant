"""
The V2 HTTP surface: the data contract the next milestone's nine UI surfaces read.

Real requests through a real router, with `get_db` and `get_current_user` overridden — the
authorization *predicate* is what these test, not the JWT machinery, which has its own suite.
That both hosts serve these paths is `test_host_parity`'s job; that the handlers behave is
this file's.

The load-bearing assertions are about what the payload preserves. A UI cannot render "⚠
unverified" if the projection flattened `UNCHECKED` into a boolean, and it cannot show
"retrieved but not cited" if a NULL `citation_index` arrived as `0`.
"""

from __future__ import annotations

import json
import uuid

import httpx
import pytest
from fastapi import FastAPI

from app import v2_runtime
from app.api.v1.v2_runs import router as v2_router
from app.db.base import get_db
from app.dependencies import get_current_user
from app.models.user import User
from tests.migration_support import open_db
from tests.test_v2_native_lifecycle import DRAFT, EVIDENCE, drive_lifecycle


@pytest.fixture
async def api(tmp_path):
    """A router-only app: one DB, one user, no auth stack and no middleware."""
    async with open_db(tmp_path / "v2api.sqlite") as maker, maker() as db:
        from datetime import UTC, datetime

        from sqlalchemy import insert

        from app.models.project import Project

        now = datetime(2026, 8, 18, tzinfo=UTC)
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

        app = FastAPI()
        app.include_router(v2_router, prefix="/api/v1")
        app.dependency_overrides[get_db] = lambda: db
        app.dependency_overrides[get_current_user] = lambda: User(
            id=uid, email=f"{uid}@x.invalid", hashed_pw="x", is_active=True, created_at=now
        )
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
            yield {"client": client, "db": db, "user_id": uid, "project_id": pid}


async def test_a_run_can_be_opened_over_http(api):
    resp = await api["client"].post(
        "/api/v1/v2/runs",
        json={"project_id": str(api["project_id"]), "question": "Does RAG help?"},
    )
    assert resp.status_code == 201
    assert resp.json()["status"] == "PENDING"

    got = await api["client"].get(f"/api/v1/v2/runs/{resp.json()['run_id']}")
    assert got.status_code == 200
    assert got.json()["run"]["question"] == "Does RAG help?"


async def test_another_users_run_is_not_found(api):
    """Ownership is the predicate. 404 rather than 403 — the difference is information."""
    resp = await api["client"].post(
        "/api/v1/v2/runs", json={"project_id": str(uuid.uuid4()), "question": "q"}
    )
    assert resp.status_code == 404
    assert (await api["client"].get(f"/api/v1/v2/runs/{uuid.uuid4()}")).status_code == 404


async def test_the_projection_carries_the_whole_run_graph(api):
    state = await drive_lifecycle(
        api["db"], {"user_id": api["user_id"], "project_id": api["project_id"]}
    )
    payload = (await api["client"].get(f"/api/v1/v2/runs/{state['run'].id}")).json()

    # Every surface the next milestone builds has its data here.
    for key in (
        "run",
        "plans",
        "sources",
        "evidence",
        "revisions",
        "claims",
        "claim_evidence_links",
        "contradictions",
        "reviews",
        "artifact",
    ):
        assert key in payload, f"the projection is missing {key}"

    assert len(payload["revisions"]) == 2
    assert [r["version"] for r in payload["revisions"]] == [1, 2]
    assert len(payload["reviews"]) == 3
    assert [r["sequence"] for r in payload["reviews"]] == [1, 2, 3]
    assert payload["artifact"]["review_gate"] == "REPORT"


async def test_the_projection_does_not_flatten_the_three_valued_vocabularies(api):
    state = await drive_lifecycle(
        api["db"], {"user_id": api["user_id"], "project_id": api["project_id"]}
    )
    payload = (await api["client"].get(f"/api/v1/v2/runs/{state['run'].id}")).json()

    assert {e["provenance_state"] for e in payload["evidence"]} == {"UNCHECKED"}
    assert all(e["attested_against"] is None for e in payload["evidence"])
    assert {c["verification_state"] for c in payload["claims"]} == {"UNCHECKED"}
    assert {c["detection_state"] for c in payload["contradictions"]} == {"DETECTED"}
    # NULL means unmeasured and must arrive as null, never 0.
    assert payload["run"]["citation_resolution_rate"] is None


async def test_an_uncited_source_arrives_with_a_null_index(api):
    owner = {"user_id": api["user_id"], "project_id": api["project_id"]}
    state = await drive_lifecycle(api["db"], owner, approve=False)
    await v2_runtime.record_evidence(
        api["db"],
        state["run"],
        evidence=[dict(EVIDENCE[0], source_url="https://example.invalid/uncited")],
        numbered_sources=None,
    )
    await api["db"].commit()

    payload = (await api["client"].get(f"/api/v1/v2/runs/{state['run'].id}")).json()
    indexes = {s["url"]: s["citation_index"] for s in payload["sources"]}
    assert indexes["https://example.invalid/uncited"] is None
    # And uncited sources sort last rather than being hidden.
    assert payload["sources"][-1]["citation_index"] is None


async def test_approving_the_report_creates_the_artifact_in_one_call(api):
    owner = {"user_id": api["user_id"], "project_id": api["project_id"]}
    state = await drive_lifecycle(api["db"], owner, approve=False)

    resp = await api["client"].post(
        f"/api/v1/v2/runs/{state['run'].id}/report-review",
        json={"decision": "APPROVED"},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["artifact_id"] is not None

    payload = (await api["client"].get(f"/api/v1/v2/runs/{state['run'].id}")).json()
    assert payload["run"]["status"] == "COMPLETED"
    assert payload["artifact"]["review_decision"] == "APPROVED"


async def test_requesting_rework_creates_no_artifact(api):
    owner = {"user_id": api["user_id"], "project_id": api["project_id"]}
    state = await drive_lifecycle(api["db"], owner, approve=False)

    resp = await api["client"].post(
        f"/api/v1/v2/runs/{state['run'].id}/report-review",
        json={"decision": "REWORK_REQUESTED", "feedback": "more detail"},
    )
    assert resp.status_code == 201
    assert resp.json()["artifact_id"] is None

    payload = (await api["client"].get(f"/api/v1/v2/runs/{state['run'].id}")).json()
    assert payload["artifact"] is None


async def test_a_plan_review_creates_no_artifact(api):
    """The whole authorization rule, seen from the outside."""
    owner = {"user_id": api["user_id"], "project_id": api["project_id"]}
    run = await v2_runtime.create_run(
        api["db"], owner_id=owner["user_id"], project_id=owner["project_id"], question="q"
    )
    await v2_runtime.record_plan(
        api["db"], run, tasks=[{"id": 1}], outline_sections=[], origin="MODEL_PROPOSED"
    )
    await api["db"].commit()

    resp = await api["client"].post(f"/api/v1/v2/runs/{run.id}/plan-review", json={})
    assert resp.status_code == 201
    assert resp.json() == {
        "review_id": resp.json()["review_id"],
        "gate": "PLAN",
        "decision": "APPROVED",
    }

    payload = (await api["client"].get(f"/api/v1/v2/runs/{run.id}")).json()
    assert payload["artifact"] is None
    assert payload["reviews"][0]["revision_id"] is None


async def test_reviewing_a_run_with_no_report_is_a_conflict_not_a_crash(api):
    owner = {"user_id": api["user_id"], "project_id": api["project_id"]}
    run = await v2_runtime.create_run(
        api["db"], owner_id=owner["user_id"], project_id=owner["project_id"], question="q"
    )
    await api["db"].commit()
    resp = await api["client"].post(
        f"/api/v1/v2/runs/{run.id}/report-review", json={"decision": "APPROVED"}
    )
    assert resp.status_code == 409
    assert "no report" in resp.json()["detail"]


# ── Bundle and verification over HTTP ─────────────────────────────────────────────


async def test_the_bundle_endpoint_serves_the_frozen_artifact(api):
    owner = {"user_id": api["user_id"], "project_id": api["project_id"]}
    state = await drive_lifecycle(api["db"], owner)

    resp = await api["client"].get(f"/api/v1/v2/runs/{state['run'].id}/bundle.json")
    assert resp.status_code == 200
    assert "attachment" in resp.headers["content-disposition"]
    payload = json.loads(resp.text)
    assert payload["bundle_hash"] == state["artifact"].artifact_hash
    assert payload["report_hash"] == state["revision_2"].report_hash


async def test_the_bundle_endpoint_previews_before_approval(api):
    """Before approval it answers "what would be frozen?", assembled live."""
    owner = {"user_id": api["user_id"], "project_id": api["project_id"]}
    state = await drive_lifecycle(api["db"], owner, approve=False)

    resp = await api["client"].get(f"/api/v1/v2/runs/{state['run'].id}/bundle.json")
    assert resp.status_code == 200
    assert json.loads(resp.text)["report_hash"] == state["revision_2"].report_hash


async def test_the_bundle_endpoint_fails_closed_with_no_report(api):
    owner = {"user_id": api["user_id"], "project_id": api["project_id"]}
    run = await v2_runtime.create_run(
        api["db"], owner_id=owner["user_id"], project_id=owner["project_id"], question="q"
    )
    await api["db"].commit()
    resp = await api["client"].get(f"/api/v1/v2/runs/{run.id}/bundle.json")
    assert resp.status_code == 409
    assert "V2_NO_REVISION" in resp.json()["detail"]


async def test_verification_reports_every_check_not_a_boolean(api):
    owner = {"user_id": api["user_id"], "project_id": api["project_id"]}
    state = await drive_lifecycle(api["db"], owner)

    body = (await api["client"].get(f"/api/v1/v2/runs/{state['run'].id}/verification")).json()
    assert body["assembled"] is True
    assert body["passed"] is True
    assert body["frozen"] is True
    names = {c["name"] for c in body["checks"]}
    assert names >= {
        "bundle_integrity",
        "report_integrity",
        "evidence_integrity",
        "citation_resolution",
        "claim_evidence_linkage",
        "approval_chain",
    }
    assert all(c["passed"] for c in body["checks"]), body["checks"]


async def test_verification_says_unassembled_rather_than_failed(api):
    """`passed: null` is the unmeasured-vs-zero rule at the API boundary."""
    owner = {"user_id": api["user_id"], "project_id": api["project_id"]}
    run = await v2_runtime.create_run(
        api["db"], owner_id=owner["user_id"], project_id=owner["project_id"], question="q"
    )
    await api["db"].commit()

    body = (await api["client"].get(f"/api/v1/v2/runs/{run.id}/verification")).json()
    assert body["assembled"] is False
    assert body["passed"] is None, "a bundle that could not be built has not failed"
    assert body["reason"] == "V2_NO_REVISION"
    assert body["checks"] == []


async def test_verification_fails_loudly_when_the_report_is_tampered_with(api):
    """The check that makes the rest worth serving."""
    owner = {"user_id": api["user_id"], "project_id": api["project_id"]}
    state = await drive_lifecycle(api["db"], owner, approve=False)

    # Rewrite the revision's text without touching its hash — exactly what an attacker or
    # a buggy writer would produce.
    state["revision_2"].report_markdown = DRAFT + "\nAn inserted sentence.\n"
    await api["db"].commit()

    body = (await api["client"].get(f"/api/v1/v2/runs/{state['run'].id}/verification")).json()
    assert body["assembled"] is True
    failed = {c["name"] for c in body["checks"] if not c["passed"]}
    assert "approval_chain" in failed or "report_integrity" in failed
    assert body["passed"] is False
