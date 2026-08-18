"""
Bundle export is reachable, and what it produces actually verifies (M0C).

The `.bundle.json` artifact is the product's central differentiator — the landing page,
the login page, the settings copy and the comparison table all sell it. It shipped in
v1.0.0 as a server endpoint with **no control anywhere in the app** and **no route at all
on the desktop host**, so the only way to obtain one was to construct the URL by hand.

These tests cover the half that can be tested here: that both hosts serve the route, and
that a bundle a user can actually download passes the standalone verifier. The web
control itself is covered by `frontend/components/session/ReportView.test.tsx` and the
end-to-end journey by `frontend/e2e/golden.spec.ts`.

The load-bearing test is `test_desktop_bundle_passes_the_standalone_verifier`. A bundle
that downloads but fails verification is worse than no bundle: it teaches the reader that
FAIL is normal, which defeats the verifier far more thoroughly than a missing button.
Before M0C the sidecar wrote no `audit_log` row at either gate, so every desktop bundle
would have failed on `approval_chain` — see the planted-failure test at the bottom.
"""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from desktop.sidecar import create_sidecar_app
from research_engine import bundle, verify_bundle

TOKEN = "test-sidecar-token"


@pytest.fixture
async def sidecar(tmp_path):
    app = create_sidecar_app(data_dir=tmp_path, token=TOKEN, fake=True)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:9") as client:
            yield client


def _auth() -> dict:
    return {"Authorization": f"Bearer {TOKEN}"}


async def _until(client: httpx.AsyncClient, session_id: str, want: str, timeout: float = 30.0):
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        resp = await client.get(f"/api/v1/research/{session_id}", headers=_auth())
        assert resp.status_code == 200
        if resp.json()["status"] == want:
            return resp.json()
        await asyncio.sleep(0.2)
    raise AssertionError(f"session never reached {want}")


async def _completed_session(client: httpx.AsyncClient) -> str:
    """Run one fake research session all the way through the gate to COMPLETED."""
    start = await client.post(
        "/api/v1/research",
        headers=_auth(),
        json={"query": "What is retrieval-augmented generation?", "depth": "fast"},
    )
    assert start.status_code == 202
    session_id = start.json()["session_id"]

    await _until(client, session_id, "AWAITING_APPROVAL")
    approve = await client.post(
        f"/api/v1/research/{session_id}/approve", headers=_auth(), json={"approved": True}
    )
    assert approve.status_code == 200
    await _until(client, session_id, "COMPLETED")
    return session_id


# ── Both hosts serve the route ────────────────────────────────────────────────────


def _published_paths(app) -> set[str]:
    """Every path in the app's OpenAPI schema.

    Read from the schema rather than walking `app.routes`, which does not flatten an
    included router in this FastAPI version — a walk finds seven top-level routes and
    would have reported the server's own bundle endpoint missing. The schema is also the
    published contract, which is the right thing to assert parity about.
    """
    return set(app.openapi()["paths"])


def test_both_hosts_expose_the_bundle_route(tmp_path):
    """Parity, asserted rather than assumed.

    The chat panel 404'd on desktop for a whole release because the frontend rendered a
    control the sidecar had no route for. This is the same shape of defect, caught by a
    test instead of by a user.
    """
    from app.main import app as server_app

    desktop_app = create_sidecar_app(data_dir=tmp_path, token=TOKEN, fake=True)

    suffix = "/export.bundle.json"
    server = {p for p in _published_paths(server_app) if p.endswith(suffix)}
    desktop = {p for p in _published_paths(desktop_app) if p.endswith(suffix)}

    assert server, "the API server lost its bundle route"
    assert desktop, "the desktop sidecar has no bundle route — the download button 404s"
    # Same path, so one frontend URL works on both hosts. The web build and the desktop
    # build ship the same `ReportView`.
    assert server == desktop, f"hosts disagree on the bundle path: {server} vs {desktop}"


# ── The desktop bundle, end to end ────────────────────────────────────────────────


async def test_desktop_bundle_downloads_with_the_right_headers(sidecar):
    session_id = await _completed_session(sidecar)
    resp = await sidecar.get(f"/api/v1/research/{session_id}/export.bundle.json", headers=_auth())
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/json")
    assert (
        f'filename="research-{session_id[:8]}.bundle.json"' in resp.headers["content-disposition"]
    )


async def test_desktop_bundle_passes_the_standalone_verifier(sidecar):
    """The load-bearing test: what a user downloads is what a third party can check.

    Runs the real verifier over the real bytes — no fixture bundle, no hand-built
    manifest.
    """
    session_id = await _completed_session(sidecar)
    resp = await sidecar.get(f"/api/v1/research/{session_id}/export.bundle.json", headers=_auth())
    manifest = bundle.BundleManifest.model_validate_json(resp.text)

    result = verify_bundle.verify(manifest)
    failed = [c.name for c in result.checks if not c.passed]
    assert result.passed, f"desktop bundle failed verification: {failed}"


async def test_desktop_bundle_carries_the_approval_chain_that_links_to_this_report(sidecar):
    """`_check_approval_chain`'s load-bearing rule, stated directly.

    An `approved` entry's `draft_hash` must equal `report_hash`, which is what proves the
    human approved *this* text rather than some earlier draft.
    """
    session_id = await _completed_session(sidecar)
    resp = await sidecar.get(f"/api/v1/research/{session_id}/export.bundle.json", headers=_auth())
    manifest = bundle.BundleManifest.model_validate_json(resp.text)

    approved = [a for a in manifest.approval_chain if a.action == "approved"]
    assert approved, "no approval record — the sidecar is not writing an audit_log row"
    assert any(a.draft_hash == manifest.report_hash for a in approved)


async def test_desktop_bundle_reports_its_trace_as_available(sidecar):
    """`trace_available=True` on this host, and the trace is genuinely populated.

    `bundle.py`'s docstring cites the desktop sidecar as the example of a host that cannot
    do durable logging. That is out of date: `PersistingSink` writes an `agent_logs` row
    for every event, exactly as the server worker's sink does. Claiming otherwise would
    understate the artifact — the reverse of the usual failure, but still a false
    statement about what was measured.
    """
    session_id = await _completed_session(sidecar)
    resp = await sidecar.get(f"/api/v1/research/{session_id}/export.bundle.json", headers=_auth())
    manifest = bundle.BundleManifest.model_validate_json(resp.text)

    assert manifest.trace_available is True
    assert manifest.trace, "trace_available=True with an empty trace is a false claim"


async def test_desktop_bundle_carries_evidence_and_hashes_it(sidecar):
    session_id = await _completed_session(sidecar)
    resp = await sidecar.get(f"/api/v1/research/{session_id}/export.bundle.json", headers=_auth())
    manifest = bundle.BundleManifest.model_validate_json(resp.text)

    assert manifest.evidence, "evidence was not read back from the SQLite checkpointer"
    for record in manifest.evidence:
        assert record.content_hash == bundle.content_hash(record.snippet)


async def test_bundle_is_refused_before_the_run_completes(sidecar):
    """Mirrors the server: a bundle is an artifact of an approved report, not a draft."""
    start = await sidecar.post(
        "/api/v1/research",
        headers=_auth(),
        json={"query": "What is retrieval-augmented generation?", "depth": "fast"},
    )
    session_id = start.json()["session_id"]
    await _until(sidecar, session_id, "AWAITING_APPROVAL")

    resp = await sidecar.get(f"/api/v1/research/{session_id}/export.bundle.json", headers=_auth())
    assert resp.status_code == 400
    assert "COMPLETED" in resp.json()["detail"]


async def test_bundle_requires_authentication(sidecar):
    """The sidecar's token gate covers the new route like every other one."""
    session_id = await _completed_session(sidecar)
    resp = await sidecar.get(f"/api/v1/research/{session_id}/export.bundle.json")
    assert resp.status_code == 401


# ── Planted failures ──────────────────────────────────────────────────────────────


async def test_tampering_with_the_report_breaks_verification(sidecar):
    """The artifact's whole point: editing it after the fact is detectable."""
    session_id = await _completed_session(sidecar)
    resp = await sidecar.get(f"/api/v1/research/{session_id}/export.bundle.json", headers=_auth())
    payload = json.loads(resp.text)
    payload["report"] = payload["report"] + "\n\nAn edit nobody approved.\n"

    result = verify_bundle.verify(bundle.BundleManifest.model_validate(payload))
    failed = {c.name for c in result.checks if not c.passed}
    assert not result.passed
    assert "report_integrity" in failed
    assert "bundle_integrity" in failed


async def test_a_bundle_with_no_approval_chain_fails_verification(sidecar):
    """Why the sidecar had to start writing `audit_log` rows in M0C.

    This reproduces the state the desktop host was in before that change: the run
    completes, the report is real, every hash matches — and the artifact still fails,
    because nothing recorded that a human approved it. Shipping the download button
    without the audit row would have made every desktop bundle look like this.
    """
    session_id = await _completed_session(sidecar)
    resp = await sidecar.get(f"/api/v1/research/{session_id}/export.bundle.json", headers=_auth())
    payload = json.loads(resp.text)
    payload["approval_chain"] = []
    # Re-hash so the ONLY failure is the missing chain, not incidental tampering.
    manifest = bundle.BundleManifest.model_validate(payload)
    manifest.bundle_hash = bundle.compute_bundle_hash(manifest)

    result = verify_bundle.verify(manifest)
    failed = {c.name for c in result.checks if not c.passed}
    assert not result.passed
    assert failed == {"approval_chain"}, f"expected only approval_chain to fail, got {failed}"


async def test_rework_then_approve_records_both_decisions(sidecar):
    """The chain is a chain: a rejected draft leaves a record, not a gap."""
    start = await sidecar.post(
        "/api/v1/research",
        headers=_auth(),
        json={"query": "What is retrieval-augmented generation?", "depth": "fast"},
    )
    session_id = start.json()["session_id"]
    await _until(sidecar, session_id, "AWAITING_APPROVAL")

    rework = await sidecar.post(
        f"/api/v1/research/{session_id}/approve",
        headers=_auth(),
        json={"approved": False, "feedback": "Add more on cost trade-offs."},
    )
    assert rework.status_code == 200
    await _until(sidecar, session_id, "AWAITING_APPROVAL")

    approve = await sidecar.post(
        f"/api/v1/research/{session_id}/approve", headers=_auth(), json={"approved": True}
    )
    assert approve.status_code == 200
    await _until(sidecar, session_id, "COMPLETED")

    resp = await sidecar.get(f"/api/v1/research/{session_id}/export.bundle.json", headers=_auth())
    manifest = bundle.BundleManifest.model_validate_json(resp.text)

    actions = [a.action for a in manifest.approval_chain]
    assert "rework_requested" in actions
    assert "approved" in actions
    assert actions.index("rework_requested") < actions.index("approved")
    # The rework's feedback is part of the record — it is why the draft changed.
    reworks = [a for a in manifest.approval_chain if a.action == "rework_requested"]
    assert reworks[0].feedback == "Add more on cost trade-offs."

    assert verify_bundle.verify(manifest).passed
