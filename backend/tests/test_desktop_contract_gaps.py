"""
The desktop contract gaps M1 found, closed and pinned (M1.5).

M1's parity harness proved seven paths the desktop build calls and the sidecar did not
serve. Every one rendered as a working control and answered 404: the Stop button, the whole
Corpus page (list, status, upload, delete, preview download), and the Settings usage panel.

`test_host_parity.py` asserts the *routes exist*. These assert they **behave** — that the
canonical per-project corpus path reaches the same flat store the desktop has always had,
that cancel does what the server's cancel does, and that usage reports real numbers rather
than a placebo zero.

The design decision worth restating: the per-project path is the canonical product contract
and both hosts serve it. The desktop's one-`corpus.sqlite`-per-app storage stays exactly as
it was — it is now an implementation detail behind a shared contract instead of a shape the
frontend had to know about. No `isDesktop` branch was added to close any of these.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from app.models.session import SessionStatus
from desktop.sidecar import create_sidecar_app

TOKEN = "test-gaps-token"

#: Every corpus assertion here uses a text document. A PDF fixture would exercise the one
#: narrow *exception* in `download_headers` (inline render, needed by in-place preview);
#: `txt` exercises the rule itself — an uploaded document must not render in this origin —
#: which is the half that matters for security.
TEXT_DOC = (
    b"Retrieval quality. Recall improved by 12 points on the internal benchmark, and "
    b"grounded answers beat ungrounded ones on factual questions."
)


@pytest.fixture
async def sidecar(tmp_path):
    app = create_sidecar_app(data_dir=tmp_path, token=TOKEN, fake=True)
    async with app.router.lifespan_context(app):
        # The corpus store is built during lifespan with the Ollama-backed embedder the
        # desktop app ships. Nothing is listening in CI, so swap in the deterministic fake
        # — the same helper `test_desktop_sidecar` uses. The store is what is under test,
        # not the embedder.
        from tests.test_corpus_store import FakeEmbeddings

        app.state.sidecar["corpus"]._embedder = FakeEmbeddings()  # noqa: SLF001
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:9") as client:
            yield client


def _auth() -> dict:
    return {"Authorization": f"Bearer {TOKEN}"}


async def _project_id(client: httpx.AsyncClient) -> str:
    resp = await client.get("/api/v1/projects", headers=_auth())
    assert resp.status_code == 200
    return resp.json()["projects"][0]["id"]


UNKNOWN_PROJECT = "00000000-0000-0000-0000-0000000000ff"


# ── Gap 1: cancel ─────────────────────────────────────────────────────────────────


@pytest.fixture
def held_run(monkeypatch):
    """Hold the pipeline open so a run stays cancellable for the length of a test.

    Cancel is only valid while a session is PENDING or RUNNING. In fake mode the whole
    pipeline reaches the review gate in about a second, so a test that starts a run and
    then cancels it is racing the pipeline — measured at roughly one failure in eight.
    (With real models the window is minutes, so this is a test artefact, not a product
    limitation.)

    `_drive_session` resolves `run` as a module global at call time, so replacing it here
    makes the run hang until the test finishes. The route under test is untouched.
    """
    import desktop.sidecar as sidecar_module

    async def _never_finishes(**kwargs):
        await asyncio.sleep(3600)

    monkeypatch.setattr(sidecar_module, "run", _never_finishes)
    return _never_finishes


async def test_cancel_stops_a_running_session(sidecar, held_run):
    start = await sidecar.post(
        "/api/v1/research",
        headers=_auth(),
        json={"query": "What is retrieval-augmented generation?", "depth": "fast"},
    )
    assert start.status_code == 202
    session_id = start.json()["session_id"]

    resp = await sidecar.post(f"/api/v1/research/{session_id}/cancel", headers=_auth())
    assert resp.status_code == 200
    assert resp.json()["status"] == SessionStatus.FAILED.value

    detail = await sidecar.get(f"/api/v1/research/{session_id}", headers=_auth())
    assert detail.json()["error_message"] == "Research stopped by user."


async def test_cancel_refuses_a_session_that_is_not_running(sidecar):
    """Mirrors the server's 400 rather than inventing a different code."""
    start = await sidecar.post(
        "/api/v1/research",
        headers=_auth(),
        json={"query": "What is retrieval-augmented generation?", "depth": "fast"},
    )
    session_id = start.json()["session_id"]

    deadline = asyncio.get_event_loop().time() + 30
    while asyncio.get_event_loop().time() < deadline:
        status = (await sidecar.get(f"/api/v1/research/{session_id}", headers=_auth())).json()[
            "status"
        ]
        if status == SessionStatus.AWAITING_APPROVAL.value:
            break
        await asyncio.sleep(0.2)

    resp = await sidecar.post(f"/api/v1/research/{session_id}/cancel", headers=_auth())
    assert resp.status_code == 400
    assert "AWAITING_APPROVAL" in resp.json()["detail"]


async def test_cancel_writes_a_terminal_event_to_the_log(sidecar, held_run):
    """The monitor is driven by the event stream, so a silent cancel leaves it spinning.

    `_TERMINAL_EVENTS` includes FAILED, so this is what lets an open stream close.
    """
    start = await sidecar.post(
        "/api/v1/research",
        headers=_auth(),
        json={"query": "What is retrieval-augmented generation?", "depth": "fast"},
    )
    session_id = start.json()["session_id"]
    cancelled = await sidecar.post(f"/api/v1/research/{session_id}/cancel", headers=_auth())
    assert cancelled.status_code == 200, cancelled.text

    stream = await sidecar.get(
        f"/api/v1/research/{session_id}/stream?access_token={TOKEN}",
        headers={"Accept": "text/event-stream"},
    )
    assert stream.status_code == 200
    assert "FAILED" in stream.text


async def test_cancel_404s_for_an_unknown_session(sidecar):
    resp = await sidecar.post(
        "/api/v1/research/00000000-0000-0000-0000-000000000000/cancel", headers=_auth()
    )
    assert resp.status_code == 404


# ── Gaps 2–5 + download: the canonical per-project corpus contract ────────────────


async def test_per_project_corpus_paths_reach_the_flat_store(sidecar):
    """The whole point of the alias: one client contract, the desktop's own storage.

    Uploading through the canonical per-project path must be visible through the flat
    route the desktop has always served, because they are the same corpus.
    """
    pid = await _project_id(sidecar)

    upload = await sidecar.post(
        f"/api/v1/projects/{pid}/corpus/documents",
        headers=_auth(),
        files={"file": ("notes.txt", TEXT_DOC, "text/plain")},
    )
    assert upload.status_code == 201, upload.text
    doc_id = upload.json()["doc_id"]

    via_project = await sidecar.get(f"/api/v1/projects/{pid}/corpus/documents", headers=_auth())
    via_flat = await sidecar.get("/api/v1/corpus/documents", headers=_auth())
    assert via_project.status_code == 200
    assert via_project.json() == via_flat.json()
    assert any(d["id"] == doc_id for d in via_project.json()["documents"])


async def test_per_project_corpus_status_matches_the_flat_one(sidecar):
    pid = await _project_id(sidecar)
    await sidecar.post(
        f"/api/v1/projects/{pid}/corpus/documents",
        headers=_auth(),
        files={"file": ("notes.txt", TEXT_DOC, "text/plain")},
    )

    via_project = await sidecar.get(f"/api/v1/projects/{pid}/corpus/status", headers=_auth())
    via_flat = await sidecar.get("/api/v1/corpus/status", headers=_auth())
    assert via_project.status_code == 200
    assert via_project.json() == via_flat.json()
    # `corpus_only` is desktop state and must survive the alias, or the Corpus page's
    # airgap toggle would read as off while the next run is airgapped.
    assert "corpus_only" in via_project.json()


async def test_upload_accepts_the_multipart_body_the_browser_sends(sidecar):
    """The encoding half of the gap, which the path fix alone would not have closed.

    The sidecar's flat route takes raw bytes with the name in the query string. The
    frontend sends a `FormData`. Matching the server's `UploadFile` signature is what
    makes one client code path work against both hosts.
    """
    pid = await _project_id(sidecar)
    resp = await sidecar.post(
        f"/api/v1/projects/{pid}/corpus/documents",
        headers=_auth(),
        files={"file": ("notes.txt", TEXT_DOC, "text/plain")},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["filename"] == "notes.txt"


async def test_upload_rejects_an_empty_document(sidecar):
    pid = await _project_id(sidecar)
    resp = await sidecar.post(
        f"/api/v1/projects/{pid}/corpus/documents",
        headers=_auth(),
        files={"file": ("empty.txt", b"", "text/plain")},
    )
    assert resp.status_code == 422


async def test_delete_through_the_canonical_path_removes_the_document(sidecar):
    pid = await _project_id(sidecar)
    upload = await sidecar.post(
        f"/api/v1/projects/{pid}/corpus/documents",
        headers=_auth(),
        files={"file": ("notes.txt", TEXT_DOC, "text/plain")},
    )
    doc_id = upload.json()["doc_id"]

    delete = await sidecar.delete(
        f"/api/v1/projects/{pid}/corpus/documents/{doc_id}", headers=_auth()
    )
    assert delete.status_code == 204

    listed = await sidecar.get("/api/v1/corpus/documents", headers=_auth())
    assert not any(d["id"] == doc_id for d in listed.json()["documents"])


async def test_delete_404s_for_an_unknown_document(sidecar):
    pid = await _project_id(sidecar)
    resp = await sidecar.delete(
        f"/api/v1/projects/{pid}/corpus/documents/does-not-exist", headers=_auth()
    )
    assert resp.status_code == 404


async def test_download_returns_the_original_bytes(sidecar):
    """The seventh gap — the one M1 misfiled as an intentional difference.

    `documentUrl()` builds this path for the Corpus page and the report preview drawer, so
    every citation preview on desktop was a 404.
    """
    pid = await _project_id(sidecar)
    upload = await sidecar.post(
        f"/api/v1/projects/{pid}/corpus/documents",
        headers=_auth(),
        files={"file": ("notes.txt", TEXT_DOC, "text/plain")},
    )
    doc_id = upload.json()["doc_id"]

    resp = await sidecar.get(
        f"/api/v1/projects/{pid}/corpus/documents/{doc_id}/download", headers=_auth()
    )
    assert resp.status_code == 200
    assert resp.content == TEXT_DOC


async def test_download_carries_the_servers_own_no_render_headers(sidecar):
    """`download_headers` is imported from the server, not restated.

    An uploaded document must not render in this origin; PDF is the one narrow exception
    that in-place preview needs. Duplicating that policy per host is how one copy ends up
    permissive.
    """
    from app.api.v1.corpus import download_headers

    pid = await _project_id(sidecar)
    upload = await sidecar.post(
        f"/api/v1/projects/{pid}/corpus/documents",
        headers=_auth(),
        files={"file": ("notes.txt", TEXT_DOC, "text/plain")},
    )
    doc_id = upload.json()["doc_id"]

    resp = await sidecar.get(
        f"/api/v1/projects/{pid}/corpus/documents/{doc_id}/download", headers=_auth()
    )
    expected = download_headers("txt", "notes.txt")
    for header, value in expected.items():
        assert resp.headers.get(header) == value, f"{header} diverged from the server's policy"


async def test_download_404s_for_an_unknown_document(sidecar):
    pid = await _project_id(sidecar)
    resp = await sidecar.get(
        f"/api/v1/projects/{pid}/corpus/documents/nope/download", headers=_auth()
    )
    assert resp.status_code == 404


@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", "/corpus/documents"),
        ("GET", "/corpus/status"),
        ("POST", "/corpus/documents"),
    ],
)
async def test_corpus_aliases_404_on_a_project_that_is_not_yours(sidecar, method, path):
    """`_resolve_project` still runs, so the authorization boundary is unchanged.

    The project id does not select a store here — there is only one — but answering for a
    project that does not exist would be a different contract from the server's, and a
    client cannot tell the difference between "no such project" and "empty corpus" if the
    alias shrugs.
    """
    resp = await sidecar.request(
        method,
        f"/api/v1/projects/{UNKNOWN_PROJECT}{path.replace('/corpus', '/corpus')}".replace(
            "/api/v1/projects/", "/api/v1/projects/"
        ),
        headers=_auth(),
        files={"file": ("x.txt", b"x", "text/plain")} if method == "POST" else None,
    )
    assert resp.status_code == 404


# ── Gap 6: usage ──────────────────────────────────────────────────────────────────


async def test_usage_reports_real_numbers_not_a_placebo(sidecar):
    """Served rather than hidden: the usage half is meaningful for a BYOK local user.

    The *limit* half is not — a single local user paying their own provider bill has no
    monthly ceiling — and the response says so honestly rather than inventing one.
    """
    resp = await sidecar.get("/api/v1/auth/me/usage", headers=_auth())
    assert resp.status_code == 200
    body = resp.json()

    for window in ("month", "week", "last_session"):
        assert window in body, f"{window} missing from the usage response"

    assert body["monthly_token_limit"] == 0, "no ceiling applies to one local user"
    assert body["limit_remaining"] is None, "unlimited must be null, not a number"
    assert body["limit_reached"] is False


async def test_usage_counts_a_completed_run(sidecar):
    """Not a hardcoded zero: a run that spent tokens has to show up.

    Fake mode still reports token counts, which is what makes this checkable without a
    provider — and what makes a regression to `return 0` visible.
    """
    before = (await sidecar.get("/api/v1/auth/me/usage", headers=_auth())).json()

    start = await sidecar.post(
        "/api/v1/research",
        headers=_auth(),
        json={"query": "What is retrieval-augmented generation?", "depth": "fast"},
    )
    session_id = start.json()["session_id"]
    deadline = asyncio.get_event_loop().time() + 30
    while asyncio.get_event_loop().time() < deadline:
        status = (await sidecar.get(f"/api/v1/research/{session_id}", headers=_auth())).json()[
            "status"
        ]
        if status == SessionStatus.AWAITING_APPROVAL.value:
            break
        await asyncio.sleep(0.2)
    await sidecar.post(
        f"/api/v1/research/{session_id}/approve", headers=_auth(), json={"approved": True}
    )
    while asyncio.get_event_loop().time() < deadline:
        status = (await sidecar.get(f"/api/v1/research/{session_id}", headers=_auth())).json()[
            "status"
        ]
        if status == SessionStatus.COMPLETED.value:
            break
        await asyncio.sleep(0.2)

    after = (await sidecar.get("/api/v1/auth/me/usage", headers=_auth())).json()
    assert after["month"]["tokens_total"] >= before["month"]["tokens_total"]
    assert after["last_session"]["tokens_total"] > 0, "a completed run reported no tokens at all"
