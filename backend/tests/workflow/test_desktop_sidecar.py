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
import json

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
    # This sidecar is built with `fake=True`, so the run was scripted and the row records
    # it as a demo — which means the export leads with the demo stamp. It did not used to:
    # `--fake` left `session.demo` false, so a report produced entirely from fixtures
    # exported with nothing to say so. The stamp coming first is the fix, not a regression.
    assert export.text.startswith("> ## ⚠ DEMO — NOT REAL RESEARCH"), export.text[:120]
    # The report body is still exported verbatim below the stamp, with a "Models used"
    # footer after it — never merged in, since the body is what a human approved.
    assert detail["final_report"] in export.text
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


def _mock_probe_transport(handler):
    """Same convention as `tests/test_local_llm.py` and `test_provider_health.py`:
    stub the transport, never `provider_health.probe` itself."""

    class _Client(httpx.AsyncClient):
        def __init__(self, *a, **kw):
            kw["transport"] = httpx.MockTransport(handler)
            super().__init__(*a, **kw)

    return _Client


async def test_provider_test_probes_a_submitted_key_before_storing(sidecar, monkeypatch):
    """`POST /models/providers/test` — contract copy #2 of the server's endpoint
    (docs/07 §2, Phase 2a)."""
    import httpx as httpx_mod

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "bad key"})

    monkeypatch.setattr(httpx_mod, "AsyncClient", _mock_probe_transport(handler))

    resp = await sidecar.post(
        "/api/v1/models/providers/test",
        headers=_auth(),
        json={"provider": "openai", "api_key": "sk-wrong"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["state"] == "degraded"
    assert body["checked_at"]


async def test_provider_health_checks_the_stored_keychain_key(sidecar, monkeypatch):
    """`GET /models/providers/health/{provider}` re-probes what is actually stored —
    404s when nothing is, 200s with the verdict when something is. Keychain access is
    stubbed (same convention as `test_key_delete_forgets_the_keychain_entry`) rather
    than touching a real OS keyring, which a headless test box may not have."""
    import httpx as httpx_mod

    import desktop.sidecar as sc

    missing = await sidecar.get("/api/v1/models/providers/health/openai", headers=_auth())
    assert missing.status_code == 404

    monkeypatch.setattr(sc, "stored_keys", lambda: {"openai": "sk-stored-key"})

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("authorization") == "Bearer sk-stored-key"
        return httpx.Response(200, json={"data": [{"id": "gpt-5"}]})

    monkeypatch.setattr(httpx_mod, "AsyncClient", _mock_probe_transport(handler))

    checked = await sidecar.get("/api/v1/models/providers/health/openai", headers=_auth())
    assert checked.status_code == 200
    body = checked.json()
    assert body["state"] == "ok"
    assert body["model_count"] == 1


# ── One-click local models (docs/07 §2, Phase 2b) ────────────────────────────────


async def test_local_status_reports_install_state(sidecar, monkeypatch):
    """The sidecar had no `/local/status` counterpart to the server's endpoint at
    all — the "Local models" card 404'd on every desktop build."""
    import desktop.sidecar as sc
    from app.services import local_llm

    async def fake_probe(base_url=None):
        return local_llm.LocalLLMStatus(
            configured_base_url="http://localhost:11434/v1",
            reachable=False,
            install_state="not_installed",
            hint="Install Ollama.",
        )

    monkeypatch.setattr(sc.local_llm, "probe", fake_probe)

    resp = await sidecar.get("/api/v1/models/local/status", headers=_auth())
    assert resp.status_code == 200
    assert resp.json()["install_state"] == "not_installed"


async def test_local_start_no_ops_when_already_reachable(sidecar, monkeypatch):
    import desktop.sidecar as sc
    from app.services import local_llm

    async def fake_probe(base_url=None):
        return local_llm.LocalLLMStatus(
            configured_base_url="http://localhost:11434/v1", reachable=True, install_state="running"
        )

    monkeypatch.setattr(sc.local_llm, "probe", fake_probe)

    resp = await sidecar.post("/api/v1/models/local/start", headers=_auth())
    assert resp.status_code == 200
    assert resp.json()["already_running"] is True


async def test_local_start_404s_when_ollama_is_not_installed(sidecar, monkeypatch):
    import desktop.sidecar as sc
    from app.services import local_llm

    async def fake_probe(base_url=None):
        return local_llm.LocalLLMStatus(
            configured_base_url="http://localhost:11434/v1",
            reachable=False,
            install_state="not_installed",
        )

    monkeypatch.setattr(sc.local_llm, "probe", fake_probe)
    monkeypatch.setattr(sc.local_llm, "resolve_binary", lambda: None)

    resp = await sidecar.post("/api/v1/models/local/start", headers=_auth())
    assert resp.status_code == 404


async def test_local_stop_is_a_no_op_when_this_app_never_started_one(sidecar):
    """A server the user started outside the app must never be touched — the process
    handle is only ever set by `/local/start`, and it starts as None."""
    resp = await sidecar.post("/api/v1/models/local/stop", headers=_auth())
    assert resp.status_code == 200
    assert resp.json()["stopped"] is False


async def test_local_pull_streams_newline_delimited_progress(sidecar, monkeypatch):
    import desktop.sidecar as sc
    from app.services import local_llm

    async def fake_pull(model, base_url=None):
        yield local_llm.PullProgress(status="pulling manifest")
        yield local_llm.PullProgress(status="downloading", completed=50, total=100)
        yield local_llm.PullProgress(status="success")

    monkeypatch.setattr(sc.local_llm, "pull", fake_pull)

    resp = await sidecar.post(
        "/api/v1/models/local/pull", headers=_auth(), json={"model": "qwen2.5:14b"}
    )
    assert resp.status_code == 200
    lines = [line for line in resp.text.strip().split("\n") if line]
    statuses = [json.loads(line)["status"] for line in lines]
    assert statuses == ["pulling manifest", "downloading", "success"]


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
    from tests.dataflow.test_corpus_store import FakeEmbeddings

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
    # Same field names as the server's DocumentResponse (app/api/v1/corpus.py) — not
    # `Ingested`'s own doc_id/chunks_written/skipped/reason. See sidecar's
    # `_document_response` for why: nothing here checked the body shape, only the status
    # code, so a wrapped/renamed response looked done while the frontend's typed
    # `CorpusDocument[]` would have read every field as undefined.
    assert body["id"] and body["chunks"] >= 1

    # Same bytes again: deduped to the same id, not doubled.
    again = await sidecar.post(
        "/api/v1/corpus/documents",
        params={"filename": "notes.txt"},
        headers=_auth(),
        content=CORPUS_DOC.encode(),
    )
    assert again.json()["id"] == body["id"]

    docs = await sidecar.get("/api/v1/corpus/documents", headers=_auth())
    assert [d["filename"] for d in docs.json()] == ["notes.txt"]

    # A format we cannot locate quotes in never enters a citation-grade corpus.
    rejected = await sidecar.post(
        "/api/v1/corpus/documents",
        params={"filename": "archive.zip"},
        headers=_auth(),
        content=b"PK\x03\x04",
    )
    # 400, matching the server — see app/services/corpus_ingest.py.
    assert rejected.status_code == 400

    delete = await sidecar.delete(f"/api/v1/corpus/documents/{body['id']}", headers=_auth())
    assert delete.status_code == 204
    gone = await sidecar.delete(f"/api/v1/corpus/documents/{body['id']}", headers=_auth())
    assert gone.status_code == 404


async def test_a_run_asking_for_corpus_mode_actually_runs_in_it(sidecar, tmp_path):
    """The desktop's M10 DoD, now driven by the run rather than by a global switch.

    `corpus_mode` arrives on the request, is persisted onto the session, and has to reach
    `RunConfig` — otherwise it is "a field the schema accepts and the run never reads",
    which `app/schemas/research.py` names as the exact bug this repository records for
    `corpus_mode`. On the desktop it *was* that bug: the row stored the flag and
    `sidecar_run_config` read corpus mode from a JSON file instead, so a run requested as
    airgapped was recorded as airgapped and executed over the open web.
    """
    _install_fake_embedder(sidecar)

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
        json={
            "query": "What does the corpus say about RAG?",
            "depth": "fast",
            "corpus_mode": True,
        },
    )
    assert start.status_code == 202
    detail = await _until(sidecar, start.json()["session_id"], "AWAITING_APPROVAL")

    assert detail["sources"], "corpus evidence must surface as sources"
    for source in detail["sources"]:
        assert source["url"].startswith("corpus://"), source["url"]

    # No global switch, and no file left behind to carry state between runs.
    assert not (tmp_path / "corpus.json").exists()


async def test_a_run_that_did_not_ask_for_corpus_mode_is_not_airgapped(sidecar):
    """The other half, and the one a global flag could not express: two runs in the same
    app, one airgapped and one not. With the switch this was impossible — whichever way it
    was set applied to every run until someone changed it."""
    _install_fake_embedder(sidecar)

    start = await sidecar.post(
        "/api/v1/research",
        headers=_auth(),
        json={"query": "What is retrieval-augmented generation?", "depth": "fast"},
    )
    assert start.status_code == 202
    detail = await _until(sidecar, start.json()["session_id"], "AWAITING_APPROVAL")

    assert detail["sources"], "a normal run still gathers sources"
    assert not any(s["url"].startswith("corpus://") for s in detail["sources"]), (
        "a run that did not ask for corpus mode must not be silently restricted to it"
    )


async def test_a_corpus_mode_run_with_an_empty_corpus_fails_rather_than_using_the_web(sidecar):
    """`docs/25 §Corpus only`: "A run in this mode with no corpus installed fails rather
    than quietly falling back to the web."

    Newly reachable on the desktop: until corpus mode came from the run row, this host had
    no way to request it per run at all. The server enforces the promise by refusing to
    start when the corpus database is absent; here the database always exists (the lifespan
    creates it), so the promise has to hold by the other mechanism — no evidence, no
    report. Which of the two fires is an implementation detail; that the run does not
    silently research the open web is not.
    """
    _install_fake_embedder(sidecar)

    start = await sidecar.post(
        "/api/v1/research",
        headers=_auth(),
        json={"query": "What does the empty corpus say?", "depth": "fast", "corpus_mode": True},
    )
    assert start.status_code == 202
    session_id = start.json()["session_id"]

    detail = await _until(sidecar, session_id, "FAILED")
    assert detail["status"] == "FAILED"
    assert not any((s.get("url") or "").startswith("http") for s in (detail["sources"] or [])), (
        "a corpus-mode run must not fall back to the web, even when the corpus is empty"
    )


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


def test_sidecar_configures_structlog_with_json_output():
    """Parity gap: the server and Celery worker both call `configure_logging()` before
    their first log line (app/main.py, app/workers/celery_app.py) — the sidecar didn't,
    so it ran on structlog's own default `ConsoleRenderer`, which on Windows reaches for
    `colorama` purely to color output nothing ever displays (an unconditional dependency
    of `click`, itself pulled in by `uvicorn[standard]`, so a Windows install gets it
    whether asked for or not — the sidecar's stdout is always a pipe the Tauri shell
    captures, never an interactive terminal). Run in a subprocess, like
    `test_sidecar_import_tree_excludes_weasyprint` above, so this neither depends on nor
    pollutes other tests' structlog global configuration.
    """
    import subprocess
    import sys

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import desktop.sidecar, structlog; "
            "assert structlog.is_configured(), 'sidecar never called configure_logging'; "
            "renderer = structlog.get_config()['processors'][-1]; "
            "assert isinstance(renderer, structlog.processors.JSONRenderer), renderer",
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


def test_shell_alive_probes_a_process_handle_on_windows(monkeypatch):
    """Regression: `os.kill(pid, 0)` is not a portable liveness check. POSIX signal 0
    sends nothing and only runs the existence check — but on Windows, `signal.
    CTRL_C_EVENT == 0`, so the same call is reinterpreted as "deliver Ctrl+C to this
    console process group" via `GenerateConsoleCtrlEvent`. That fails with `WinError 87`
    for any pid that is not a console process-group leader — true of an ordinary
    launcher pid — and was observed to surface as an uncatchable `SystemError` rather
    than an `OSError`, crashing the watchdog thread `test_shell_watchdog_predicate`
    covers on POSIX. `shell_alive` now branches on platform instead; this drives its
    Windows branch without a Windows box by faking `ctypes.windll.kernel32`.
    """
    import ctypes
    import sys

    from desktop.sidecar import shell_alive

    monkeypatch.setattr(sys, "platform", "win32")

    class _FakeKernel32:
        def __init__(self, opens_ok: bool, handle: int = 99):
            self._opens_ok = opens_ok
            self._handle = handle
            self.closed: list[int] = []

        def OpenProcess(self, access, inherit_handle, pid):
            return self._handle if self._opens_ok else 0

        def CloseHandle(self, handle):
            self.closed.append(handle)

    class _FakeWinDLL:
        def __init__(self, kernel32: _FakeKernel32):
            self.kernel32 = kernel32

    live = _FakeKernel32(opens_ok=True)
    monkeypatch.setattr(ctypes, "windll", _FakeWinDLL(live), raising=False)
    assert shell_alive(4242) is True
    assert live.closed == [99]  # the probe handle must not leak

    gone = _FakeKernel32(opens_ok=False)
    monkeypatch.setattr(ctypes, "windll", _FakeWinDLL(gone), raising=False)
    assert shell_alive(4242) is False


async def test_catalog_presets_reflect_what_is_actually_installed(sidecar, monkeypatch):
    """The server's `GET /models` swaps the static `ollama` preset for one built from
    the models this machine actually has (`_ollama_presets_from_installed`) — a picker
    that offers a family the operator never pulled 404s on the first planner call. The
    desktop's own catalog route never called that helper at all, so choosing "Local" on
    a desktop with, say, only `qwen2.5:7b` installed would still route to whatever
    static tag `catalog.PRESETS["ollama"]` names, which is exactly the failure the
    helper exists to prevent — just never wired in on this host.
    """
    import desktop.sidecar as sc
    from app.services import local_llm

    async def fake_probe(base_url=None):  # noqa: ARG001
        return local_llm.LocalLLMStatus(
            configured_base_url="http://localhost:11434/v1",
            reachable=True,
            models=[
                local_llm.LocalModel(
                    name="qwen2.5:7b",
                    route="ollama:qwen2.5:7b",
                    in_catalog=False,
                    params_b=7.0,
                    supports_tools=True,
                )
            ],
        )

    monkeypatch.setattr(sc.local_llm, "probe", fake_probe)

    resp = await sidecar.get("/api/v1/models", headers=_auth())
    assert resp.status_code == 200
    ollama_preset = resp.json()["presets"]["ollama"]
    assert ollama_preset["fast"]["planner"] == "ollama:qwen2.5:7b", (
        "the desktop catalog ignored the installed model and kept the static preset: "
        f"{ollama_preset}"
    )


async def test_deployment_routing_stays_the_baseline_after_a_saved_preference(sidecar):
    """`deployment_routing` and `effective_routing` answer different questions —
    "what does this deployment default to" versus "what will the next run actually
    dial" — and a settings page that wants to show "your choice vs. the baseline" needs
    them to stay different after a preference is saved. The desktop's catalog route
    built both from the same `_effective_with(routing)` call, so the moment a user
    saved a routing preference, `deployment_routing` silently became a mirror of their
    own choice instead of the env/static baseline `model_routing.deployment_default()`
    reports on the server.

    Deliberately not `google:gemini-2.5-flash` for every role: `conftest.py` pins
    `MODEL_*` to exactly that for the whole suite, which would make this pass by
    accident even against the old, collapsing implementation.
    """
    routing = {
        r: "anthropic:claude-haiku-4-5"
        for r in ("planner", "executor", "critic", "synthesizer", "chat")
    }
    put = await sidecar.put("/api/v1/models/routing", headers=_auth(), json={"routing": routing})
    assert put.status_code == 200

    models = await sidecar.get("/api/v1/models", headers=_auth())
    body = models.json()
    assert body["effective_routing"] == routing
    assert body["deployment_routing"] != routing, (
        "deployment_routing should stay the baseline, not mirror the saved preference: "
        f"{body['deployment_routing']}"
    )
