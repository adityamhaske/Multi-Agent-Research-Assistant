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


# ── Schema evolution on an existing install ──────────────────────────────────────


async def test_existing_database_gains_columns_added_after_release(tmp_path):
    """An older desktop file must pick up columns added since it was created.

    The desktop builds its schema with `create_all`, not Alembic — the migrations are
    Postgres-shaped from 0001 (JSONB, later pgvector) and only the ORM's `with_variant`
    types are portable. But `create_all` never alters an existing table, so before this
    every column added after a user's first launch was invisible to them, and the first
    release adding one would have broken every install in the field.

    Simulated the only way that matters: build the schema, drop a column so the file looks
    older, put a row in it, then boot the sidecar and check the column returns without
    losing the row.
    """
    from sqlalchemy import create_engine, inspect

    from app.models.base import Base
    from app.models.memory_chunk import MemoryChunk

    # Must be the file the sidecar actually opens (see `create_sidecar_app`), or the test
    # silently passes against a fresh database it created itself and proves nothing.
    db = tmp_path / "desktop.sqlite"
    tables = [t for t in Base.metadata.sorted_tables if t.name != MemoryChunk.__tablename__]
    engine = create_engine(f"sqlite:///{db}")
    Base.metadata.create_all(engine, tables=tables)

    with engine.begin() as conn:
        conn.exec_driver_sql("ALTER TABLE sessions DROP COLUMN demo")
        conn.exec_driver_sql(
            "INSERT INTO sessions (id, user_id, project_id, prompt, status, research_depth,"
            " total_cost_usd, total_tokens_input, total_tokens_output, rework_count,"
            " created_at, updated_at) VALUES ('a', 'b', 'c', 'older run', 'COMPLETED',"
            " 'fast', 0, 0, 0, 0, datetime('now'), datetime('now'))"
        )
    assert "demo" not in {c["name"] for c in inspect(engine).get_columns("sessions")}
    engine.dispose()

    app = create_sidecar_app(data_dir=tmp_path, token=TOKEN, fake=True)
    async with app.router.lifespan_context(app):
        pass

    engine = create_engine(f"sqlite:///{db}")
    columns = {c["name"] for c in inspect(engine).get_columns("sessions")}
    assert "demo" in columns, "startup must add columns the ORM declares"
    with engine.connect() as conn:
        # Assert on the row this test inserted, not a total: startup also seeds a demo
        # session on first launch, so a count would couple this test to that feature.
        row = conn.exec_driver_sql(
            "SELECT demo FROM sessions WHERE prompt = 'older run'"
        ).fetchone()
        assert row is not None, "the pre-existing row must survive the column addition"
        # Defaults to "real research" — mislabelling real work as a demo is recoverable,
        # the reverse is not.
        assert row[0] == 0
    engine.dispose()


async def test_first_launch_seeds_a_demo_and_never_reseeds(tmp_path):
    """First launch leaves a finished demo waiting; later launches must not add more.

    The obvious trigger — "no sessions exist" — is wrong, because it re-creates the demo
    every launch after the user deletes it. A marker file is what makes a deletion stick
    (docs/17 §8a), so this deletes the seeded session and boots again to prove it.
    """
    from sqlalchemy import create_engine

    from desktop.sidecar import DEMO_QUERY, demo_already_seeded

    async def boot():
        app = create_sidecar_app(data_dir=tmp_path, token=TOKEN, fake=True)
        async with app.router.lifespan_context(app):
            await asyncio.sleep(0.5)  # let the seeded run finish; measured well under this

    assert not demo_already_seeded(tmp_path)
    await boot()
    assert demo_already_seeded(tmp_path), "the marker is what stops a re-seed"

    engine = create_engine(f"sqlite:///{tmp_path / 'desktop.sqlite'}")
    with engine.connect() as conn:
        rows = conn.exec_driver_sql(
            "SELECT demo, status FROM sessions WHERE prompt = ?", (DEMO_QUERY,)
        ).fetchall()
    assert len(rows) == 1, "exactly one demo on first launch"
    assert rows[0][0] == 1, "the seeded session must be marked as a demo"

    # A second launch must not add another.
    await boot()
    with engine.connect() as conn:
        assert (
            conn.exec_driver_sql(
                "SELECT COUNT(*) FROM sessions WHERE prompt = ?", (DEMO_QUERY,)
            ).scalar()
            == 1
        )

    # Deleting it must stick — this is the case the marker exists for.
    with engine.begin() as conn:
        conn.exec_driver_sql("DELETE FROM sessions WHERE prompt = ?", (DEMO_QUERY,))
    await boot()
    with engine.connect() as conn:
        assert (
            conn.exec_driver_sql(
                "SELECT COUNT(*) FROM sessions WHERE prompt = ?", (DEMO_QUERY,)
            ).scalar()
            == 0
        ), "a deleted demo must not come back"
    engine.dispose()


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
    # The report body is exported verbatim, with a "Models used" footer appended after
    # it — never merged in, since the body is what a human approved.
    assert export.text.startswith(detail["final_report"])
    assert "## Models used" in export.text

    # Desktop PDF is WebView print-to-PDF by design (docs/13 §7): no WeasyPrint here.
    pdf = await sidecar.get(f"/api/v1/research/{session_id}/export.pdf", headers=_auth())
    assert pdf.status_code == 501


async def test_run_persists_the_model_routing_it_actually_dialled(sidecar):
    """`_drive_session` resolves a `RunConfig` but never wrote it back onto the session
    row, so `model_routing` stayed null on every desktop session forever — the server's
    `pipeline_runner._run_config_for` does this snapshot and the sidecar never grew the
    equivalent line (docs/07 §2, "truthful per-agent model attribution")."""
    start = await sidecar.post(
        "/api/v1/research",
        headers=_auth(),
        json={"query": "What is retrieval-augmented generation?", "depth": "fast"},
    )
    session_id = start.json()["session_id"]

    detail = await _until(sidecar, session_id, "AWAITING_APPROVAL")

    assert detail["model_routing"], (
        "resolved routing must be persisted before disclosure is possible"
    )
    assert set(detail["model_routing"]) == {"planner", "executor", "critic", "synthesizer", "chat"}
    # Pinned by conftest's MODEL_* env vars — proves the sidecar actually read the
    # configured routing rather than emitting a hardcoded placeholder.
    assert detail["model_routing"]["planner"] == "google:gemini-2.5-flash"


async def test_a_per_run_model_override_is_honored_not_silently_dropped(sidecar):
    """`start_research` accepted `payload.model_routing` and then never used it — the
    request schema promises "omit to use your saved settings", but a request that did
    NOT omit it ran on the saved settings anyway. Same bug class as `corpus_mode`/`demo`
    a few lines above: accepted by the schema, dropped on the floor."""
    # Distinct from conftest's pinned MODEL_* env (all "google:gemini-2.5-flash") —
    # otherwise a dropped override and an honored one would be indistinguishable.
    override = {
        r: "anthropic:claude-haiku-4-5"
        for r in ("planner", "executor", "critic", "synthesizer", "chat")
    }
    start = await sidecar.post(
        "/api/v1/research",
        headers=_auth(),
        json={
            "query": "What is retrieval-augmented generation?",
            "depth": "fast",
            "model_routing": override,
        },
    )
    assert start.status_code == 202
    session_id = start.json()["session_id"]

    detail = await _until(sidecar, session_id, "AWAITING_APPROVAL")
    assert detail["model_routing"] == override

    # An unroutable model is rejected before a session exists, same contract as the
    # server (`app/api/v1/research.py`).
    bad = await sidecar.post(
        "/api/v1/research",
        headers=_auth(),
        json={
            "query": "What is retrieval-augmented generation?",
            "depth": "fast",
            "model_routing": {"planner": "nope"},
        },
    )
    assert bad.status_code == 422


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
