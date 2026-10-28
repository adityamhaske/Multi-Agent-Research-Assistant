"""
`check_packaged_sidecar.py --ingest-fixtures` reads every shipped format through an engine's
own routes and compares the text with the source tree's (RFC V3.1 AC-17, AC-25; gate G-1).

Driven end to end against the engine launched from this checkout, through a one-line
wrapper standing where a packaged `research-sidecar` would. The same checker, the same
fixtures and the same `goldens.json` then run against each frozen engine in `desktop.yml`.
A planted wrong golden must fail and name the fixture, or a mismatch on a frozen build would
pass silently.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
CHECKER = ROOT / "scripts" / "check_packaged_sidecar.py"
FIXTURES = ROOT / "backend" / "tests" / "fixtures" / "formats"

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="the wrapper is a POSIX script")


def _checker():
    spec = importlib.util.spec_from_file_location("check_packaged_sidecar", CHECKER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def engine_from_source(tmp_path) -> Path:
    wrapper = tmp_path / "bin" / "research-sidecar"
    wrapper.parent.mkdir()
    wrapper.write_text(
        f'#!/bin/sh\ncd "{ROOT / "backend"}" && exec "{sys.executable}" -m desktop.sidecar "$@"\n',
        encoding="utf-8",
    )
    wrapper.chmod(0o755)
    return wrapper


def _run(binary: Path, fixtures: Path, out: Path) -> tuple[int, dict]:
    code = _checker().main(
        [
            "--bin",
            str(binary),
            "--min-tree-mb",
            "0",
            "--ingest-fixtures",
            str(fixtures),
            "--json",
            str(out),
        ]
    )
    return code, json.loads(out.read_text(encoding="utf-8"))


def test_every_format_reads_the_same_through_the_engine(engine_from_source, tmp_path):
    code, evidence = _run(engine_from_source, FIXTURES, tmp_path / "evidence.json")

    assert code == 0, evidence.get("error")
    goldens = json.loads((FIXTURES / "goldens.json").read_text(encoding="utf-8"))
    assert evidence["ingest"]["formats"] == goldens
    assert evidence["ingest"]["cited"] >= 1, "the ingested files were searched and cited"
    assert evidence["checks"]["ingest_fixtures"] == "PASS"


def test_a_format_that_reads_differently_fails_and_names_it(engine_from_source, tmp_path):
    planted = tmp_path / "formats"
    shutil.copytree(FIXTURES, planted)
    goldens = json.loads((planted / "goldens.json").read_text(encoding="utf-8"))
    goldens["report.docx"]["sha256"] = "0" * 64
    (planted / "goldens.json").write_text(json.dumps(goldens), encoding="utf-8")

    code, evidence = _run(engine_from_source, planted, tmp_path / "evidence.json")

    assert code == 1
    assert evidence["result"] == "FAIL"
    assert "report.docx" in evidence["error"]
    assert "paper.pdf" not in evidence["error"], "only the format that differs is named"
