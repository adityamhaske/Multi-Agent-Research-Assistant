"""
One corpus contract, stated as a table and asserted against both hosts (parity Phase 2b).

The per-project corpus path is the canonical product contract — the server keeps one
SQLite file per project, the desktop one for the whole app, and that difference is
infrastructure that stays. What was never supposed to differ is what a client sees, and
all of it did:

| | server (was) | desktop (was) |
|---|---|---|
| success | `200` | `201` |
| missing filename / empty / unsupported | `400` | `422` |
| over the size limit | *no limit enforced* | `413` |
| embedder unreachable | *propagated as a 500* | `503` |
| body | full `DocumentResponse` | `id`, `filename`, `chunks` only |
| download `Content-Type` | `text/plain; charset=utf-8` | *absent* |
| delete | `204` **with `content-type: application/json`** and an empty body | `204`, no type |

None of it was caught: the operation existed on both hosts, so the route check passed, and
the desktop declared no `response_model`, so the shape check skipped it (Phase 1 closed
that). The parity goldens then recorded each difference so this fix could be reviewed
against a baseline rather than against memory.

**Both hosts are driven here, from one table.** A test that checked only one of them would
be the same shape as the defect.
"""

from __future__ import annotations

import pytest

from app.schemas.corpus import DocumentResponse
from research_engine.documents import MAX_DOCUMENT_BYTES
from tests.parity.drivers import desktop_driver, server_driver

TEXT_DOC = b"Recall improved by twelve points on the internal benchmark."


@pytest.fixture(params=["server", "desktop"])
async def host(request, tmp_path):
    """Both hosts, same journey. `params` rather than two test modules, so a fix that
    lands on one host and not the other cannot pass."""
    make = server_driver if request.param == "server" else desktop_driver
    async with make(tmp_path / request.param) as driver:
        resp = await driver.request("POST", "/projects", json={"name": "Corpus contract"})
        assert resp.status_code == 201
        driver.project_id = resp.json()["id"]  # type: ignore[attr-defined]
        yield driver


def _upload_path(driver) -> str:
    return f"/projects/{driver.project_id}/corpus/documents"


async def _upload(driver, name: str, data: bytes, content_type: str = "text/plain"):
    return await driver.request(
        "POST", _upload_path(driver), files={"file": (name, data, content_type)}
    )


# ── Success ───────────────────────────────────────────────────────────────────────


async def test_a_successful_upload_is_201_on_both_hosts(host):
    """`POST` that creates a document answers `201`. The server used to answer `200`."""
    resp = await _upload(host, "notes.txt", TEXT_DOC)
    assert resp.status_code == 201, resp.text


async def test_the_upload_body_is_the_full_document_shape_on_both_hosts(host):
    resp = await _upload(host, "notes.txt", TEXT_DOC)
    assert set(resp.json()) == set(DocumentResponse.model_fields)
    assert resp.json()["chunks"] >= 1, "an ingest that stored no chunks is not an ingest"


# ── Refusals ──────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("name", "data", "expected_status"),
    [
        ("empty.txt", b"", 400),
        ("thing.exe", b"MZ\x00binary", 400),
        ("/", TEXT_DOC, 400),
        ("huge.txt", b"x" * (MAX_DOCUMENT_BYTES + 1), 413),
    ],
    ids=["empty body", "unsupported format", "a name with no basename", "over the size limit"],
)
async def test_a_refused_upload_uses_the_same_status_on_both_hosts(
    host, name, data, expected_status
):
    """`413` in particular is a change on the *server*, which enforced no limit at all —
    the desktop's guard was strictly better and is now the contract."""
    resp = await _upload(host, name, data)
    assert resp.status_code == expected_status, resp.text


async def test_a_part_that_is_not_a_file_is_refused_the_same_way_on_both_hosts(host):
    """An empty filename means the client did not send a file part at all — the multipart
    encoder degrades it to a plain form field — so FastAPI's own body validation rejects
    it before any corpus code runs. `422` here is that validation's contract, identical on
    both hosts because both declare `UploadFile`, and deliberately not something
    `clean_upload` overrides: an application-level `400` would have to be produced by
    accepting the part first, which is worse.
    """
    resp = await _upload(host, "", TEXT_DOC)
    assert resp.status_code == 422
    assert resp.json()["detail"][0]["loc"] == ["body", "file"]


async def test_a_refusal_says_what_was_wrong(host):
    """A status code alone leaves the UI with nothing to show."""
    resp = await _upload(host, "empty.txt", b"")
    assert resp.json()["detail"], "a 400 with no detail tells the user nothing"


# ── Download ──────────────────────────────────────────────────────────────────────


async def test_a_download_carries_its_content_type_on_both_hosts(host):
    """The desktop served the bytes with no `Content-Type` at all, so a browser had to
    sniff a file another user uploaded — which `X-Content-Type-Options: nosniff`, sent on
    the same response, explicitly forbids it from doing."""
    doc_id = (await _upload(host, "notes.txt", TEXT_DOC)).json()["id"]
    resp = await host.request("GET", f"{_upload_path(host)}/{doc_id}/download")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/plain")
    assert resp.content == TEXT_DOC


# ── Delete ────────────────────────────────────────────────────────────────────────


async def test_delete_returns_a_body_less_204_on_both_hosts(host):
    """A `204` carrying `content-type: application/json` and no body does not parse —
    every client that reads it has to special-case the status before touching the body."""
    doc_id = (await _upload(host, "notes.txt", TEXT_DOC)).json()["id"]
    resp = await host.request("DELETE", f"{_upload_path(host)}/{doc_id}")
    assert resp.status_code == 204
    assert not resp.content
    assert "application/json" not in resp.headers.get("content-type", "")


async def test_deleting_an_unknown_document_is_404_on_both_hosts(host):
    resp = await host.request("DELETE", f"{_upload_path(host)}/no-such-document")
    assert resp.status_code == 404
    assert resp.json()["detail"]
