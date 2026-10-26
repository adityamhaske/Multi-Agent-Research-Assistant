"""
Folders in the corpus (RFC V3.1 §7.1, PR-14; AC-18, AC-22).

The store is exercised directly on a real SQLite file, and the routes through the desktop
sidecar's real HTTP surface — which delegates to the server's handlers, so the contract is
one function on both hosts.
"""

from __future__ import annotations

import httpx
import pytest

from app.errors import Invalid
from app.services.corpus_ingest import folder_components, ingest_document
from app.services.corpus_selection import freeze_selection
from desktop.sidecar import create_sidecar_app
from research_engine.corpus import CorpusStore
from tests.dataflow.test_corpus_store import SOLAR_TEXT, VENTS_TEXT, FakeEmbeddings

TOKEN = "folders-token"


@pytest.fixture
async def store(tmp_path) -> CorpusStore:
    return CorpusStore(tmp_path / "c.sqlite", FakeEmbeddings())


# ── Paths ─────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("path", "folders"),
    [
        ("Thesis/Ch2/data.csv", ["Thesis", "Ch2"]),
        ("Thesis\\Ch2\\data.csv", ["Thesis", "Ch2"]),
        ("data.csv", []),
        (None, []),
    ],
)
def test_a_relative_path_names_folders(path, folders):
    assert folder_components(path) == folders


@pytest.mark.parametrize(
    "path", ["../etc/passwd", "Thesis/../../x.csv", "Thesis//x.csv", "./x.csv", "a/\0/x.csv"]
)
def test_a_path_that_could_climb_or_alias_is_refused(path):
    with pytest.raises(Invalid):
        folder_components(path)


def test_an_absurdly_deep_path_is_refused():
    with pytest.raises(Invalid, match="levels deep"):
        folder_components("/".join(["d"] * 40) + "/x.csv")


# ── Upload into folders ───────────────────────────────────────────────────────────


async def test_a_folder_upload_files_documents_and_creates_folders(store):
    await ingest_document(
        store, "solar.txt", SOLAR_TEXT.encode(), relative_path="Thesis/Ch1/solar.txt"
    )
    await ingest_document(
        store, "vents.txt", VENTS_TEXT.encode(), relative_path="Thesis/Ch2/vents.txt"
    )

    names = {f["name"]: f for f in await store.folders()}
    assert set(names) == {"Thesis", "Ch1", "Ch2"}
    assert names["Ch1"]["parent_id"] == names["Thesis"]["id"]
    assert len(await store.memberships()) == 2


async def test_the_same_file_in_two_folders_is_one_document_two_memberships(store):
    first = await ingest_document(
        store, "solar.txt", SOLAR_TEXT.encode(), relative_path="A/solar.txt"
    )
    again = await ingest_document(
        store, "solar.txt", SOLAR_TEXT.encode(), relative_path="B/solar.txt"
    )

    assert first.id == again.id
    assert len(await store.documents()) == 1
    assert {m["folder_id"] for m in await store.memberships()} == {
        f["id"] for f in await store.folders()
    }


# ── Folder operations ─────────────────────────────────────────────────────────────


async def test_rename_and_move_keep_ids_and_refuse_a_cycle(store):
    parent = await store.create_folder("Thesis")
    child = await store.create_folder("Ch1", parent)

    await store.update_folder(child, name="Chapter 1")
    await store.update_folder(child, parent_id=None)
    folders = {f["id"]: f for f in await store.folders()}
    assert folders[child]["name"] == "Chapter 1" and folders[child]["parent_id"] is None

    await store.update_folder(child, parent_id=parent)
    with pytest.raises(ValueError, match="into itself"):
        await store.update_folder(parent, parent_id=child)


async def test_deleting_a_folder_deletes_only_documents_filed_nowhere_else(store):
    only = await ingest_document(
        store, "solar.txt", SOLAR_TEXT.encode(), relative_path="Old/solar.txt"
    )
    both = await ingest_document(
        store, "vents.txt", VENTS_TEXT.encode(), relative_path="Old/vents.txt"
    )
    await ingest_document(store, "vents.txt", VENTS_TEXT.encode(), relative_path="Keep/vents.txt")
    loose = await store.ingest("loose.txt", b"A document never filed in any folder at all.")

    old = next(f["id"] for f in await store.folders() if f["name"] == "Old")
    result = await store.delete_folder(old)

    remaining = {d["id"] for d in await store.documents()}
    assert only.id not in remaining, "filed only in the deleted folder"
    assert both.id in remaining, "still filed in another folder"
    assert loose.doc_id in remaining, "never in a folder, never touched"
    assert result["documents_deleted"] == 1


# ── Selecting a folder ────────────────────────────────────────────────────────────


async def test_a_folder_selection_includes_its_subfolders_resolved_now(store):
    await ingest_document(
        store, "solar.txt", SOLAR_TEXT.encode(), relative_path="Thesis/Ch1/solar.txt"
    )
    await ingest_document(
        store, "vents.txt", VENTS_TEXT.encode(), relative_path="Elsewhere/vents.txt"
    )
    thesis = next(f["id"] for f in await store.folders() if f["name"] == "Thesis")

    frozen = await freeze_selection(store, folder_ids=[thesis], doc_keys=[], whole_corpus=False)

    assert [i["filename"] for i in frozen["resolved"]] == ["solar.txt"]


# ── Both hosts, one contract ──────────────────────────────────────────────────────


async def test_folder_routes_work_through_the_desktop_host(tmp_path):
    app = create_sidecar_app(data_dir=tmp_path, token=TOKEN, fake=True)
    async with app.router.lifespan_context(app):
        app.state.sidecar["corpus"].embedder = FakeEmbeddings()
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:9") as client:
            auth = {"Authorization": f"Bearer {TOKEN}"}
            pid = (await client.get("/api/v1/projects", headers=auth)).json()["projects"][0]["id"]
            base = f"/api/v1/projects/{pid}/corpus"

            up = await client.post(
                f"{base}/documents",
                headers=auth,
                files={"file": ("solar.txt", SOLAR_TEXT.encode(), "text/plain")},
                data={"relative_path": "Thesis/solar.txt"},
            )
            assert up.status_code == 201, up.text
            bad = await client.post(
                f"{base}/documents",
                headers=auth,
                files={"file": ("x.txt", b"some text here", "text/plain")},
                data={"relative_path": "../x.txt"},
            )
            assert bad.status_code == 400

            tree = (await client.get(f"{base}/tree", headers=auth)).json()
            assert [f["name"] for f in tree["folders"]] == ["Thesis"]
            assert len(tree["memberships"]) == 1

            made = await client.post(f"{base}/folders", headers=auth, json={"name": "Notes"})
            assert made.status_code == 201
            renamed = await client.patch(
                f"{base}/folders/{made.json()['id']}", headers=auth, json={"name": "Reading"}
            )
            assert renamed.json()["name"] == "Reading"
            gone = await client.delete(f"{base}/folders/{tree['folders'][0]['id']}", headers=auth)
            assert gone.status_code == 200 and gone.json()["documents_deleted"] == 1
            missing = await client.delete(f"{base}/folders/no-such-folder", headers=auth)
            assert missing.status_code == 404


async def test_the_extracted_text_route_serves_what_citations_quote(tmp_path):
    app = create_sidecar_app(data_dir=tmp_path, token=TOKEN, fake=True)
    async with app.router.lifespan_context(app):
        app.state.sidecar["corpus"].embedder = FakeEmbeddings()
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:9") as client:
            auth = {"Authorization": f"Bearer {TOKEN}"}
            pid = (await client.get("/api/v1/projects", headers=auth)).json()["projects"][0]["id"]
            base = f"/api/v1/projects/{pid}/corpus"
            up = await client.post(
                f"{base}/documents",
                headers=auth,
                files={"file": ("t.csv", b"Name,Year\nNorth,2021\n", "text/csv")},
            )
            body = (
                await client.get(f"{base}/documents/{up.json()['id']}/text", headers=auth)
            ).json()
            assert body["text"] == "Row 2 — Name: North; Year: 2021"
            assert body["extraction_mode"] == "linearized"
            assert body["segments"] == [[0, "row 2"]]
            missing = await client.get(f"{base}/documents/nope/text", headers=auth)
            assert missing.status_code == 404
