"""
The move off the desktop's pre-3.1 shared corpus (internal/rfcs/V3.1-corpus-scope.md §7.3).

Driven through the sidecar's real lifespan against a real data directory: a populated
`corpus.sqlite` written the way 3.0.x wrote it, then the app started. Failures are injected
at the move's own steps, and every recovery is checked by starting the app again — the
only way a user's data directory is ever recovered.
"""

from __future__ import annotations

import sqlite3

import httpx
import pytest

from desktop import corpus_layout
from desktop.sidecar import create_sidecar_app
from research_engine.corpus import CorpusStore
from tests.dataflow.test_corpus_store import SOLAR_TEXT, VENTS_TEXT, FakeEmbeddings

TOKEN = "legacy-corpus-token"


def _auth() -> dict:
    return {"Authorization": f"Bearer {TOKEN}"}


async def _legacy_store(data_dir) -> list[tuple]:
    """A populated 3.0.x shared store. Returns its `(id, sha256)` rows."""
    store = CorpusStore(data_dir / corpus_layout.LEGACY_FILENAME, FakeEmbeddings())
    await store.ingest("solar.txt", SOLAR_TEXT.encode())
    await store.ingest("vents.txt", VENTS_TEXT.encode())
    with sqlite3.connect(data_dir / corpus_layout.LEGACY_FILENAME) as conn:
        return sorted(conn.execute("SELECT id, sha256 FROM corpus_documents").fetchall())


async def _launch(data_dir):
    """Start the app on `data_dir`, return (projects by name, the corpus warning if any)."""
    app = create_sidecar_app(data_dir=data_dir, token=TOKEN, fake=True)
    async with app.router.lifespan_context(app):
        app.state.sidecar["corpus"].embedder = FakeEmbeddings()
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:9") as client:
            projects = (await client.get("/api/v1/projects", headers=_auth())).json()["projects"]
            by_name = {p["name"]: p for p in projects}
            docs = {}
            for p in projects:
                listed = await client.get(
                    f"/api/v1/projects/{p['id']}/corpus/documents", headers=_auth()
                )
                docs[p["name"]] = sorted(d["id"] for d in listed.json())
        return by_name, docs, app.state.sidecar.get("corpus_warning")


def _rows(path) -> list[tuple]:
    with sqlite3.connect(path) as conn:
        return sorted(conn.execute("SELECT id, sha256 FROM corpus_documents").fetchall())


async def test_the_shared_store_moves_whole_to_one_new_project(tmp_path):
    before = await _legacy_store(tmp_path)

    projects, docs, warning = await _launch(tmp_path)

    assert warning is None
    legacy = projects[corpus_layout.LEGACY_PROJECT_NAME]
    assert "moved here" in (legacy.get("description") or "")
    assert docs[corpus_layout.LEGACY_PROJECT_NAME] == sorted(i for i, _ in before)
    # Nowhere else: the default project starts empty instead of inheriting them.
    assert all(ids == [] for name, ids in docs.items() if name != corpus_layout.LEGACY_PROJECT_NAME)

    moved = tmp_path / "corpus" / f"corpus_{legacy['id']}.sqlite"
    assert _rows(moved) == before, "ids and hashes are preserved exactly"
    assert _rows(tmp_path / corpus_layout.BACKUP_FILENAME) == before, "the backup is kept"
    assert not (tmp_path / corpus_layout.LEGACY_FILENAME).exists(), "the shared store is retired"


async def test_a_second_launch_changes_nothing(tmp_path):
    await _legacy_store(tmp_path)
    first, first_docs, _ = await _launch(tmp_path)
    second, second_docs, _ = await _launch(tmp_path)

    assert set(first) == set(second), "no second legacy project"
    assert first_docs == second_docs


async def test_a_failed_backup_check_keeps_the_shared_store_and_says_why(tmp_path, monkeypatch):
    before = await _legacy_store(tmp_path)

    def refuse(_a, _b):
        raise corpus_layout.MigrationRefused("integrity_check on the copy returned 'corrupt'")

    monkeypatch.setattr(corpus_layout, "verify_copy", refuse)
    projects, docs, warning = await _launch(tmp_path)

    assert warning and "integrity_check" in warning
    assert corpus_layout.LEGACY_PROJECT_NAME not in projects
    assert _rows(tmp_path / corpus_layout.LEGACY_FILENAME) == before, "the live store untouched"
    # The shared layout stays in force, so the documents are still reachable meanwhile.
    assert docs["General"] == sorted(i for i, _ in before)

    monkeypatch.undo()
    projects, docs, warning = await _launch(tmp_path)
    assert warning is None
    assert docs[corpus_layout.LEGACY_PROJECT_NAME] == sorted(i for i, _ in before)


async def test_a_crash_before_the_commit_is_finished_by_the_next_launch(tmp_path, monkeypatch):
    before = await _legacy_store(tmp_path)
    real_set = corpus_layout._set_meta

    async def crash(db, key, value):
        raise RuntimeError("power cut before the commit")

    monkeypatch.setattr(corpus_layout, "_set_meta", crash)
    with pytest.raises(RuntimeError, match="power cut"):
        await _launch(tmp_path)
    # The project store may already be on disk, but the layout is still `shared`.
    assert (tmp_path / corpus_layout.LEGACY_FILENAME).exists()

    monkeypatch.setattr(corpus_layout, "_set_meta", real_set)
    projects, docs, _ = await _launch(tmp_path)
    assert [n for n in projects if n.startswith(corpus_layout.LEGACY_PROJECT_NAME)] == [
        corpus_layout.LEGACY_PROJECT_NAME
    ], "exactly one legacy project, reusing the id fixed before the crash"
    assert docs[corpus_layout.LEGACY_PROJECT_NAME] == sorted(i for i, _ in before)


async def test_a_crash_after_the_commit_retires_the_shared_store_next_launch(tmp_path):
    before = await _legacy_store(tmp_path)
    await _launch(tmp_path)
    # Put a shared store back, as a crash between the commit and step 5 would leave it.
    corpus_layout._backup(
        tmp_path / corpus_layout.BACKUP_FILENAME, tmp_path / corpus_layout.LEGACY_FILENAME
    )

    projects, docs, warning = await _launch(tmp_path)

    assert warning is None
    assert not (tmp_path / corpus_layout.LEGACY_FILENAME).exists()
    assert docs[corpus_layout.LEGACY_PROJECT_NAME] == sorted(i for i, _ in before)


async def test_a_damaged_moved_store_is_rebuilt_from_the_backup(tmp_path):
    before = await _legacy_store(tmp_path)
    projects, _, _ = await _launch(tmp_path)
    moved = (
        tmp_path / "corpus" / f"corpus_{projects[corpus_layout.LEGACY_PROJECT_NAME]['id']}.sqlite"
    )
    moved.unlink()

    _, docs, _ = await _launch(tmp_path)
    assert docs[corpus_layout.LEGACY_PROJECT_NAME] == sorted(i for i, _ in before)


async def test_a_fresh_install_has_no_legacy_project(tmp_path):
    projects, _, warning = await _launch(tmp_path)
    assert corpus_layout.LEGACY_PROJECT_NAME not in projects
    assert warning is None
