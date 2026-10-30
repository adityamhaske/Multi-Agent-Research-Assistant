"""
Renaming, moving and deleting a corpus folder, on both hosts (RFC V3.1 §7.1).

The Corpus page states what a delete will remove before sending it
(`frontend/lib/corpusTree.ts::folderDeletion`) and then reports the server's own count. These
tests drive the routes it calls through both hosts' real stores and check the count is the
one the page promised: the subfolders, and the files filed nowhere else — a file also in
another folder only loses this membership.
"""

from __future__ import annotations

import pytest

from tests.parity.drivers import Driver, desktop_driver, server_driver
from tests.security.test_corpus_project_isolation import _project, _upload

HOSTS = {"server": server_driver, "desktop": desktop_driver}


@pytest.fixture(params=sorted(HOSTS))
async def host(request, tmp_path):
    async with HOSTS[request.param](tmp_path / request.param) as driver:
        yield driver


async def _folders(driver: Driver, pid: str) -> dict[str, dict]:
    tree = (await driver.request("GET", f"/projects/{pid}/corpus/tree")).json()
    return {f["name"]: f for f in tree["folders"]}


async def test_rename_move_and_delete_with_the_count_the_page_states(host):
    pid = await _project(host, "P")
    await _upload(host, pid, "a.txt", b"Only in chapter one.", "Thesis/Ch1/a.txt")
    shared = b"Filed in two places."
    await _upload(host, pid, "b.txt", shared, "Thesis/b.txt")
    await _upload(host, pid, "b.txt", shared, "Notes/b.txt")
    folders = await _folders(host, pid)

    renamed = await host.request(
        "PATCH",
        f"/projects/{pid}/corpus/folders/{folders['Notes']['id']}",
        json={"name": "Reading"},
    )
    assert renamed.status_code == 200, renamed.text
    moved = await host.request(
        "PATCH",
        f"/projects/{pid}/corpus/folders/{folders['Ch1']['id']}",
        json={"parent_id": folders["Notes"]["id"], "move": True},
    )
    assert moved.status_code == 200, moved.text
    after = await _folders(host, pid)
    assert "Reading" in after and "Notes" not in after
    assert after["Ch1"]["parent_id"] == folders["Notes"]["id"]

    # Ch1 now lives under Reading, so Thesis holds only b.txt, which Reading also holds.
    deleted = await host.request(
        "DELETE", f"/projects/{pid}/corpus/folders/{folders['Thesis']['id']}"
    )
    assert deleted.status_code == 200, deleted.text
    assert deleted.json() == {"folders_deleted": 1, "documents_deleted": 0, "versions_deleted": 0}

    deleted = await host.request(
        "DELETE", f"/projects/{pid}/corpus/folders/{folders['Notes']['id']}"
    )
    assert deleted.json()["folders_deleted"] == 2
    assert deleted.json()["documents_deleted"] == 2, "a.txt and b.txt were filed nowhere else"
    listed = (await host.request("GET", f"/projects/{pid}/corpus/documents")).json()
    assert listed == []
