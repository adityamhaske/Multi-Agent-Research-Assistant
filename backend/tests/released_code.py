"""
The engine package exactly as a released version shipped it, for compatibility tests.

RFC V3.1 D-20 and AC-24 ask whether *the shipped* code accepts what 3.1 writes, so the old code
must be the tag's bytes, never this checkout's. `git archive` unpacks it, and each test runs
it in a separate interpreter so nothing from this checkout can stand in for it.

Where the tag is missing (a shallow clone with no tags), the test skips locally and **fails
in CI**. `ci.yml` fetches the tag for these tests, so a missing tag there is a broken job,
not a reason to report a compatibility check that never ran.
"""

from __future__ import annotations

import io
import os
import shutil
import subprocess
import tarfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


def released_engine(tag: str, dest: Path) -> Path:
    """Unpack `backend/research_engine` as of `tag` under `dest`; return the dir to put on
    `sys.path` (the package's parent)."""
    git = shutil.which("git")
    archived = (
        subprocess.run(
            [git, "archive", "--format=tar", tag, "backend/research_engine"],
            capture_output=True,
            cwd=REPO,
        )
        if git
        else None
    )
    if archived is None or archived.returncode != 0:
        reason = f"the {tag} tag is not in this checkout"
        if os.environ.get("CI"):
            pytest.fail(f"{reason}; ci.yml fetches it for this test")
        pytest.skip(f"{reason} (shallow clone)")
    with tarfile.open(fileobj=io.BytesIO(archived.stdout)) as tar:
        tar.extractall(dest, filter="data")
    return dest / "backend"
