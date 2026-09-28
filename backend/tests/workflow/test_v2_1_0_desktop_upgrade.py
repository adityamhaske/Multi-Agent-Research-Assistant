"""
A desktop that ran v2.1.0 opens under V3 with everything it had, and keeps working.

RG-4b / exit criterion 5 (`internal/rfcs/V3.0-agentspec-scope.md` §15.3, §24). The files
under `tests/fixtures/upgrade/v2.1.0/` were written by the v2.1.0 sidecar itself —
`scripts/make_upgrade_fixture.py` refuses to keep anything a sidecar wrote unless it reports
version 2.1.0 at the tag's commit — so this is the upgrade of a database somebody actually
holds, not of one reconstructed from today's models with columns taken out.
`test_desktop_column_sync.py` proves the additive sync handles a missing column; this proves
the whole install survives it: the first launch, saved preferences, a project, research on
both pipelines, a run left waiting at a gate, and the bundles already exported.

What "keeps working" means here is the V3 contract, each part of it asserted:

- nothing that was in the file is lost, and nothing is re-seeded over it;
- the bundles v2.1.0 exported still verify, unchanged, under the V3 verifier (AC-9);
- re-exporting pre-V3 research yields v1 — its prompts were never recorded, and the
  assembler refuses to invent them (`app/run_bundle.py::_provenance_records`);
- research started after the upgrade emits a v2 bundle carrying prompt provenance, with and
  without a customised role (AC-D3a, AC-D3b).

The real launch of the packaged app on a v2.1.0 data directory is separate evidence (the
exit criterion says "on a real launch — not a source checkout"); this is the part CI repeats
on every change.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
from pathlib import Path

import pytest

from research_engine.bundle import BundleManifest
from research_engine.verify_bundle import verify, verify_file
from tests.parity.drivers import desktop_driver
from tests.parity.journeys import _await_run_status

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "upgrade" / "v2.1.0"
MANIFEST = json.loads((FIXTURE / "MANIFEST.json").read_text(encoding="utf-8"))

#: What V3 added to the tables a v2.1.0 install already has (migrations 0026 and 0027). The
#: desktop gets them from `_add_missing_columns`, not Alembic.
V3_COLUMNS = {
    "research_runs": {
        "effective_prompt_overrides",
        "prompt_overrides_status",
        "effective_prompt_provenance",
    },
    "sessions": {"prompt_overrides_not_applied"},
}

OVERRIDE = "Plan exactly three research tasks, each answerable from one primary source."


def _columns(db: Path, table: str) -> set[str]:
    with sqlite3.connect(db) as conn:
        return {row[1] for row in conn.execute(f'PRAGMA table_info("{table}")')}


def _row_counts(db: Path) -> dict[str, int]:
    with sqlite3.connect(db) as conn:
        tables = [
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        ]
        return {t: conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in tables}  # noqa: S608


@pytest.fixture()
def install(tmp_path) -> Path:
    """A copy of the v2.1.0 data directory — the test never writes to the committed one."""
    data = tmp_path / "research-engine"
    shutil.copytree(
        FIXTURE,
        data,
        ignore=shutil.ignore_patterns("MANIFEST.json", "*.bundle.json"),
    )
    return data


# ── The fixture is what it claims to be ───────────────────────────────────────────


def test_the_fixture_files_are_the_ones_v2_1_0_wrote():
    """A hand-edited fixture would upgrade a database v2.1.0 never produced."""
    assert MANIFEST["sidecar"] == {
        "version": "2.1.0",
        "git_sha": "4580ac06e7e5ef214b55fcad580e4a40b3689f30",
    }
    for name, digest in MANIFEST["files"].items():
        assert hashlib.sha256((FIXTURE / name).read_bytes()).hexdigest() == digest, name


def test_the_fixture_predates_every_v3_column():
    """Otherwise the sync below would have nothing to do and the test would prove nothing."""
    for table, added in V3_COLUMNS.items():
        assert not added & _columns(FIXTURE / "desktop.sqlite", table), table


@pytest.mark.parametrize("name", ["run-completed.bundle.json", "session-completed.bundle.json"])
def test_bundles_v2_1_0_exported_still_verify_unchanged(name):
    """AC-9 against the artifacts a v2.1.0 user already holds, not ones regenerated today."""
    result = verify_file(FIXTURE / name)
    assert result.passed, [(c.name, c.detail) for c in result.checks if not c.passed]
    assert json.loads((FIXTURE / name).read_text())["bundle_version"] == 1
    assert result.prompt_provenance == []
    assert result.prompt_overrides_status is None


# ── The upgrade ───────────────────────────────────────────────────────────────────


async def _finish(driver, run_id: str) -> dict:
    """Take a run through whichever gates it still has, and return its bundle."""
    at = await _await_run_status(driver, run_id, {"AWAITING_PLAN", "AWAITING_REVIEW", "FAILED"})
    if at.json()["run"]["status"] == "AWAITING_PLAN":
        resp = await driver.request(
            "POST", f"/runs/{run_id}/plan-review", json={"decision": "APPROVED"}
        )
        assert resp.status_code == 201, resp.text
        at = await _await_run_status(driver, run_id, {"AWAITING_REVIEW", "FAILED"})
    assert at.json()["run"]["status"] == "AWAITING_REVIEW", at.text
    resp = await driver.request(
        "POST", f"/runs/{run_id}/report-review", json={"decision": "APPROVED"}
    )
    assert resp.status_code == 201, resp.text
    done = await _await_run_status(driver, run_id, {"COMPLETED", "FAILED"})
    assert done.json()["run"]["status"] == "COMPLETED", done.text
    bundle = await driver.request("GET", f"/runs/{run_id}/bundle.json")
    assert bundle.status_code == 200, bundle.text
    return bundle.json()


def _verified(bundle: dict):
    result = verify(BundleManifest.model_validate(bundle))
    assert result.passed, [(c.name, c.detail) for c in result.checks if not c.passed]
    return result


async def _new_run(driver) -> str:
    resp = await driver.request(
        "POST",
        "/runs",
        json={
            "project_id": MANIFEST["project_id"],
            "question": "How do retrieval-augmented agents keep long-term memory consistent?",
            "depth": "fast",
            "skip_plan_gate": False,
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["run_id"]


async def test_a_populated_v2_1_0_install_upgrades_and_keeps_working(install, monkeypatch):
    db = install / "desktop.sqlite"
    before = _row_counts(db)
    assert before == MANIFEST["row_counts"]["desktop.sqlite"]
    marker = (install / "demo_seeded.json").read_bytes()
    # `desktop_driver` marks the demo as seeded before launching, which is right for a fresh
    # directory and wrong here: it would overwrite v2.1.0's own marker and hide a V3 that no
    # longer recognised it. Disabled, the only thing that can stop a second demo is the file
    # v2.1.0 wrote.
    monkeypatch.setattr("desktop.sidecar.mark_demo_seeded", lambda _data_dir: None)

    async with desktop_driver(install) as driver:
        # Startup is the upgrade: the additive sync ran inside the lifespan.
        for table, added in V3_COLUMNS.items():
            assert added <= _columns(db, table), table
        # Nothing was lost and nothing was seeded over the install — not a second user, not
        # a second "General" project, not a fresh demo on what is not a first launch.
        assert _row_counts(db) == before
        assert (install / "demo_seeded.json").read_bytes() == marker

        me = (await driver.request("GET", "/auth/me")).json()
        assert me["preferences"]["retrieval_k"] == MANIFEST["preferences"]["retrieval_k"]
        assert me["preferences"]["density"] == MANIFEST["preferences"]["density"]
        assert not me["preferences"].get("prompt_overrides")

        projects = (await driver.request("GET", "/projects")).json()["projects"]
        assert MANIFEST["project_id"] in {p["id"] for p in projects}

        # Research on the earlier pipeline stays readable and exportable, and records that
        # it predates overrides rather than claiming they were ignored.
        demo = await driver.request("GET", f"/research/{MANIFEST['demo_session_id']}")
        assert demo.status_code == 200
        assert demo.json()["status"] == MANIFEST["demo_session_status"]
        session_id = MANIFEST["session_completed_id"]
        session = (await driver.request("GET", f"/research/{session_id}")).json()
        assert session["status"] == "COMPLETED"
        assert session["final_report"]
        assert session["prompt_overrides_not_applied"] is False
        exported = await driver.request("GET", f"/research/{session_id}/export.bundle.json")
        assert exported.status_code == 200
        assert exported.json()["bundle_version"] == 1
        _verified(exported.json())

        # A run v2.1.0 finished re-exports as v1 and verifies. Its prompts were never
        # recorded, so a v2 bundle for it could only be invented.
        completed = MANIFEST["run_completed_id"]
        run = (await driver.request("GET", f"/runs/{completed}")).json()["run"]
        assert run["status"] == "COMPLETED"
        rebuilt = (await driver.request("GET", f"/runs/{completed}/bundle.json")).json()
        assert rebuilt["bundle_version"] == 1
        assert "prompt_provenance" not in rebuilt
        _verified(rebuilt)
        original = json.loads((FIXTURE / "run-completed.bundle.json").read_text())
        assert rebuilt["report_hash"] == original["report_hash"]
        assert [e["content_hash"] for e in rebuilt["evidence"]] == [
            e["content_hash"] for e in original["evidence"]
        ]

        # The run left waiting at the report gate across the upgrade can still be approved.
        # Its first half ran under v2.1.0, which recorded no prompts, so it too stays v1.
        waiting = MANIFEST["run_awaiting_review_id"]
        resumed = await _finish(driver, waiting)
        assert resumed["bundle_version"] == 1
        _verified(resumed)

        # Research started after the upgrade is V3 research: v2, provenance recorded,
        # nothing customised yet.
        fresh = await _finish(driver, await _new_run(driver))
        assert fresh["bundle_version"] == 2
        assert fresh["prompt_overrides_status"] == "NONE"
        assert fresh["prompt_provenance"]
        assert all(not r["overridden"] for r in fresh["prompt_provenance"])
        assert _verified(fresh).prompt_overrides_status == "NONE"

        # A customisation saved after the upgrade merges into the preferences v2.1.0 left,
        # and the next run records exactly what it replaced.
        saved = await driver.request(
            "PATCH", "/auth/me", json={"preferences": {"prompt_overrides": {"planner": OVERRIDE}}}
        )
        assert saved.status_code == 200, saved.text
        assert saved.json()["preferences"]["retrieval_k"] == MANIFEST["preferences"]["retrieval_k"]
        customised = await _finish(driver, await _new_run(driver))
        assert customised["bundle_version"] == 2
        assert customised["prompt_overrides_status"] == "APPLIED"
        replaced = [r for r in customised["prompt_provenance"] if r["overridden"]]
        assert [r["purpose"] for r in replaced] == ["planner.main"]
        assert OVERRIDE in replaced[0]["effective_prompt"]
        result = _verified(customised)
        assert result.prompt_overrides_status == "APPLIED"

    # Everything that was in the file is still there after the upgrade and the new work.
    after = _row_counts(db)
    assert all(after[table] >= count for table, count in before.items()), (before, after)
