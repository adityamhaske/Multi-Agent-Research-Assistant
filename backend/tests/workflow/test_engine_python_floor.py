"""
The engine refuses a Python older than its floor, by name (`research_engine/__init__.py`).

Run from a checkout — how a third party runs `python -m research_engine.verify_bundle` — no
installer applies `requires-python`, so without the guard an older interpreter stops at a
SyntaxError in syntax it does not know. CI runs only the floor itself, so the interpreter is
simulated: the package's `__init__` runs against a patched `sys.version_info`.
"""

from __future__ import annotations

import re
import runpy
import sys
from pathlib import Path

import pytest

ENGINE = Path(__file__).resolve().parents[2] / "research_engine"
FLOOR = tuple(
    int(n)
    for n in re.search(
        r'^requires-python = ">=(\d+)\.(\d+)"',
        (ENGINE / "pyproject.toml").read_text(encoding="utf-8"),
        re.M,
    ).groups()
)


def _run_init_as(monkeypatch, version: tuple[int, int, int]) -> None:
    monkeypatch.setattr(sys, "version_info", (*version, "final", 0))
    monkeypatch.setattr(sys, "version", ".".join(map(str, version)) + " (main) [simulated]")
    runpy.run_path(str(ENGINE / "__init__.py"))


def test_a_python_below_the_floor_is_refused_with_the_floor_it_needs(monkeypatch):
    major, minor = FLOOR
    # A RuntimeError, not an ImportError: `check_packaged_sidecar.py` reads an ImportError as
    # "the verifier could not be imported here" and carries on without verifying.
    with pytest.raises(
        RuntimeError, match=rf"needs Python {major}\.{minor}\+, this is {major}\.{minor - 1}\.9$"
    ):
        _run_init_as(monkeypatch, (major, minor - 1, 9))


def test_the_floor_itself_is_accepted(monkeypatch):
    _run_init_as(monkeypatch, (*FLOOR, 0))
