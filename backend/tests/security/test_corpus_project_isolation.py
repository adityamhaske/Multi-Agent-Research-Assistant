"""
Project A's documents are unreachable from project B, on both hosts (RFC V3.1 §13, AC-1, AC-2).

Release blocker 1 (internal/rfcs/V3.1-corpus-scope.md §14.2): any cross-project access, on
either host or in any route, holds 3.1.0. So this drives every corpus surface a client can
name: list, tree, status, extracted text (what the citation preview renders), download (what
the file preview opens), delete, folder rename and delete, selection by id, and a corpus
run's citations. It does this through both hosts' real routes, stores and run drivers, via
the parity drivers (`tests/parity/drivers.py`). Only the embedder is a fake there, and it is
a port, not the code under test.

The desktop half used to be the bug: before 3.1 every desktop project shared one store, and
`test_desktop_contract_gaps` once pinned that sharing as correct.
"""

from __future__ import annotations

import asyncio

import pytest

from app.services.corpus_selection import document_id_of
from tests.parity.drivers import Driver, desktop_driver, server_driver

# Both documents answer the scripted planner's tasks (`research_engine.fakes`: what
# retrieval-augmented generation is, and when it beats fine-tuning), A's more fully than B's,
# so a leak would have something to retrieve.
A_TEXT = (
    b"Project A. Retrieval-augmented generation grounds answers in retrieved passages; "
    b"retrieval beats fine-tuning when the facts change faster than a model can be retrained."
)
B_TEXT = b"Project B. Retrieval-augmented generation retrieves passages before answering."


HOSTS = {"server": server_driver, "desktop": desktop_driver}


@pytest.fixture(params=sorted(HOSTS))
async def host(request, tmp_path):
    async with HOSTS[request.param](tmp_path / request.param) as driver:
        yield driver


async def _project(driver: Driver, name: str) -> str:
    resp = await driver.request("POST", "/projects", json={"name": name})
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _upload(driver: Driver, pid: str, name: str, body: bytes, path: str) -> dict:
    resp = await driver.request(
        "POST",
        f"/projects/{pid}/corpus/documents",
        files={"file": (name, body, "text/plain")},
        data={"relative_path": path},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


@pytest.fixture
async def two_projects(host):
    a, b = await _project(host, "A"), await _project(host, "B")
    a_doc = await _upload(host, a, "solar.txt", A_TEXT, "Thesis/solar.txt")
    b_doc = await _upload(host, b, "vents.txt", B_TEXT, "Notes/vents.txt")
    tree = (await host.request("GET", f"/projects/{a}/corpus/tree")).json()
    assert tree["folders"], "the folder upload created A's folder"
    return {"a": a, "b": b, "a_doc": a_doc, "b_doc": b_doc, "a_folder": tree["folders"][0]}


async def test_b_lists_and_counts_only_its_own_documents(host, two_projects):
    a_id, b = two_projects["a_doc"]["id"], two_projects["b"]

    listed = (await host.request("GET", f"/projects/{b}/corpus/documents")).json()
    assert [d["id"] for d in listed] == [two_projects["b_doc"]["id"]]

    tree = (await host.request("GET", f"/projects/{b}/corpus/tree")).json()
    assert a_id not in {d["id"] for d in tree["documents"]}
    assert two_projects["a_folder"]["id"] not in {f["id"] for f in tree["folders"]}

    status = (await host.request("GET", f"/projects/{b}/corpus/status")).json()
    assert status["documents"] == 1


@pytest.mark.parametrize(
    "method,suffix",
    [
        ("GET", "/text"),  # the citation preview
        ("GET", "/download"),  # the file preview and the download link
        ("DELETE", ""),
    ],
)
async def test_b_cannot_reach_a_document_of_a_by_id(host, two_projects, method, suffix):
    a, b, a_id = two_projects["a"], two_projects["b"], two_projects["a_doc"]["id"]

    resp = await host.request(method, f"/projects/{b}/corpus/documents/{a_id}{suffix}")
    assert resp.status_code == 404, (method, suffix, resp.status_code, resp.text)

    still = (await host.request("GET", f"/projects/{a}/corpus/documents")).json()
    assert a_id in {d["id"] for d in still}, "A's document survived B's request"


async def test_b_cannot_rename_or_delete_a_folder_of_a(host, two_projects):
    a, b, folder = two_projects["a"], two_projects["b"], two_projects["a_folder"]

    renamed = await host.request(
        "PATCH", f"/projects/{b}/corpus/folders/{folder['id']}", json={"name": "Taken"}
    )
    deleted = await host.request("DELETE", f"/projects/{b}/corpus/folders/{folder['id']}")
    assert renamed.status_code == 404, renamed.text
    assert deleted.status_code == 404, deleted.text

    tree = (await host.request("GET", f"/projects/{a}/corpus/tree")).json()
    assert {f["id"]: f["name"] for f in tree["folders"]}[folder["id"]] == folder["name"]
    assert two_projects["a_doc"]["id"] in {d["id"] for d in tree["documents"]}


async def test_b_cannot_select_a_file_or_folder_of_a(host, two_projects):
    b = two_projects["b"]
    for selection in (
        {"doc_keys": [two_projects["a_doc"]["doc_key"]]},
        {"folder_ids": [two_projects["a_folder"]["id"]]},
    ):
        resp = await host.request(
            "POST",
            "/runs",
            json={"project_id": b, "question": "q", "corpus_selection": selection},
        )
        assert resp.status_code == 404, (selection, resp.status_code, resp.text)
        # AC-7: the refusal does not say which id, so it cannot confirm that A's exists.
        assert two_projects["a_doc"]["doc_key"] not in resp.text
        assert two_projects["a_folder"]["id"] not in resp.text


async def _await_settled(driver: Driver, run_id: str, timeout: float = 60.0) -> dict:
    wanted = {"AWAITING_REVIEW", "AWAITING_PLAN", "FAILED", "COMPLETED"}
    deadline = asyncio.get_event_loop().time() + timeout
    while True:
        body = (await driver.request("GET", f"/runs/{run_id}")).json()
        if body["run"]["status"] in wanted or asyncio.get_event_loop().time() > deadline:
            return body
        await asyncio.sleep(0.1)


async def test_a_corpus_run_in_b_cites_only_b(host, two_projects):
    """The `cite` half of AC-1: a whole-corpus run in B, on the real run driver, retrieves
    and cites nothing of A's, though A's document is the better match for every task."""
    b, a_id = two_projects["b"], two_projects["a_doc"]["id"]
    created = await host.request(
        "POST",
        "/runs",
        json={
            "project_id": b,
            "question": "What is retrieval-augmented generation?",
            "depth": "fast",
            "corpus_mode": True,
            "skip_plan_gate": True,
        },
    )
    assert created.status_code == 201, created.text
    body = await _await_settled(host, created.json()["run_id"])

    run = body["run"]
    # A run that failed with nothing would pass every absence check below vacuously.
    assert run["status"] == "AWAITING_REVIEW", (run["status"], run["error_message"])
    cited = {document_id_of(s["url"]) for s in body["sources"]}
    assert two_projects["b_doc"]["id"] in cited, body["sources"]
    frozen = {d["document_id"] for d in run["corpus_selection"]["resolved"]}
    assert frozen == {two_projects["b_doc"]["id"]}, "B's run froze only B's corpus"
    assert cited == {two_projects["b_doc"]["id"]}, body["sources"]
    assert not any(a_id in (s["corpus_document_id"] or "") for s in body["sources"])
    for item in body["evidence"]:
        assert "Project A" not in item["snippet"], "A's text reached B's run"
