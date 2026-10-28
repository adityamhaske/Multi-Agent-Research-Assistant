"""
A desktop that ran v3.0.2 opens under 3.1 with its whole shared corpus moved, and nothing
leaks (RFC V3.1 §7.3; AC-23 desktop half, AC-27).

The files under `tests/fixtures/upgrade/v3.0.2-populated/` were written by the v3.0.2
sidecar itself. `scripts/make_upgrade_fixture.py --release 3.0.2` keeps nothing unless the
sidecar reports 3.0.2 at the tag's commit. They hold the last shared corpus a desktop user
can have:
- every kind 3.0.2 reads, uploaded under two different projects;
- a superseded version;
- three generated reports;
- a corpus-only run that cited from that store.

Each criterion is checked against that file, through the real sidecar:
- every document moves with its id, `doc_key`, version, `sha256` and `superseded_at`
  intact, and the `corpus_id` is unchanged;
- after the move no project but "Documents from before 3.1" can list, open or download
  any of them (AC-1 re-run on the migrated store);
- the 3.0.2 run that quoted them still opens exactly what it cited (§7.3);
- deleting the legacy project leaves every other project's research intact;
- a second launch changes nothing.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
from pathlib import Path

import pytest

from desktop import corpus_layout
from research_engine.verify_bundle import verify_file
from tests.parity.drivers import desktop_driver

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "upgrade" / "v3.0.2-populated"
MANIFEST = json.loads((FIXTURE / "MANIFEST.json").read_text(encoding="utf-8"))
ROWS = "SELECT id, doc_key, version, sha256, superseded_at FROM corpus_documents ORDER BY id"


def _rows(path: Path) -> list[tuple]:
    with sqlite3.connect(path) as conn:
        return conn.execute(ROWS).fetchall()


def _corpus_id(path: Path) -> str:
    with sqlite3.connect(path) as conn:
        return conn.execute("SELECT corpus_id FROM corpus_meta").fetchone()[0]


@pytest.fixture()
def install(tmp_path) -> Path:
    """A copy of the v3.0.2 data directory — the test never writes to the committed one."""
    data = tmp_path / "research-engine"
    shutil.copytree(FIXTURE, data, ignore=shutil.ignore_patterns("MANIFEST.json", "*.bundle.json"))
    return data


async def _projects(driver) -> dict[str, str]:
    listed = (await driver.request("GET", "/projects")).json()["projects"]
    return {p["name"]: p["id"] for p in listed}


def test_the_fixture_files_are_the_ones_v3_0_2_wrote():
    assert MANIFEST["sidecar"] == {
        "version": "3.0.2",
        "git_sha": "0a9de70ee90485531120856fce7f5dde4041c0aa",
    }
    for name, digest in MANIFEST["files"].items():
        assert hashlib.sha256((FIXTURE / name).read_bytes()).hexdigest() == digest, name


def test_the_fixture_holds_what_ac_23_asks_for():
    with sqlite3.connect(FIXTURE / "corpus.sqlite") as conn:
        kinds = {r[0] for r in conn.execute("SELECT kind FROM corpus_documents")}
        origins = {r[0] for r in conn.execute("SELECT origin FROM corpus_documents")}
        superseded = conn.execute(
            "SELECT COUNT(*) FROM corpus_documents WHERE superseded_at IS NOT NULL"
        ).fetchone()[0]
    assert {"pdf", "html", "md", "txt"} <= kinds
    assert origins == {"uploaded", "generated"}
    assert superseded >= 1


async def test_every_document_moves_into_one_project_unchanged(install):
    before, corpus_id = _rows(install / "corpus.sqlite"), _corpus_id(install / "corpus.sqlite")

    async with desktop_driver(install) as driver:
        projects = await _projects(driver)
        legacy = projects[corpus_layout.LEGACY_PROJECT_NAME]
        listed = (await driver.request("GET", f"/projects/{legacy}/corpus/documents")).json()

    moved = install / "corpus" / f"corpus_{legacy}.sqlite"
    assert _rows(moved) == before, "ids, doc_keys, versions, hashes and supersession kept"
    assert _corpus_id(moved) == corpus_id
    assert {d["id"] for d in listed} == {row[0] for row in before}
    assert _rows(install / corpus_layout.BACKUP_FILENAME) == before, "the backup is kept"
    assert not (install / corpus_layout.LEGACY_FILENAME).exists()


async def test_no_other_project_can_reach_a_moved_document(install):
    """AC-27, last bullet: project isolation holds on the migrated store, including for the
    two projects whose own uploads these were under 3.0.2."""
    before = _rows(install / "corpus.sqlite")
    async with desktop_driver(install) as driver:
        projects = await _projects(driver)
        others = [
            pid for name, pid in projects.items() if name != corpus_layout.LEGACY_PROJECT_NAME
        ]
        assert MANIFEST["project_id"] in others and MANIFEST["second_project_id"] in others
        for pid in others:
            listed = (await driver.request("GET", f"/projects/{pid}/corpus/documents")).json()
            assert listed == [], pid
            for doc_id, *_ in before:
                for suffix in ("/text", "/download"):
                    resp = await driver.request(
                        "GET", f"/projects/{pid}/corpus/documents/{doc_id}{suffix}"
                    )
                    assert resp.status_code == 404, (pid, doc_id, suffix)


async def test_the_3_0_2_run_still_opens_what_it_cited_and_nothing_else(install):
    run = MANIFEST["corpus_run_id"]
    async with desktop_driver(install) as driver:
        body = (await driver.request("GET", f"/runs/{run}")).json()
        cited = {s["url"].split("#")[0].removeprefix("corpus://") for s in body["sources"]}
        assert cited, "the 3.0.2 corpus run cited from the shared store"
        for doc_id in cited:
            resp = await driver.request("GET", f"/runs/{run}/cited-documents/{doc_id}")
            assert resp.status_code == 200, (doc_id, resp.text)
            assert resp.json()["text"]
        uncited = set(MANIFEST["documents"].values()) - cited
        for doc_id in uncited:
            resp = await driver.request("GET", f"/runs/{run}/cited-documents/{doc_id}")
            assert resp.status_code == 404, doc_id


async def test_deleting_the_moved_project_leaves_everything_else(install):
    async with desktop_driver(install) as driver:
        projects = await _projects(driver)
        legacy = projects.pop(corpus_layout.LEGACY_PROJECT_NAME)
        gone = await driver.request("DELETE", f"/projects/{legacy}")
        assert gone.status_code == 204, gone.text
        assert await _projects(driver) == projects
        for run in (MANIFEST["run_completed_id"], MANIFEST["run_awaiting_review_id"]):
            resp = await driver.request("GET", f"/runs/{run}")
            assert resp.status_code == 200, run
        session = await driver.request("GET", f"/research/{MANIFEST['session_completed_id']}")
        assert session.status_code == 200
    assert not (install / "corpus" / f"corpus_{legacy}.sqlite").exists()
    assert (install / corpus_layout.BACKUP_FILENAME).exists(), "the backup is never deleted"


async def test_a_second_launch_changes_nothing(install):
    async with desktop_driver(install) as driver:
        first = await _projects(driver)
    moved = install / "corpus" / f"corpus_{first[corpus_layout.LEGACY_PROJECT_NAME]}.sqlite"
    rows = _rows(moved)
    async with desktop_driver(install) as driver:
        assert await _projects(driver) == first
    assert _rows(moved) == rows


def test_the_bundles_3_0_2_exported_still_verify():
    for name in ("run-completed.bundle.json", "session-completed.bundle.json"):
        result = verify_file(FIXTURE / name)
        assert result.passed, (name, [c for c in result.checks if not c.passed])
