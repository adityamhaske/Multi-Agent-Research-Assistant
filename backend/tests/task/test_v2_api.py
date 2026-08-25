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
from research_engine.runconfig import ROLES
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


async def test_approving_a_plan_moves_the_run_to_running_in_the_same_commit(api):
    """A workspace must not go stale the moment a plan is approved.

    The client refetches when the mutation succeeds. If the run were still AWAITING_PLAN at
    that point it would conclude nothing is live, keep its event stream closed, and never
    learn the run had resumed — which is exactly what the plan-gate journey found.
    """
    owner = {"user_id": api["user_id"], "project_id": api["project_id"]}
    run = await v2_runtime.create_run(
        api["db"],
        owner_id=owner["user_id"],
        project_id=owner["project_id"],
        question="q",
        skip_plan_gate=False,
    )
    await v2_runtime.record_plan(
        api["db"], run, tasks=[{"id": 1}], outline_sections=[], origin="MODEL_PROPOSED"
    )
    await v2_runtime.set_status(api["db"], run, "AWAITING_PLAN")
    await api["db"].commit()

    resp = await api["client"].post(
        f"/api/v1/v2/runs/{run.id}/plan-review", json={"decision": "APPROVED", "dispatch": True}
    )
    assert resp.status_code == 201

    payload = (await api["client"].get(f"/api/v1/v2/runs/{run.id}")).json()
    assert payload["run"]["status"] == "RUNNING", "the client would see a stalled run"
    assert payload["artifact"] is None, "a plan approval still authorizes no artifact"


async def test_requesting_plan_changes_does_not_start_research(api):
    owner = {"user_id": api["user_id"], "project_id": api["project_id"]}
    run = await v2_runtime.create_run(
        api["db"],
        owner_id=owner["user_id"],
        project_id=owner["project_id"],
        question="q",
        skip_plan_gate=False,
    )
    await v2_runtime.record_plan(
        api["db"], run, tasks=[{"id": 1}], outline_sections=[], origin="MODEL_PROPOSED"
    )
    await v2_runtime.set_status(api["db"], run, "AWAITING_PLAN")
    await api["db"].commit()

    await api["client"].post(
        f"/api/v1/v2/runs/{run.id}/plan-review", json={"decision": "REWORK_REQUESTED"}
    )
    payload = (await api["client"].get(f"/api/v1/v2/runs/{run.id}")).json()
    assert payload["run"]["status"] == "AWAITING_PLAN"


async def _plan_with_nothing_selected(api, *, tasks):
    """A run parked at the design gate whose proposed plan selects `tasks`."""
    run = await v2_runtime.create_run(
        api["db"],
        owner_id=api["user_id"],
        project_id=api["project_id"],
        question="q",
        skip_plan_gate=False,
    )
    await v2_runtime.record_plan(
        api["db"], run, tasks=tasks, outline_sections=[], origin="MODEL_PROPOSED"
    )
    await v2_runtime.set_status(api["db"], run, "AWAITING_PLAN")
    await api["db"].commit()
    return run


async def test_approving_a_plan_with_every_task_excluded_is_refused(api):
    """The hole that produced an eleven-claim report with zero evidence (run 63091d21).

    A local planner proposed four subtopics and marked every one `include: false`. V1's
    gate has always rejected this; V2 had no such check, so the approval was recorded, the
    graph filtered the task list to `[]`, nothing was searched, and the synthesizer wrote
    the report from its own training data with repaired citations pointing at nothing.

    Refused *before* the review row is written, because a recorded APPROVED review is
    itself evidence — the run must be left exactly as it was, still awaiting a real
    decision.
    """
    run = await _plan_with_nothing_selected(
        api,
        tasks=[
            {"id": 1, "query": "brand equity definition", "include": False},
            {"id": 2, "query": "customer satisfaction metrics", "include": False},
        ],
    )

    resp = await api["client"].post(
        f"/api/v1/v2/runs/{run.id}/plan-review", json={"decision": "APPROVED", "dispatch": True}
    )
    assert resp.status_code == 422
    assert "at least one task" in resp.json()["detail"]

    payload = (await api["client"].get(f"/api/v1/v2/runs/{run.id}")).json()
    assert payload["run"]["status"] == "AWAITING_PLAN", "a refused approval must not start the run"
    assert payload["reviews"] == [], "a refused approval must not be recorded as a decision"


async def test_approving_a_plan_that_kept_one_task_is_still_allowed(api):
    """Negative control: the guard must reject *nothing selected*, not every plan.

    `dispatch: False` keeps this off the broker — what is under test is the validation,
    not the resume.
    """
    run = await _plan_with_nothing_selected(
        api,
        tasks=[
            {"id": 1, "query": "kept", "include": True},
            {"id": 2, "query": "dropped", "include": False},
        ],
    )
    resp = await api["client"].post(
        f"/api/v1/v2/runs/{run.id}/plan-review", json={"decision": "APPROVED", "dispatch": False}
    )
    assert resp.status_code == 201


async def test_a_task_with_no_include_key_still_counts_as_selected(api):
    """`include` defaults to True in the schema, and the guard must read it the same way.

    Every V1-era and migrated plan omits the key entirely; treating absent as excluded
    would refuse approval on plans that are perfectly valid.
    """
    run = await _plan_with_nothing_selected(api, tasks=[{"id": 1, "query": "no include key"}])
    resp = await api["client"].post(
        f"/api/v1/v2/runs/{run.id}/plan-review", json={"decision": "APPROVED", "dispatch": False}
    )
    assert resp.status_code == 201


async def test_requesting_rework_on_an_empty_plan_is_still_allowed(api):
    """Asking for changes is the *correct* response to a plan that selects nothing.

    The guard is on APPROVED only. Blocking rework here would trap the run: the reviewer
    could neither approve it nor ask the planner to try again.
    """
    run = await _plan_with_nothing_selected(api, tasks=[{"id": 1, "query": "a", "include": False}])
    resp = await api["client"].post(
        f"/api/v1/v2/runs/{run.id}/plan-review", json={"decision": "REWORK_REQUESTED"}
    )
    assert resp.status_code == 201


async def test_a_reviewer_can_repair_an_all_excluded_plan_by_editing_it(api):
    """The remedy for the run that searched nothing, exercised through the contract.

    The planner proposed both subtopics excluded. The reviewer re-selects one and
    approves; the run proceeds on exactly that one. Before this, the request body carried
    no task list at all, so the only possible outcomes were "approve what the planner
    proposed" or "ask for a rework".
    """
    run = await _plan_with_nothing_selected(
        api,
        tasks=[
            {"id": 1, "query": "brand equity", "include": False},
            {"id": 2, "query": "csat metrics", "include": False},
        ],
    )
    resp = await api["client"].post(
        f"/api/v1/v2/runs/{run.id}/plan-review",
        json={
            "decision": "APPROVED",
            "dispatch": False,
            "tasks": [
                {"id": 1, "query": "brand equity", "include": True},
                {"id": 2, "query": "csat metrics", "include": False},
            ],
        },
    )
    assert resp.status_code == 201, resp.text

    payload = (await api["client"].get(f"/api/v1/v2/runs/{run.id}")).json()
    plans = payload["plans"]
    # The proposal is kept and the edit appended, so what the model suggested and what a
    # human approved stay distinguishable — `origin` is the only thing that says which.
    assert len(plans) == 2
    assert plans[0]["origin"] == "MODEL_PROPOSED"
    assert plans[-1]["origin"] == "HUMAN_EDITED"
    assert [t["query"] for t in plans[-1]["tasks"]] == ["brand equity"]


async def test_editing_a_plan_down_to_nothing_is_still_refused(api):
    """The edit path cannot be used to get around the guard the proposal path enforces."""
    run = await _plan_with_nothing_selected(api, tasks=[{"id": 1, "query": "a", "include": True}])
    resp = await api["client"].post(
        f"/api/v1/v2/runs/{run.id}/plan-review",
        json={
            "decision": "APPROVED",
            "tasks": [{"id": 1, "query": "a", "include": False}],
        },
    )
    assert resp.status_code == 422
    assert "at least one task" in resp.json()["detail"]


async def test_an_unedited_approval_records_no_second_plan_version(api):
    """`None` tasks means "unedited". A version per approval would be noise, and would
    relabel the planner's own proposal as a human edit."""
    run = await _plan_with_nothing_selected(api, tasks=[{"id": 1, "query": "a", "include": True}])
    resp = await api["client"].post(
        f"/api/v1/v2/runs/{run.id}/plan-review",
        json={"decision": "APPROVED", "dispatch": False},
    )
    assert resp.status_code == 201

    plans = (await api["client"].get(f"/api/v1/v2/runs/{run.id}")).json()["plans"]
    assert len(plans) == 1
    assert plans[0]["origin"] == "MODEL_PROPOSED"


async def test_a_run_records_the_routing_it_was_started_with(api):
    """A per-run model choice has to be durable to be a choice at all.

    `run_config_for_run` treats a stamped `model_routing` as authoritative, so this one
    value is what every role, every resume, the export's attribution and the bundle read.
    """
    routing = {role: "custom:auto/best-fast" for role in ROLES}
    resp = await api["client"].post(
        "/api/v1/v2/runs",
        json={
            "project_id": str(api["project_id"]),
            "question": "Does RAG help?",
            "model_routing": routing,
            "dispatch": False,
        },
    )
    assert resp.status_code == 201, resp.text

    payload = (await api["client"].get(f"/api/v1/v2/runs/{resp.json()['run_id']}")).json()
    assert payload["run"]["model_routing"] == routing


async def test_a_local_model_route_survives_with_its_tag(api):
    """The desktop's own picker offers installed tags, and `qwen2.5:7b` is one id."""
    routing = {role: "ollama:qwen2.5:7b" for role in ROLES}
    resp = await api["client"].post(
        "/api/v1/v2/runs",
        json={
            "project_id": str(api["project_id"]),
            "question": "q",
            "model_routing": routing,
            "dispatch": False,
        },
    )
    assert resp.status_code == 201, resp.text
    payload = (await api["client"].get(f"/api/v1/v2/runs/{resp.json()['run_id']}")).json()
    assert payload["run"]["model_routing"]["planner"] == "ollama:qwen2.5:7b"


async def test_an_unroutable_model_is_refused_before_the_run_exists(api):
    """Rejected at the door rather than inside the worker minutes later."""
    resp = await api["client"].post(
        "/api/v1/v2/runs",
        json={
            "project_id": str(api["project_id"]),
            "question": "q",
            "model_routing": {role: "google:no-such-model" for role in ROLES},
            "dispatch": False,
        },
    )
    assert resp.status_code == 422
    assert "catalog" in resp.json()["detail"]


async def test_omitting_routing_leaves_the_run_on_saved_settings(api):
    """Negative control: the default path must not start stamping a routing.

    A caller that does not care is resolved at execution time (run → user → deployment),
    and stamping something here would freeze today's default onto tomorrow's run.
    """
    resp = await api["client"].post(
        "/api/v1/v2/runs",
        json={"project_id": str(api["project_id"]), "question": "q", "dispatch": False},
    )
    assert resp.status_code == 201
    payload = (await api["client"].get(f"/api/v1/v2/runs/{resp.json()['run_id']}")).json()
    assert payload["run"]["model_routing"] is None
