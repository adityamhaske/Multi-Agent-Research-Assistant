"""
`scripts/gates/g4_bundle_compat.py` holds every G-4 expectation, and fails when one breaks
(RFC V3.1 §14.1, D-20; release blocker 3).

The gate's evidence comes from bundles real selection runs produce. This drives the same
script on one the real assembler builds here, a selection run with a grounding record, so
the script's own logic runs in CI rather than first on release day. The v3.0.2 verifier is
read from the tag, so the test needs the tag (`ci.yml` fetches it), and it skips only where
no tag can be read outside CI.
"""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path

import pytest

from app import run_bundle, run_lifecycle
from tests.dataflow.test_selection_provenance import REPORT, URL, _evidence, _selection_run
from tests.sqlite_support import open_db

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts" / "gates" / "g4_bundle_compat.py"


def _gate():
    spec = importlib.util.spec_from_file_location("g4_bundle_compat", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
async def selection_bundle(tmp_path) -> Path:
    async with open_db(tmp_path / "g4.sqlite") as maker, maker() as db:
        run, uid = await _selection_run(db)
        run.evidence_outcome = "READ"
        run.grounding_report = {
            "status": "complete",
            "claims_total": 1,
            "claims_supported": 1,
            "claims_rejected": 0,
            "claims_unmeasured": 0,
        }
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
    path = tmp_path / "selection.bundle.json"
    path.write_text(json.dumps(manifest.model_dump(), ensure_ascii=False), encoding="utf-8")
    return path


def _run_gate(bundle: Path, out: Path, gate=None) -> tuple[int, dict]:
    gate = gate or _gate()
    code = gate.main([str(bundle), "--out", str(out)])
    evidence = json.loads((out / "g4.json").read_text(encoding="utf-8"))
    if code != 0 and "cannot read the v3.0.2 tag" in json.dumps(evidence):
        if os.environ.get("CI"):
            pytest.fail("the v3.0.2 tag is missing in CI; ci.yml fetches it for this test")
        pytest.skip("the v3.0.2 tag is not in this checkout (shallow clone)")
    return code, evidence


def test_every_g4_expectation_holds_for_a_selection_bundle(selection_bundle, tmp_path):
    code, evidence = _run_gate(selection_bundle, tmp_path / "evidence")

    assert code == 0, evidence["problems"]
    assert len(evidence["v3.0.2_verifier"]["verify_bundle.py sha256"]) == 64
    (bundle,) = evidence["bundles"]
    assert set(bundle["cases"]) == {
        "as produced",
        "source edited",
        "selection trace entry edited",
        "grounding_validation edited",
        "report edited",
        "outside selection, rehashed",
    }
    assert all(case["held"] for case in bundle["cases"].values())
    # The 3.0.2 verifier knows nothing of selections, so it passes the rehashed bundle the
    # 3.1 verifier refuses: the new check is an addition, not a format change (§8.6).
    rehashed = bundle["cases"]["outside selection, rehashed"]
    assert rehashed["v3.0.2"]["passed"] and not rehashed["3.1"]["passed"]


def test_a_tamper_the_verifiers_miss_fails_the_gate(selection_bundle, tmp_path, monkeypatch):
    """Negative control: an 'edit' that changes nothing passes both verifiers, and the gate
    must report that as a failure rather than as a tamper caught."""
    gate = _gate()
    real = gate.tampered

    def harmless(bundle):
        cases = real(bundle)
        cases["source edited"] = json.loads(json.dumps(bundle))
        return cases

    monkeypatch.setattr(gate, "tampered", harmless)
    code, evidence = _run_gate(selection_bundle, tmp_path / "evidence", gate)

    assert code == 1
    assert any("source edited" in p for p in evidence["problems"])


def test_a_bundle_without_a_selection_is_refused(selection_bundle, tmp_path):
    bundle = json.loads(selection_bundle.read_text(encoding="utf-8"))
    bundle["trace"] = [t for t in bundle["trace"] if t.get("event") != "corpus_selection"]
    plain = tmp_path / "plain.bundle.json"
    plain.write_text(json.dumps(bundle), encoding="utf-8")

    code, evidence = _run_gate(plain, tmp_path / "evidence")

    assert code == 1
    assert "records no corpus_selection" in evidence["problems"][0]
