"""
`tests/fixtures/formats/goldens.json` — what each format fixture extracts to, as a hash a
packaged engine can be checked against (RFC V3.1 AC-17, AC-25; gate G-1).

The tier tests pin each fixture's canonical text exactly, but only against the extractor in
this checkout. A frozen desktop engine carries its own copy of every parser, and AC-17 asks
for byte-identical text across hosts and builds. `scripts/check_packaged_sidecar.py
--ingest-fixtures` uploads each fixture through a launched engine and compares what its
`/text` route returns with this file. That checker is standard-library only, so the golden
is data rather than a Python dict in a test.

This module keeps the file honest:
- it is exactly what the shipped extractor produces;
- it covers every fixture in the directory;
- it covers every kind the format registry accepts, so a new format cannot ship unchecked.

**Regenerating.** `GOLDEN_RECORD=1 python -m pytest tests/task/test_format_goldens.py`
rewrites the file from this checkout. Read the diff first: a changed hash is a change to
which quotes verify against that format.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

from research_engine.documents import FORMATS, extract

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "formats"
GOLDENS = FIXTURES / "goldens.json"


def _measure(name: str) -> dict:
    result = extract(name, (FIXTURES / name).read_bytes())
    return {
        "kind": result.kind,
        "mode": result.mode,
        "chars": len(result.text),
        "sha256": hashlib.sha256(result.text.encode("utf-8")).hexdigest(),
    }


def _fixtures() -> list[str]:
    return sorted(p.name for p in FIXTURES.iterdir() if p.is_file() and p.name != GOLDENS.name)


def test_the_goldens_are_what_the_shipped_extractor_produces():
    measured = {name: _measure(name) for name in _fixtures()}
    if os.environ.get("GOLDEN_RECORD") == "1":
        GOLDENS.write_text(json.dumps(measured, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        pytest.skip("goldens rewritten; review the diff")
    assert json.loads(GOLDENS.read_text(encoding="utf-8")) == measured


def test_every_kind_the_registry_accepts_has_a_fixture():
    covered = {entry["kind"] for entry in json.loads(GOLDENS.read_text(encoding="utf-8")).values()}
    assert {f.kind for f in FORMATS.values()} <= covered
