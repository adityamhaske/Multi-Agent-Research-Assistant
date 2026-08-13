"""
Desktop sidecar tests (docs/12 M9, docs/13 §7).

The DoD item under test here is the security one: *the sidecar rejects an
unauthenticated localhost request.* The token is per-launch and mandatory; the only
concession is `?access_token=` on the SSE endpoint, because native EventSource cannot
set headers and the WebView is the sole client.

The end-to-end flow (start → gate → approve → export) runs in fake mode against the
real graph, the real SQLite file, and the real SSE contract — the desktop host is a
thin adapter, so testing it through HTTP is the honest scope.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from desktop.sidecar import create_sidecar_app

TOKEN = "test-sidecar-token"


@pytest.fixture
async def sidecar(tmp_path):
    app = create_sidecar_app(data_dir=tmp_path, token=TOKEN, fake=True)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:9") as client:
            yield client


def _auth(token: str | None = TOKEN) -> dict:
    return {"Authorization": f"Bearer {token}"} if token else {}


# ── The security contract ────────────────────────────────────────────────────────


async def test_unauthenticated_request_is_rejected(sidecar):
    """DoD: the sidecar rejects an unauthenticated localhost request."""
    resp = await sidecar.get("/api/v1/research")
    assert resp.status_code == 401


async def test_wrong_token_is_rejected(sidecar):
    resp = await sidecar.get("/api/v1/research", headers=_auth("wrong-token"))
    assert resp.status_code == 401


async def test_stream_without_token_is_rejected(sidecar):
    """The EventSource query-parameter path is not a hole around the token."""
    resp = await sidecar.get("/api/v1/research/00000000-0000-0000-0000-000000000000/stream")
    assert resp.status_code == 401


async def test_cors_preflight_needs_no_token(sidecar):
    """The WebView origin is a Tauri asset origin, not the sidecar's — the browser
    sends a preflight that carries no bearer token, and it must still get CORS
    headers. A tokenless preflight is not a security hole: the real request is
    still gated by the token (asserted right after)."""
    origin = "tauri://localhost"
    preflight = await sidecar.options(
        "/api/v1/research",
        headers={"Origin": origin, "Access-Control-Request-Method": "POST"},
    )
    assert preflight.status_code == 200
    assert preflight.headers["access-control-allow-origin"] == origin

    # The actual request is still rejected without the token — CORS only lets the
    # browser *see* the 401, it does not grant access.
    denied = await sidecar.post("/api/v1/research", headers={"Origin": origin})
    assert denied.status_code == 401
    assert denied.headers["access-control-allow-origin"] == origin

    # A non-allow-listed origin gets no CORS headers at all.
    stranger = await sidecar.get("/api/v1/research", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in stranger.headers


# ── Local-user boot ──────────────────────────────────────────────────────────────


async def test_local_user_and_default_project(sidecar):
    me = await sidecar.get("/api/v1/auth/me", headers=_auth())
    assert me.status_code == 200
    assert me.json()["email"] == "local@desktop.invalid"

    projects = await sidecar.get("/api/v1/projects", headers=_auth())
    assert projects.status_code == 200
    names = [p["name"] for p in projects.json()["projects"]]
    assert names == ["General"]


async def test_model_catalog_marks_no_keys_unavailable(sidecar):
    """Fake mode has no provider keys: the picker must show everything unavailable
    rather than crashing or pretending."""
    resp = await sidecar.get("/api/v1/models", headers=_auth())
    assert resp.status_code == 200
    body = resp.json()
    assert body["available_providers"] == []
    assert body["models"], "the catalog must still render"
    assert all(m["available"] is False for m in body["models"])


# ── The research flow ────────────────────────────────────────────────────────────


async def _until(client: httpx.AsyncClient, session_id: str, want: str, timeout: float = 30.0):
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        resp = await client.get(f"/api/v1/research/{session_id}", headers=_auth())
        assert resp.status_code == 200
        if resp.json()["status"] == want:
            return resp.json()
        await asyncio.sleep(0.2)
    raise AssertionError(f"session never reached {want}")


async def test_fake_research_gate_approve_export(sidecar):
    start = await sidecar.post(
        "/api/v1/research",
        headers=_auth(),
        json={"query": "What is retrieval-augmented generation?", "depth": "fast"},
    )
    assert start.status_code == 202
    session_id = start.json()["session_id"]

    # Fake mode pauses at the human gate — the desktop keeps the gate (docs/13 §9).
    detail = await _until(sidecar, session_id, "AWAITING_APPROVAL")
    assert detail["draft_report"]

    approve = await sidecar.post(
        f"/api/v1/research/{session_id}/approve", headers=_auth(), json={"approved": True}
    )
    assert approve.status_code == 200

    detail = await _until(sidecar, session_id, "COMPLETED")
    assert detail["final_report"]
    assert detail["sources"], "a completed report carries its citation table"

    export = await sidecar.get(f"/api/v1/research/{session_id}/export.md", headers=_auth())
    assert export.status_code == 200
    assert export.text == detail["final_report"]

    # Desktop PDF is WebView print-to-PDF by design (docs/13 §7): no WeasyPrint here.
    pdf = await sidecar.get(f"/api/v1/research/{session_id}/export.pdf", headers=_auth())
    assert pdf.status_code == 501


# ── Settings: saved routing + keychain keys ──────────────────────────────────


async def test_routing_round_trip(sidecar, tmp_path):
    """The picker's save lands in `routing.json` and reads back through /models."""
    routing = {
        r: "google:gemini-2.5-flash"
        for r in ("planner", "executor", "critic", "synthesizer", "chat")
    }

    put = await sidecar.put("/api/v1/models/routing", headers=_auth(), json={"routing": routing})
    assert put.status_code == 200
    assert put.json()["routing"] == routing
    assert (tmp_path / "routing.json").exists()

    models = await sidecar.get("/api/v1/models", headers=_auth())
    assert models.json()["user_routing"] == routing
    assert models.json()["effective_routing"]["planner"] == "google:gemini-2.5-flash"

    # Rejected before storage, same contract as the server endpoint.
    bad = await sidecar.put(
        "/api/v1/models/routing", headers=_auth(), json={"routing": {"planner": "nope"}}
    )
    assert bad.status_code == 422
    assert (tmp_path / "routing.json").read_text() != ""

    clear = await sidecar.delete("/api/v1/models/routing", headers=_auth())
    assert clear.status_code == 200
    assert clear.json()["routing"] is None
    assert not (tmp_path / "routing.json").exists()


async def test_key_delete_forgets_the_keychain_entry(sidecar, monkeypatch):
    import desktop.sidecar as sc

    deleted: list[str] = []
    monkeypatch.setattr(sc, "delete_key", lambda provider: deleted.append(provider))

    resp = await sidecar.delete("/api/v1/desktop/keys/google", headers=_auth())
    assert resp.status_code == 204
    assert deleted == ["google"]

    unknown = await sidecar.delete("/api/v1/desktop/keys/nope", headers=_auth())
    assert unknown.status_code == 422


# ── The airgapped corpus (docs/12 M10) ──────────────────────────────────────────


def _install_fake_embedder(app_holder) -> None:
    """Swap the Ollama-backed embedder for the deterministic test fake.

    The sidecar's lifespan builds the store before tests can touch it, so the
    embedder is replaced in place — the store is the contract under test.
    """
    from tests.test_corpus_store import FakeEmbeddings

    # `app_holder` is the httpx client; the app hangs off its transport.
    app = app_holder._transport.app  # noqa: SLF001 — test-internal access
    app.state.sidecar["corpus"]._embedder = FakeEmbeddings()  # noqa: SLF001


# The scripted planner's two task queries are fixed strings (fakes.py); a corpus
# document containing those words is therefore guaranteed to be retrieved in
# fake-mode runs, keeping the end-to-end assertion non-vacuous.
CORPUS_DOC = (
    "Background and definitions: retrieval-augmented generation grounds a model in "
    "documents. Current state and data: adoption has grown steadily, and the current "
    "evidence shows grounded answers beat ungrounded ones on factual benchmarks."
)


async def test_corpus_upload_list_delete_round_trip(sidecar):
    _install_fake_embedder(sidecar)

    upload = await sidecar.post(
        "/api/v1/corpus/documents",
        params={"filename": "notes.txt"},
        headers=_auth(),
        content=CORPUS_DOC.encode(),
    )
    assert upload.status_code == 201
    body = upload.json()
    assert body["doc_id"] and body["chunks_written"] >= 1 and not body["skipped"]

    # Same bytes again: deduped, not doubled.
    again = await sidecar.post(
        "/api/v1/corpus/documents",
        params={"filename": "notes.txt"},
        headers=_auth(),
        content=CORPUS_DOC.encode(),
    )
    assert again.json()["skipped"] is True

    docs = await sidecar.get("/api/v1/corpus/documents", headers=_auth())
    assert [d["filename"] for d in docs.json()["documents"]] == ["notes.txt"]

    # A format we cannot locate quotes in never enters a citation-grade corpus.
    rejected = await sidecar.post(
        "/api/v1/corpus/documents",
        params={"filename": "archive.zip"},
        headers=_auth(),
        content=b"PK\x03\x04",
    )
    assert rejected.status_code == 422

    delete = await sidecar.delete(f"/api/v1/corpus/documents/{body['doc_id']}", headers=_auth())
    assert delete.status_code == 204
    gone = await sidecar.delete(f"/api/v1/corpus/documents/{body['doc_id']}", headers=_auth())
    assert gone.status_code == 404


async def test_corpus_only_run_cites_corpus_locations(sidecar, tmp_path):
    """The desktop's M10 DoD: with corpus-only mode switched on, a run's sources
    are corpus:// locations — not a single web URL — and the switch persists."""
    _install_fake_embedder(sidecar)

    mode = await sidecar.put("/api/v1/corpus/mode", headers=_auth(), json={"corpus_only": True})
    assert mode.json() == {"corpus_only": True}
    assert (tmp_path / "corpus.json").exists()

    status_resp = await sidecar.get("/api/v1/corpus/status", headers=_auth())
    assert status_resp.json()["corpus_only"] is True

    upload = await sidecar.post(
        "/api/v1/corpus/documents",
        params={"filename": "notes.txt"},
        headers=_auth(),
        content=CORPUS_DOC.encode(),
    )
    assert upload.status_code == 201

    start = await sidecar.post(
        "/api/v1/research",
        headers=_auth(),
        json={"query": "What does the corpus say about RAG?", "depth": "fast"},
    )
    assert start.status_code == 202
    detail = await _until(sidecar, start.json()["session_id"], "AWAITING_APPROVAL")

    assert detail["sources"], "corpus evidence must surface as sources"
    for source in detail["sources"]:
        assert source["url"].startswith("corpus://"), source["url"]

    # Switching back off persists too.
    off = await sidecar.put("/api/v1/corpus/mode", headers=_auth(), json={"corpus_only": False})
    assert off.json() == {"corpus_only": False}


async def test_stream_replays_to_the_terminal_event(sidecar):
    start = await sidecar.post(
        "/api/v1/research",
        headers=_auth(),
        json={"query": "Summarize vector database trade-offs.", "depth": "fast"},
    )
    session_id = start.json()["session_id"]
    await _until(sidecar, session_id, "AWAITING_APPROVAL")

    # The token travels as a query parameter here (native EventSource sets no headers).
    async with sidecar.stream(
        "GET",
        f"/api/v1/research/{session_id}/stream",
        params={"access_token": TOKEN},
    ) as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        lines = []
        async for line in resp.aiter_lines():
            lines.append(line)
            if "HITL_READY" in line:
                break
    assert any('"type": "connected"' in ln for ln in lines)
    assert any("HITL_READY" in ln for ln in lines)


def test_sidecar_import_tree_excludes_weasyprint():
    """The desktop bundle must not carry WeasyPrint's GTK chain (docs/13 §7).

    Checked in a fresh interpreter: importing the whole sidecar module — models,
    schemas, engine — must never pull it in. The PDF endpoint 501s instead.
    """
    import subprocess
    import sys

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import desktop.sidecar, sys; "
            "assert 'weasyprint' not in sys.modules, 'weasyprint imported by sidecar'; "
            "assert 'app.services.export' not in sys.modules, 'server export imported by sidecar'",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_shell_watchdog_predicate():
    """The sidecar must not outlive a hard-killed shell (docs/13 §7).

    The shell passes --shell-pid and a watchdog thread exits when that PID is gone;
    this covers the predicate the watchdog polls.
    """
    import subprocess
    import sys

    from desktop.sidecar import shell_alive

    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        assert shell_alive(child.pid)
    finally:
        child.kill()
    child.wait()
    assert not shell_alive(child.pid)
