"""
Server ↔ desktop parity (M1).

AGENTS.md opens on the recurring bug in this repository: "Server and desktop are parallel
implementations of the same contract. Every shared behaviour has two homes, and the second
one gets forgotten." It lists eight such behaviours and records that each was wrong at
least once. Two of them — report chat and bundle export — shipped as controls the UI
rendered and the sidecar had no route for.

The failure mode is always the same, and it is not that the two implementations differ.
They are *supposed* to differ: one has Postgres, Redis, Celery and multi-user auth; the
other has SQLite, a keychain and one local user. The failure is that a difference nobody
decided on reaches a user as a 404.

So these tests do not assert identical implementations. They assert:

1. **Every difference is declared.** A route on one host and not the other must be named
   below with a reason, or the test fails.
2. **Declarations cannot rot.** A declared divergence that no longer exists also fails, so
   the lists shrink as things are fixed instead of accumulating.
3. **The UI's contract is satisfied.** Every API path the desktop build actually calls must
   exist on the sidecar. This is the check that would have caught the chat 404 and the
   bundle 404; it found six more in M1, which M1.5 then closed, along with a seventh that
   M1 had misfiled as an intentional difference.
4. **Shared routes agree in shape**, because the same TypeScript types read both.
5. **Security boundaries hold on both**, swept generically rather than per route.

M1 is deliberately *only* this. No shared-service extraction (M7), no schema change, and no
fix for what is found here — a test that records a real defect is worth more than one that
hides it, and the extraction in M7 is only safe once this contract exists to hold it.
"""

from __future__ import annotations

import tempfile

import httpx
import pytest

from desktop.sidecar import create_sidecar_app

TOKEN = "test-parity-token"


def _auth() -> dict:
    return {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture
async def sidecar(tmp_path):
    app = create_sidecar_app(data_dir=tmp_path, token=TOKEN, fake=True)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:9") as client:
            yield client


# ── Route surfaces ────────────────────────────────────────────────────────────────


def _server_app():
    from app.main import app

    return app


def _desktop_app():
    return create_sidecar_app(data_dir=tempfile.mkdtemp(), token=TOKEN, fake=True)


def _operations(app, strip: str = "/api/v1") -> set[str]:
    """`"GET /research/{session_id}"` for every published operation.

    Read from the OpenAPI document rather than `app.routes`, which does not flatten an
    included router in this FastAPI version.
    """
    out: set[str] = set()
    for path, item in app.openapi()["paths"].items():
        normalised = path[len(strip) :] if path.startswith(strip) else path
        for method in item:
            if method in ("get", "post", "put", "patch", "delete"):
                out.add(f"{method.upper()} {normalised}")
    return out


#: On the server and deliberately not on the desktop host. The reason matters more than the
#: entry: a route here is a *product decision*, not an oversight.
INTENTIONAL_SERVER_ONLY: dict[str, str] = {
    # Auth. The desktop app is one local user behind a per-launch bearer token; there is no
    # registration, no password, no refresh rotation and no BYOK column to encrypt. Keys
    # live in the OS keychain and are managed through /desktop/keys/*.
    "POST /auth/register": "no accounts on desktop — single local user (docs/13 §7)",
    "POST /auth/login": "no accounts on desktop",
    "POST /auth/logout": "no session cookie to clear",
    "POST /auth/refresh": "no refresh-token rotation without accounts",
    "POST /auth/me/password": "no password to change",
    "PUT /auth/me/api-key": "keys are keychain-backed — PUT /desktop/keys/{provider}",
    "DELETE /auth/me/api-key": "keys are keychain-backed — DELETE /desktop/keys/{provider}",
    # A nickname for the server's single active-connection row. Desktop keeps one keychain
    # entry per provider already labeled by provider name, not one active connection to
    # disambiguate, so there is nothing here for a sidecar route to rename yet.
    "PATCH /auth/me/api-key/label": "no active-connection concept on desktop — keys are per-provider",
    # Project memory is pgvector-only, stated as a known gap in the v1.0.0 release notes
    # and handled in the UI: `project/page.tsx` branches on `isDesktop` and explains it,
    # and SideNav hides Chat entirely on desktop.
    "GET /projects/{project_id}/memory/status": "project memory is pgvector-only",
    "GET /projects/{project_id}/threads": "project chat is pgvector-only (AGENTS.md)",
    "POST /projects/{project_id}/threads": "project chat is pgvector-only",
    "DELETE /threads/{thread_id}": "project chat is pgvector-only",
    "GET /threads/{thread_id}/messages": "project chat is pgvector-only",
    "POST /threads/{thread_id}/messages": "project chat is pgvector-only",
    # Container orchestration concerns. The shell learns the sidecar is up from the
    # stdout handshake (docs/13 §7), not by polling a health endpoint.
    "GET /health": "the Tauri shell uses the stdout handshake, not HTTP health",
    "GET /health/ready": "no compose healthcheck on desktop",
    "GET /models/readiness": "server-side first-run readiness probe; desktop uses /desktop/keys",
    "GET /models/providers/health": (
        "desktop takes the provider as a path segment: /models/providers/health/{provider}; "
        "the frontend already branches on isDesktop for this one"
    ),
}

#: On the desktop host and deliberately not on the server.
INTENTIONAL_DESKTOP_ONLY: dict[str, str] = {
    "GET /desktop/keys": "OS keychain status; the server stores encrypted keys on the user row",
    "PUT /desktop/keys/{provider}": "keys go to the OS keychain, never to a database column",
    "DELETE /desktop/keys/{provider}": "removes the key from the OS keychain",
    "GET /desktop/keys/custom_endpoint": "custom base URL is local config, not a user column",
    "PUT /desktop/keys/custom_endpoint": "custom base URL is local config, not a user column",
    "GET /corpus/documents": "flat per-app corpus; the server scopes a corpus file per project",
    "POST /corpus/documents": "flat per-app corpus; the server scopes a corpus file per project",
    "DELETE /corpus/documents/{doc_id}": "flat per-app corpus, one corpus.sqlite for the app",
    "GET /corpus/status": "flat per-app corpus, one corpus.sqlite for the whole app",
    "PUT /corpus/mode": "corpus-only is persistent desktop state; the server takes it per run",
    "POST /models/local/start": "the desktop app can spawn a local Ollama; a container cannot",
    "POST /models/local/stop": "the desktop app can stop the Ollama process it spawned",
    "GET /models/providers/health/{provider}": (
        "path-segment form of the server's query-parameter variant; the frontend already "
        "branches on isDesktop for this one, which is why it is not a UI gap"
    ),
}


def test_every_server_only_route_is_declared():
    """Declared in one of two senses, and the difference between them is the point.

    `INTENTIONAL_SERVER_ONLY` means the route legitimately does not exist on the desktop
    host. `KNOWN_DESKTOP_GAPS` means the UI calls it anyway, so its absence reaches a user.
    A route can be in both — the flat `/corpus/*` shape is a real decision *and* the UI was
    never taught about it — because they answer different questions.
    """
    server_only = _operations(_server_app()) - _operations(_desktop_app())
    undeclared = server_only - set(INTENTIONAL_SERVER_ONLY) - set(KNOWN_DESKTOP_GAPS)
    assert not undeclared, (
        "Routes exist on the server and not on the desktop host, with no recorded reason.\n"
        "Add the route to the sidecar, declare it in INTENTIONAL_SERVER_ONLY with why, or — "
        "if the desktop UI calls it — record it in KNOWN_DESKTOP_GAPS with its issue:\n  "
        + "\n  ".join(sorted(undeclared))
    )


def test_every_desktop_only_route_is_declared():
    desktop_only = _operations(_desktop_app()) - _operations(_server_app())
    undeclared = desktop_only - set(INTENTIONAL_DESKTOP_ONLY)
    assert not undeclared, (
        "Routes exist on the desktop host and not on the server, with no recorded reason:\n  "
        + "\n  ".join(sorted(undeclared))
    )


def test_declared_divergences_are_still_real():
    """Guards the lists themselves, the same way `test_engine_boundary` guards its own.

    A divergence someone fixed must be deleted from the declaration, or the list slowly
    becomes a description of the past.
    """
    server_only = _operations(_server_app()) - _operations(_desktop_app())
    desktop_only = _operations(_desktop_app()) - _operations(_server_app())

    stale_server = set(INTENTIONAL_SERVER_ONLY) - server_only
    stale_desktop = set(INTENTIONAL_DESKTOP_ONLY) - desktop_only
    assert not stale_server, (
        f"Resolved — remove from INTENTIONAL_SERVER_ONLY: {sorted(stale_server)}"
    )
    assert not stale_desktop, (
        f"Resolved — remove from INTENTIONAL_DESKTOP_ONLY: {sorted(stale_desktop)}"
    )


def test_every_declared_divergence_states_a_reason():
    for table in (INTENTIONAL_SERVER_ONLY, INTENTIONAL_DESKTOP_ONLY):
        for route, reason in table.items():
            assert reason and len(reason) > 15, f"{route} needs a real reason, not {reason!r}"


# ── The UI's contract ─────────────────────────────────────────────────────────────
#
# The check that would have caught the chat 404 and the bundle 404.

#: Every API path the frontend calls that is reachable in the **desktop** build, with the
#: surface that calls it. Maintained by hand from `frontend/hooks/queries.ts` and the
#: components; a path here is a promise the sidecar has to keep.
#:
#: Paths only reachable behind an `isDesktop` guard are deliberately absent: project chat
#: (SideNav hides it) and project memory (`project/page.tsx` renders an explanation
#: instead) are not called on desktop at all.
DESKTOP_UI_CALLS: dict[str, str] = {
    "GET /auth/me": "AppShell — the local user identity",
    "GET /projects": "ProjectSwitcher",
    "POST /projects": "ProjectSwitcher — create",
    "PATCH /projects/{project_id}": "ProjectsSection — rename, archive, restore",
    "DELETE /projects/{project_id}": "ProjectsSection — delete",
    "POST /research": "dashboard run form",
    "GET /research": "history, project overview",
    "GET /research/{session_id}": "session view",
    "GET /research/{session_id}/stream": "live monitor (SSE)",
    "GET /research/{session_id}/plan": "PlanGate",
    "POST /research/{session_id}/plan": "PlanGate — submit the edited design",
    "POST /research/{session_id}/approve": "ApprovalGate",
    "GET /research/{session_id}/chat": "ChatPanel — history",
    "POST /research/{session_id}/chat": "ChatPanel — ask",
    "GET /research/{session_id}/export.md": "ReportView",
    "GET /research/{session_id}/export.pdf": "ReportView (501 on desktop, handled)",
    "GET /research/{session_id}/export.bundle.json": "ReportView — M0C",
    "POST /research/{session_id}/cancel": "SessionView — the Stop button (M1.5)",
    "GET /projects/{project_id}/corpus/documents": "Corpus page, project overview (M1.5)",
    "POST /projects/{project_id}/corpus/documents": "Corpus page — upload (M1.5)",
    "DELETE /projects/{project_id}/corpus/documents/{doc_id}": "Corpus page — delete (M1.5)",
    "GET /projects/{project_id}/corpus/status": "Corpus page, project overview (M1.5)",
    "GET /projects/{project_id}/corpus/documents/{doc_id}/download": (
        "DocumentPreview via documentUrl(), from the Corpus page and ReportView (M1.5)"
    ),
    "GET /auth/me/usage": "Settings — the usage panel (M1.5)",
    "POST /research/{session_id}/archive": "SessionCard",
    "POST /research/{session_id}/unarchive": "history archive view",
    "DELETE /research/{session_id}": "SessionCard — delete",
    "GET /research/outline-templates": "OutlineTemplatePicker",
    "GET /models": "StartModelPicker, ModelPicker",
    "GET /models/routing": "settings",
    "PUT /models/routing": "settings",
    "DELETE /models/routing": "settings",
    "GET /models/local/status": "LocalLLMCard",
    "POST /models/local/pull": "LocalLLMCard",
    "POST /models/providers/test": "connection test",
    # The research workspace. This block was missing while the desktop build was already
    # shipping `/research` and `/research/run` — the sidebar's primary control points at
    # the first — so the table said the desktop journey used sessions long after it had stopped
    # being. That omission is what let `POST /runs` answer 501 to the packaged app's
    # Start research button without any test objecting: parity only checks what this
    # table claims the client calls.
    "POST /runs": "StartResearchForm — Start research",
    "GET /runs": "Research page, Overview — the run list",
    "GET /runs/{run_id}": "RunWorkspace — the aggregate graph",
    "GET /runs/{run_id}/stream": "RunWorkspace — live events (SSE)",
    "POST /runs/{run_id}/plan-review": "PlanPanel — approve or edit the design",
    "POST /runs/{run_id}/report-review": "ReviewPanel — approve or request rework",
    "POST /runs/{run_id}/cancel": "RunWorkspace — the Stop button",
    "GET /runs/{run_id}/verification": "ArtifactPanel — the standalone verifier",
    "GET /runs/{run_id}/bundle.json": "ArtifactPanel — the verifiable bundle",
    "GET /runs/{run_id}/export.md": "ReportPanel",
    "GET /runs/{run_id}/export.pdf": "ReportPanel (501 on desktop, handled)",
    "POST /runs/{run_id}/archive": "RunCard — archive",
    "POST /runs/{run_id}/unarchive": "RunCard — restore",
    "DELETE /runs/{run_id}": "RunCard — delete",
}

#: Paths the desktop UI calls that the sidecar does **not** serve — controls that 404.
#:
#: **Empty since M1.5.** M1 found six and recorded them here rather than fixing them, because
#: a contract milestone that also repairs things cannot show which of its tests were load-
#: bearing. M1.5 then closed all of them, plus a seventh M1 had misfiled: the corpus document
#: *download* path was listed only as an intentional server-only route, on the reading that
#: the UI did not call it. It does — `documentUrl()` builds it for both the Corpus page and
#: the report preview drawer — so it was a live 404 that this table failed to name. The
#: `DESKTOP_UI_CALLS` entry above is what now prevents that particular mistake: a path is
#: judged by whether the client calls it, not by anyone's recollection.
#:
#: Keep it empty. An entry here is a shipped control that does not work.
KNOWN_DESKTOP_GAPS: dict[str, str] = {}


def test_desktop_ui_calls_are_served_by_the_sidecar():
    """Every path the desktop build calls must exist, or be a recorded gap.

    This is the test that turns "a control that 404s" from something a user discovers into
    something a pull request discovers.
    """
    served = _operations(_desktop_app())
    missing = {call for call in DESKTOP_UI_CALLS if call not in served}
    assert not missing, (
        "The desktop UI calls paths the sidecar does not serve — these render as controls "
        "that 404:\n  " + "\n  ".join(sorted(missing))
    )


def test_known_desktop_gaps_are_still_real():
    """A gap that has been fixed must leave this list, so the count only falls."""
    served = _operations(_desktop_app())
    fixed = {gap for gap in KNOWN_DESKTOP_GAPS if gap in served}
    assert not fixed, f"Fixed — remove from KNOWN_DESKTOP_GAPS: {sorted(fixed)}"


def test_known_desktop_gaps_are_not_silently_growing():
    """A ceiling, so a future change cannot quietly add a seventh 404.

    Raising this number should take an argument, the same way adding to
    `test_engine_boundary.KNOWN_EXCEPTIONS` should.
    """
    assert len(KNOWN_DESKTOP_GAPS) == 0, (
        f"{len(KNOWN_DESKTOP_GAPS)} desktop UI call(s) now 404. M1.5 brought this to zero; "
        "a new entry is a control that ships broken. Serve the path on both hosts, or stop "
        "the desktop build from rendering the control."
    )


# ── Shared routes agree in shape ──────────────────────────────────────────────────


def _response_models(app, strip: str = "/api/v1") -> dict[str, str]:
    """`operation -> response schema name` for 2xx JSON responses."""
    out: dict[str, str] = {}
    for path, item in app.openapi()["paths"].items():
        normalised = path[len(strip) :] if path.startswith(strip) else path
        for method, op in item.items():
            if method not in ("get", "post", "put", "patch", "delete"):
                continue
            for code, resp in (op.get("responses") or {}).items():
                if not str(code).startswith("2"):
                    continue
                schema = (resp.get("content") or {}).get("application/json", {}).get("schema") or {}
                ref = schema.get("$ref") or (schema.get("items") or {}).get("$ref")
                if ref:
                    out[f"{method.upper()} {normalised}"] = ref.rsplit("/", 1)[-1]
    return out


def test_shared_routes_return_the_same_response_models():
    """One set of TypeScript types reads both hosts (`frontend/lib/types.ts`).

    A shared route returning a different shape on one host is a UI that renders correctly
    in the web build and wrongly in the desktop build, with nothing failing in between.
    """
    server = _response_models(_server_app())
    desktop = _response_models(_desktop_app())

    mismatched = {
        op: (server[op], desktop[op])
        for op in set(server) & set(desktop)
        if server[op] != desktop[op]
    }
    assert not mismatched, f"Shared routes disagree on response shape: {mismatched}"


def test_the_session_status_vocabulary_is_shared():
    """Both hosts import the same enum, and the UI's union mirrors it.

    A status one host can emit and the other cannot is how a client ends up with no branch
    for a state it is shown — the defect AGENTS.md records for `RunOutcome.status` and the
    two dict literals in `sidecar._apply_outcome`.
    """
    from app.models.session import SessionStatus

    assert {s.value for s in SessionStatus} == {
        "PENDING",
        "RUNNING",
        "AWAITING_PLAN",
        "AWAITING_APPROVAL",
        "COMPLETED",
        "FAILED",
    }


def test_run_outcome_statuses_are_all_handled_by_the_desktop_host():
    """The AGENTS.md trap, made executable.

    "A new `RunOutcome.status` → `pipeline_runner::_persist_outcome` *and* **both** dict
    literals in `sidecar::_apply_outcome`. A missing key there raises inside a background
    task, so the session sits on RUNNING forever with nothing in the log to say why."
    """
    import typing
    from pathlib import Path

    from desktop import sidecar as sidecar_module
    from research_engine.runner import RunStatus

    # `_apply_outcome` is a closure inside `create_sidecar_app`, so it cannot be reached as
    # a module attribute. Slice its region out of the source instead — robust to the
    # function moving, and it keeps the assertion on the two dict literals AGENTS.md names
    # rather than on the whole 2,000-line module, where a status could appear in an
    # unrelated string and pass vacuously.
    source = Path(sidecar_module.__file__).read_text(encoding="utf-8")
    start = source.index("async def _apply_outcome")
    end = source.index("async def _drive_session", start)
    region = source[start:end]

    statuses = set(typing.get_args(RunStatus))
    unhandled = {s for s in statuses if f'"{s}"' not in region}
    assert not unhandled, (
        f"`sidecar._apply_outcome` has no mapping for RunOutcome status {sorted(unhandled)} — "
        "the session would sit on RUNNING with nothing in the log to say why"
    )


def test_terminal_stream_events_agree_between_hosts():
    """A pause event missing from one stop-list leaves a stream open on a suspended graph.

    AGENTS.md: "A new pause event → the stream's stop-list in `app/api/v1/research.py`
    *and* `sidecar::_TERMINAL_EVENTS`; a stream left open on a suspended graph waits on
    no one."
    """
    import inspect

    from app.api.v1 import research as server_research
    from desktop.sidecar import _TERMINAL_EVENTS

    server_source = inspect.getsource(server_research.stream_events)
    for event in _TERMINAL_EVENTS:
        assert f'"{event}"' in server_source, (
            f"{event} ends the desktop stream but not the server's — a client on the server "
            "would hold a connection open on a graph that will publish nothing more"
        )


# ── Security boundaries, swept generically ────────────────────────────────────────


async def test_every_sidecar_route_requires_the_token(sidecar):
    """One sweep instead of one assertion per route, so a route added without auth fails.

    The sidecar binds an ephemeral localhost port, but "localhost" is not an authorisation
    boundary: any process on the machine, and any web page the user visits that can reach
    127.0.0.1, is a caller. The per-launch bearer token is the boundary (docs/13 §7).
    """
    app = create_sidecar_app(data_dir=tempfile.mkdtemp(), token=TOKEN, fake=True)
    checked = 0
    for path, item in app.openapi()["paths"].items():
        for method in item:
            if method not in ("get", "post", "put", "patch", "delete"):
                continue
            # SSE is the one documented concession: EventSource cannot set headers, so the
            # token travels as `?access_token=`. Still authenticated, just differently.
            if path.endswith("/stream"):
                continue
            concrete = (
                path.replace("{session_id}", "00000000-0000-0000-0000-000000000000")
                .replace("{project_id}", "00000000-0000-0000-0000-000000000000")
                .replace("{doc_id}", "1")
                .replace("{provider}", "google")
            )
            resp = await sidecar.request(method, concrete, json={})
            assert resp.status_code == 401, (
                f"{method.upper()} {path} answered {resp.status_code} without a token — "
                "every sidecar route is behind the per-launch bearer token"
            )
            checked += 1
    assert checked > 20, f"only swept {checked} routes; the sweep is not covering the surface"


async def test_the_sse_concession_still_requires_the_token(sidecar):
    """The one exemption is an exemption from the *header*, not from authentication."""
    sid = "00000000-0000-0000-0000-000000000000"
    unauthenticated = await sidecar.get(f"/api/v1/research/{sid}/stream")
    assert unauthenticated.status_code == 401

    wrong_token = await sidecar.get(f"/api/v1/research/{sid}/stream?access_token=not-the-token")
    assert wrong_token.status_code == 401


async def test_a_bad_token_is_rejected_like_a_missing_one(sidecar):
    resp = await sidecar.get("/api/v1/projects", headers={"Authorization": "Bearer wrong"})
    assert resp.status_code == 401


# ── Lifecycle contract, asserted against the host that can run it ─────────────────


async def test_gate_status_transitions_follow_the_shared_vocabulary(sidecar):
    """PENDING/RUNNING → AWAITING_APPROVAL → COMPLETED, using the shared enum's values.

    The desktop host is the one that can be driven end to end in-process; the server's
    half of this lives in `test_pipeline.py` and `test_session_lifecycle.py`. What is
    asserted here is that the *vocabulary* the desktop emits is the vocabulary the shared
    types and the UI branch on.
    """
    from app.models.session import SessionStatus

    start = await sidecar.post(
        "/api/v1/research",
        headers=_auth(),
        json={"query": "What is retrieval-augmented generation?", "depth": "fast"},
    )
    assert start.status_code == 202
    assert start.json()["status"] in {s.value for s in SessionStatus}
    session_id = start.json()["session_id"]

    import asyncio

    deadline = asyncio.get_event_loop().time() + 30
    seen: list[str] = []
    while asyncio.get_event_loop().time() < deadline:
        status = (await sidecar.get(f"/api/v1/research/{session_id}", headers=_auth())).json()[
            "status"
        ]
        if not seen or seen[-1] != status:
            seen.append(status)
        if status == SessionStatus.AWAITING_APPROVAL.value:
            break
        await asyncio.sleep(0.2)

    assert seen[-1] == SessionStatus.AWAITING_APPROVAL.value, f"transitions seen: {seen}"
    assert all(s in {e.value for e in SessionStatus} for s in seen), seen


async def test_resuming_a_gate_that_is_not_pending_conflicts(sidecar):
    """409, on both hosts, for the same reason.

    `app/api/v1/research.py::submit_plan` documents it: resuming a thread that is not
    suspended at the matching interrupt pushes a plan-shaped payload into whichever
    interrupt is pending, and `hitl_gate_node` reads a missing `approved` key as a
    rejection — silently counting a rework nobody asked for.
    """
    start = await sidecar.post(
        "/api/v1/research",
        headers=_auth(),
        json={"query": "What is retrieval-augmented generation?", "depth": "fast"},
    )
    session_id = start.json()["session_id"]

    # Approving before the draft gate is reached must not be accepted.
    early = await sidecar.post(
        f"/api/v1/research/{session_id}/approve", headers=_auth(), json={"approved": True}
    )
    assert early.status_code == 409
    assert "AWAITING_APPROVAL" in early.json()["detail"]


async def test_a_session_from_another_user_is_not_found_rather_than_forbidden(sidecar):
    """404, not 403 — the server's `_authorized_session` does the same.

    Returning 403 would confirm the session exists, which is a disclosure the desktop host
    does not need to make either.
    """
    resp = await sidecar.get(
        "/api/v1/research/00000000-0000-0000-0000-000000000000", headers=_auth()
    )
    assert resp.status_code == 404
