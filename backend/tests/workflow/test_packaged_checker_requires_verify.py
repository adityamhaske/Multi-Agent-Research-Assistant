"""
A bundle verification that did not run is a failure where CI says it must run.

`scripts/check_packaged_sidecar.py --journey` ends by handing the bundle the packaged engine
exported to the repository's standalone verifier. The checker is standard-library only and the
verifier imports pydantic, so where pydantic is missing it reports
`"verify_bundle": "NOT RUN — …"` and still passes. That is honest for a person checking a
published installer by hand. In CI it was a false pass: every Shell job logged that line, and
went green, while RELEASE.md said the checker proved "an exported, verified bundle".

`--require-verify` turns NOT RUN into a failure, and every `desktop.yml` call passes it. The
negative controls plant the real defect, an unimportable pydantic, and drive the checker's own
`main()` against an engine that answers the way the packaged one does. That follows the flag
from argv to the verdict. Without the flag, the same run must still pass as NOT RUN.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
CHECKER = ROOT / "scripts" / "check_packaged_sidecar.py"
DESKTOP_YML = ROOT / ".github" / "workflows" / "desktop.yml"
VALID_BUNDLE = ROOT / "backend" / "tests" / "fixtures" / "bundles" / "v2-customised.bundle.json"
SHA = "c0ffee" + "1" * 34


def _load_checker():
    spec = importlib.util.spec_from_file_location("check_packaged_sidecar", CHECKER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _PackagedEngine:
    """Answers the checker's calls the way a healthy packaged engine does, through both gates."""

    def __init__(self, binary: Path, data_dir: Path, startup_timeout: float) -> None:
        self.status = None

    def request(self, method, path, body=None, *, auth=True, expect="2xx", raw=False):
        if path == "/auth/me":
            return 200 if auth else 401
        if path == "/version":
            return {"version": "0.0.0", "git_sha": SHA}
        if path == "/projects":
            return {"id": "p1"}
        if path == "/runs":
            self.status = "AWAITING_PLAN"
            return {"run_id": "r1"}
        if path == "/runs/r1":
            return {"run": {"status": self.status}}
        if path == "/runs/r1/plan-review":
            self.status = "AWAITING_REVIEW"
            return {}
        if path == "/runs/r1/report-review":
            self.status = "COMPLETED"
            return {}
        if path == "/runs/r1/export.md":
            return b"# Report\n"
        if path == "/runs/r1/bundle.json":
            bundle = {
                "bundle_version": 2,
                "demo": True,
                "approval_chain": [{"action": "plan_approved"}, {"action": "approved"}],
                "evidence": [{"id": "e1"}],
            }
            return json.dumps(bundle).encode()
        if path == "/runs/r1/export.pdf":
            return 501
        raise AssertionError(f"the checker called {path}, which this engine does not serve")

    def tail(self, lines: int = 40) -> str:
        return ""

    def stop(self) -> None:
        pass


@pytest.fixture
def checker():
    return _load_checker()


@pytest.fixture
def pydantic_missing(monkeypatch):
    """The CI runner as it was: the repository's verifier is there, pydantic is not.

    The verifier and the bundle model are evicted so the import really runs again and stops
    where it did on the runner, at `from pydantic import …`. monkeypatch restores all three.
    """
    for name in ("research_engine.verify_bundle", "research_engine.bundle"):
        monkeypatch.delitem(sys.modules, name, raising=False)
    monkeypatch.setitem(sys.modules, "pydantic", None)


def _run(checker, monkeypatch, tmp_path, capsys, *flags: str) -> tuple[int, dict]:
    monkeypatch.setattr(checker, "Engine", _PackagedEngine)
    binary = tmp_path / "research-sidecar"
    binary.write_bytes(b"\0")
    code = checker.main(
        ["--bin", str(binary), "--min-tree-mb", "0", "--expect-sha", SHA, "--journey", *flags]
    )
    return code, json.loads(capsys.readouterr().out)


def test_a_required_verification_that_cannot_run_fails_the_check_and_says_why(
    checker, pydantic_missing, monkeypatch, tmp_path, capsys
):
    code, evidence = _run(checker, monkeypatch, tmp_path, capsys, "--require-verify")

    assert code == 1
    assert evidence["result"] == "FAIL"
    assert "--require-verify" in evidence["error"]
    assert "pydantic" in evidence["error"], evidence["error"]
    # Everything up to the verifier passed: the failure is the missing verification alone.
    assert evidence["checks"]["identity"] == "PASS"
    assert "journey" not in evidence["checks"]


def test_without_the_flag_the_same_run_passes_and_reports_the_verification_as_not_run(
    checker, pydantic_missing, monkeypatch, tmp_path, capsys
):
    """A person checking a published installer gets an honest NOT RUN, not a crash."""
    code, evidence = _run(checker, monkeypatch, tmp_path, capsys)

    assert code == 0
    assert evidence["result"] == "PASS"
    verdict = evidence["journey"]["verify_bundle"]
    assert verdict.startswith("NOT RUN") and "pydantic" in verdict, verdict
    # Beside the other checks too, where a reader skimming for PASS sees it isn't one.
    assert evidence["checks"]["verify_bundle"] == verdict


def test_the_required_verification_still_passes_a_valid_bundle_when_it_can_run(checker):
    """The positive control: the flag fails only a verification that did not run."""
    assert checker.verify_bundle(VALID_BUNDLE, required=True) == "PASS"


def test_the_flag_without_a_journey_is_refused_rather_than_ignored(checker, capsys):
    """No journey means no bundle to verify: accepting the flag would promise a check never run."""
    with pytest.raises(SystemExit) as exc:
        checker.main(["--bin", "x", "--require-verify"])
    assert exc.value.code == 2
    assert "--require-verify" in capsys.readouterr().err


def _checker_calls(step: dict) -> list[str]:
    script = step.get("run", "")
    # One logical command per call: join shell (`\`) and PowerShell (`` ` ``) continuations.
    joined = re.sub(r"[\\`]\n\s*", " ", script)
    return [line for line in joined.splitlines() if "scripts/check_packaged_sidecar.py" in line]


def test_every_ci_call_of_the_checker_requires_the_verification():
    jobs = yaml.safe_load(DESKTOP_YML.read_text(encoding="utf-8"))["jobs"].values()
    calls = [call for job in jobs for step in job["steps"] for call in _checker_calls(step)]

    # The installed .deb, the extracted AppImage and the installed .msi.
    assert len(calls) == 3, calls
    for call in calls:
        assert "--journey" in call and "--require-verify" in call, call


def test_the_shell_job_installs_the_verifiers_pydantic_from_the_backend_requirements():
    """One home for the version: the job reads `backend/requirements.txt`, never a literal."""
    steps = yaml.safe_load(DESKTOP_YML.read_text(encoding="utf-8"))["jobs"]["shell"]["steps"]
    installs = [s for s in steps if "pip install" in s.get("run", "")]

    assert len(installs) == 1, [s.get("name") for s in installs]
    (install,) = installs
    assert "backend/requirements.txt" in install["run"]
    literal = re.search(r"pydantic(\[[^\]]*\])?\s*[<>=!~]=?\s*\d", install["run"])
    assert not literal, f"a pydantic version written into CI: {literal.group(0)}"
    assert install.get("timeout-minutes"), "an unbounded install in the Shell job"
