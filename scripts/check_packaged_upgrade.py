#!/usr/bin/env python3
"""
Launch a packaged V3 sidecar on a v2.1.0 data directory and record what the upgrade did.

Exit criterion 5 asks for a populated v2.1.0 install that "upgrades to V3 and runs research,
on a real launch — not a fresh install, not a source checkout". The CI test
(`backend/tests/workflow/test_v2_1_0_desktop_upgrade.py`) runs the same journey against the
source tree on every change; it structurally cannot say anything about the frozen binary,
whose import tree is a different thing (`research-sidecar.spec` excludes packages the source
checkout has). This drives the binary itself and writes down what it saw.

    python scripts/check_packaged_upgrade.py \\
        --sidecar backend/dist/research-sidecar/research-sidecar \\
        --install backend/tests/fixtures/upgrade/v2.1.0 \\
        --out evidence.json

`--install` is only ever copied: the launch happens in a temporary directory, so the source —
a committed fixture, or a data directory the real v2.1.0 app wrote — is never upgraded in
place. The sidecar runs with `--fake`, the same scripted models `desktop.yml` drives the
packaged app with, and every bundle it produces is therefore stamped `demo`; what this
proves is that the upgraded install opens, keeps its data and runs the pipeline, not
anything about research quality.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import shlex
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

from make_upgrade_fixture import Sidecar

ROOT = Path(__file__).resolve().parent.parent
OVERRIDE = "Plan exactly three research tasks, each answerable from one primary source."
V3_COLUMNS = {
    "research_runs": [
        "effective_prompt_overrides",
        "prompt_overrides_status",
        "effective_prompt_provenance",
    ],
    "sessions": ["prompt_overrides_not_applied"],
}


def _row_counts(db: Path) -> dict[str, int]:
    with sqlite3.connect(db) as conn:
        tables = [
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        ]
        return {t: conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in tables}  # noqa: S608


def _columns(db: Path, table: str) -> list[str]:
    with sqlite3.connect(db) as conn:
        return [row[1] for row in conn.execute(f'PRAGMA table_info("{table}")')]


def _standalone_verdict(bundle: bytes, scratch: Path, name: str) -> dict:
    """The shipped verifier, run the way a third party runs it — as a separate process."""
    path = scratch / name
    path.write_bytes(bundle)
    done = subprocess.run(  # noqa: S603
        [sys.executable, "-m", "research_engine.verify_bundle", str(path)],
        cwd=ROOT / "backend",
        capture_output=True,
        text=True,
    )
    return {"exit_code": done.returncode, "output": done.stdout.strip().splitlines()}


def _finish(sidecar: Sidecar, run_id: str) -> None:
    status = sidecar.json("GET", f"/runs/{run_id}")["run"]["status"]
    if status in {"PENDING", "RUNNING", "AWAITING_PLAN"}:
        sidecar.await_run(run_id, "AWAITING_PLAN")
        sidecar.call("POST", f"/runs/{run_id}/plan-review", {"decision": "APPROVED"})
    sidecar.await_run(run_id, "AWAITING_REVIEW")
    sidecar.call("POST", f"/runs/{run_id}/report-review", {"decision": "APPROVED"})
    sidecar.await_run(run_id, "COMPLETED")


def _bundle_facts(sidecar: Sidecar, run_id: str, scratch: Path, name: str) -> dict:
    raw = sidecar.call("GET", f"/runs/{run_id}/bundle.json")
    bundle = json.loads(raw)
    in_app = sidecar.json("GET", f"/runs/{run_id}/verification")
    return {
        "run_id": run_id,
        "bundle_version": bundle["bundle_version"],
        "demo": bundle.get("demo"),
        "prompt_overrides_status": bundle.get("prompt_overrides_status"),
        "overridden_purposes": [
            r["purpose"] for r in bundle.get("prompt_provenance", []) if r["overridden"]
        ],
        "provenance_purposes": [r["purpose"] for r in bundle.get("prompt_provenance", [])],
        "in_app_verification_passed": in_app["passed"],
        "standalone_verifier": _standalone_verdict(raw, scratch, name),
    }


def _new_run(sidecar: Sidecar, project_id: str) -> str:
    return sidecar.json(
        "POST",
        "/runs",
        {
            "project_id": project_id,
            "question": "How do retrieval-augmented agents keep long-term memory consistent?",
            "depth": "fast",
            "skip_plan_gate": False,
            "dispatch": True,
        },
    )["run_id"]


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--sidecar", required=True, help="the packaged V3 sidecar")
    parser.add_argument("--install", required=True, type=Path, help="a v2.1.0 data directory")
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()

    manifest = json.loads((args.install / "MANIFEST.json").read_text())
    evidence: dict = {
        "checked_at": dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat(),
        "sidecar_command": args.sidecar,
        "install_source": str(args.install),
        "install_written_by": manifest["sidecar"],
    }
    with tempfile.TemporaryDirectory(prefix="v3-upgrade-") as scratch_dir:
        scratch = Path(scratch_dir)
        data = scratch / "data"
        shutil.copytree(
            args.install, data, ignore=shutil.ignore_patterns("MANIFEST.json", "*.bundle.json")
        )
        db = data / "desktop.sqlite"
        before = _row_counts(db)
        evidence["columns_before"] = {t: _columns(db, t) for t in V3_COLUMNS}

        sidecar = Sidecar(shlex.split(args.sidecar), None, data, scratch / "sidecar.log")
        try:
            evidence["sidecar"] = sidecar.json("GET", "/version")
            evidence["v3_columns_added"] = {
                t: [c for c in cols if c in _columns(db, t)] for t, cols in V3_COLUMNS.items()
            }
            evidence["row_counts_unchanged_by_startup"] = _row_counts(db) == before

            me = sidecar.json("GET", "/auth/me")
            evidence["preferences_after_upgrade"] = me["preferences"]

            session = sidecar.json("GET", f"/research/{manifest['session_completed_id']}")
            exported = sidecar.call(
                "GET", f"/research/{manifest['session_completed_id']}/export.bundle.json"
            )
            evidence["pre_v3_session"] = {
                "status": session["status"],
                "has_report": bool(session["final_report"]),
                "bundle_version": json.loads(exported)["bundle_version"],
                "standalone_verifier": _standalone_verdict(exported, scratch, "session.json"),
            }
            demo = sidecar.json("GET", f"/research/{manifest['demo_session_id']}")
            evidence["pre_v3_demo_session_status"] = demo["status"]

            evidence["pre_v3_completed_run"] = _bundle_facts(
                sidecar, manifest["run_completed_id"], scratch, "completed.json"
            )
            waiting = manifest["run_awaiting_review_id"]
            evidence["pre_v3_waiting_run_status_at_launch"] = sidecar.json(
                "GET", f"/runs/{waiting}"
            )["run"]["status"]
            _finish(sidecar, waiting)
            evidence["pre_v3_waiting_run_after_approval"] = _bundle_facts(
                sidecar, waiting, scratch, "waiting.json"
            )

            fresh = _new_run(sidecar, manifest["project_id"])
            _finish(sidecar, fresh)
            evidence["post_upgrade_run"] = _bundle_facts(sidecar, fresh, scratch, "fresh.json")

            sidecar.call(
                "PATCH", "/auth/me", {"preferences": {"prompt_overrides": {"planner": OVERRIDE}}}
            )
            customised = _new_run(sidecar, manifest["project_id"])
            _finish(sidecar, customised)
            evidence["post_upgrade_customised_run"] = _bundle_facts(
                sidecar, customised, scratch, "customised.json"
            )
            evidence["preferences_after_customising"] = sidecar.json("GET", "/auth/me")[
                "preferences"
            ]
        finally:
            sidecar.stop()
        after = _row_counts(db)
        evidence["no_rows_lost"] = all(after[t] >= n for t, n in before.items())

    args.out.write_text(json.dumps(evidence, indent=2) + "\n")
    print(json.dumps(evidence, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
