"""
A selected-files run's provenance: the persist check, the run API, and the bundle.

internal/rfcs/V3.1-corpus-scope.md §8.5–§8.6 (AC-6, AC-13, AC-21). Driven through the real
persistence adapter and the real bundle assembler against real rows — the hop under test
is row → artifact, so the row is where every test starts.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, insert, select

from app import run_bundle, run_execution, run_lifecycle
from app.api.v1.runs import project_run
from app.models.project import Project
from app.models.research import Evidence
from app.models.user import User
from research_engine.bundle import compute_bundle_hash
from research_engine.runner import RunOutcome
from research_engine.verify_bundle import verify
from tests.sqlite_support import open_db

NOW = datetime(2026, 10, 25, tzinfo=UTC)
SELECTED = "doc-selected-v1"
URL = f"corpus://{SELECTED}#chars=0-60"
SNIPPET = "Photovoltaic cells made of silicon absorb photons and release electrons."
SELECTION = {
    "requested": {"folder_ids": [], "doc_keys": ["key-1"], "whole_corpus": False},
    "resolved": [
        {
            "document_id": SELECTED,
            "doc_key": "key-1",
            "version": 1,
            "sha256": "a" * 64,
            "filename": "solar.txt",
            "path": "Thesis/solar.txt",
        }
    ],
    "corpus_id": "corpus-xyz",
    "corpus_version": 4,
}
REPORT = f"# R\n\n## Findings\n\nSilicon cells release electrons [1].\n\n## Sources\n\n[1] {URL}\n"


async def _selection_run(db):
    uid, pid = uuid.uuid4(), uuid.uuid4()
    await db.execute(
        insert(User).values(
            id=uid, email=f"{uid}@x.invalid", hashed_pw="x", is_active=True, created_at=NOW
        )
    )
    await db.execute(
        insert(Project).values(id=pid, user_id=uid, name="P", created_at=NOW, updated_at=NOW)
    )
    await db.commit()
    run = await run_lifecycle.create_run(
        db,
        owner_id=uid,
        project_id=pid,
        question="How do solar cells work?",
        depth="fast",
        corpus_mode=True,
        corpus_selection=SELECTION,
    )
    await db.commit()
    return run, uid


def _evidence(url: str) -> list[dict]:
    return [
        {
            "task_id": 1,
            "source_url": url,
            "source_title": "solar.txt",
            "snippet": SNIPPET,
            "key_fact": "cells release electrons",
        }
    ]


# ── The persist check (AC-6) ──────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "outside",
    [
        "corpus://doc-not-selected#chars=0-60",
        "https://example.org/a-web-page",
    ],
)
async def test_evidence_outside_the_selection_fails_the_run_and_is_not_kept(tmp_path, outside):
    async with open_db(tmp_path / "persist.sqlite") as maker, maker() as db:
        run, _ = await _selection_run(db)
        outcome = RunOutcome(
            status="awaiting_approval",
            draft_report=REPORT,
            sources=[{"index": 1, "title": "x", "url": outside}],
        )

        result = await run_execution.persist_outcome(
            db, run, outcome, state={"evidence": _evidence(URL) + _evidence(outside)}
        )
        await db.commit()

        assert result.status == "FAILED"
        assert run.status == "FAILED"
        assert run.error_message.startswith("selection_violation")
        stored = (
            await db.execute(
                select(func.count()).select_from(Evidence).where(Evidence.run_id == run.id)
            )
        ).scalar_one()
        assert stored == 0, "nothing from a violating run is kept as evidence"


async def test_evidence_inside_the_selection_is_kept(tmp_path):
    async with open_db(tmp_path / "persist-ok.sqlite") as maker, maker() as db:
        run, _ = await _selection_run(db)
        outcome = RunOutcome(
            status="awaiting_approval",
            draft_report=REPORT,
            sources=[{"index": 1, "title": "solar.txt", "url": URL}],
        )

        result = await run_execution.persist_outcome(
            db, run, outcome, state={"evidence": _evidence(URL)}
        )
        await db.commit()

        assert result.status != "FAILED"
        assert run.error_message is None


# ── The run API (AC-21) ───────────────────────────────────────────────────────────


async def test_the_run_api_says_what_the_run_was_allowed_to_read(tmp_path):
    async with open_db(tmp_path / "api.sqlite") as maker, maker() as db:
        run, _ = await _selection_run(db)
        body = await project_run(db, run)

        assert body["run"]["corpus_selection"]["resolved"][0]["path"] == "Thesis/solar.txt"
        assert "corpus_id" in body["run"] and "corpus_version" in body["run"]


# ── The bundle (AC-13) ────────────────────────────────────────────────────────────


@pytest.fixture
async def bundle(tmp_path):
    async with open_db(tmp_path / "bundle.sqlite") as maker, maker() as db:
        run, uid = await _selection_run(db)
        run.evidence_outcome = "READ"
        written = await run_lifecycle.record_evidence(
            db,
            run,
            evidence=_evidence(URL),
            numbered_sources=[{"index": 1, "url": URL, "title": "solar.txt"}],
        )
        revision = await run_lifecycle.record_revision(
            db, run, report_markdown=REPORT, evidence_index=written
        )
        await run_lifecycle.set_status(db, run, "AWAITING_REVIEW")
        await db.commit()
        await run_lifecycle.record_report_review(
            db, run, revision.revision, reviewer_id=uid, decision="APPROVED"
        )
        await run_lifecycle.set_status(db, run, "COMPLETED")
        await db.commit()

        manifest, reason = await run_bundle.assemble_with_reason(db, run.id)
        assert reason is None, reason
        yield manifest


def _checks(result) -> dict[str, bool]:
    return {c.name: c.passed for c in result.checks}


async def test_the_bundle_records_the_selection_and_verifies(bundle):
    assert bundle.bundle_version in (1, 2), "no new bundle format (RFC D-12)"
    assert bundle.trace[0]["event"] == "corpus_selection"
    assert bundle.trace[0]["resolved"][0]["document_id"] == SELECTED
    source = bundle.sources[0]
    assert source["document_id"] == SELECTED
    assert source["path"] == "Thesis/solar.txt"
    assert source["sha256"] == "a" * 64

    result = verify(bundle)
    assert result.passed, [(c.name, c.detail) for c in result.checks if not c.passed]
    assert _checks(result)["corpus_selection"] is True


async def test_a_consistent_bundle_citing_outside_its_selection_fails_only_that_check(bundle):
    """Re-hashed after the edit, so integrity passes: what is left to catch it is the
    selection check, and nothing else may fail in its place."""
    tampered = bundle.model_copy(deep=True)
    tampered.sources[0]["url"] = "corpus://doc-not-selected#chars=0-60"
    tampered.bundle_hash = compute_bundle_hash(tampered)

    checks = _checks(verify(tampered))
    assert checks["corpus_selection"] is False
    assert checks["bundle_integrity"] is True


async def test_editing_the_recorded_selection_breaks_the_hash(bundle):
    tampered = bundle.model_copy(deep=True)
    tampered.trace[0]["resolved"][0]["document_id"] = "doc-not-selected"

    assert _checks(verify(tampered))["bundle_integrity"] is False


async def test_the_v3_0_2_verifier_still_verifies_a_selection_bundle(bundle, tmp_path):
    """RFC D-20 / G-4: compatibility proven against the shipped verifier, not inferred.

    The verifier and its imports are taken byte-for-byte from the `v3.0.2` tag and run in a
    separate interpreter, so nothing from this checkout's engine can stand in for them.
    """
    git = shutil.which("git")
    files = ["__init__.py", "verify_bundle.py", "bundle.py", "claims.py"]
    old = tmp_path / "v3.0.2" / "research_engine"
    old.mkdir(parents=True)
    for name in files:
        shown = subprocess.run(
            [git or "git", "show", f"v3.0.2:backend/research_engine/{name}"],
            capture_output=True,
            text=True,
        )
        if git is None or shown.returncode != 0:
            pytest.skip("the v3.0.2 tag is not in this checkout (shallow clone); G-4 runs it")
        (old / name).write_text(shown.stdout, encoding="utf-8")

    path = tmp_path / "selection.bundle.json"
    path.write_text(json.dumps(bundle.model_dump(), ensure_ascii=False), encoding="utf-8")
    probe = (
        "import json, sys\n"
        f"sys.path.insert(0, {str(old.parent)!r})\n"
        "from research_engine import verify_bundle\n"
        f"assert verify_bundle.__file__.startswith({str(old)!r}), verify_bundle.__file__\n"
        f"r = verify_bundle.verify_file({str(path)!r})\n"
        "print(json.dumps({'passed': r.passed, "
        "'checks': [[c.name, c.passed, c.detail] for c in r.checks]}))\n"
    )
    done = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, cwd=tmp_path
    )
    assert done.returncode == 0, done.stderr
    result = json.loads(done.stdout.strip().splitlines()[-1])
    assert result["passed"], result["checks"]
