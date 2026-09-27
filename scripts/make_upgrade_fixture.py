#!/usr/bin/env python3
"""
Write the v2.1.0 desktop upgrade fixture by driving a real v2.1.0 sidecar.

RG-4b / exit criterion 5 (internal/rfcs/V3.0-agentspec-scope.md §15.3, §24): a *populated*
v2.1.0 install must upgrade to V3 — not a fresh install, and not a schema produced by taking
columns back out of today's models. `tests/workflow/test_desktop_column_sync.py` builds its
"older" databases the second way, which proves `_add_missing_columns` handles a missing
column; it cannot prove that the file an actual v2.1.0 user holds is one V3 opens, because
nothing in it was written by v2.1.0.

So this runs the v2.1.0 sidecar itself — either from a checkout of the `v2.1.0` tag or the
frozen binary out of the v2.1.0 installer — and uses it the way a person would: first launch
(which seeds the demo session), saved preferences, a project, one run approved through both
gates and exported, and one run left waiting at the report gate. The databases it wrote are
copied out through SQLite's backup API, which copies pages rather than re-deriving rows, so
the committed files are what v2.1.0 wrote, with the WAL folded in.

    git worktree add --detach /tmp/v210 v2.1.0
    (cd /tmp/v210 && python scripts/stamp_build.py)
    python scripts/make_upgrade_fixture.py \\
        --sidecar "python -m desktop.sidecar" --cwd /tmp/v210/backend

    # or, from the installer's own binary:
    python scripts/make_upgrade_fixture.py \\
        --sidecar "/Volumes/Research Assistant/Research Assistant.app/Contents/Resources/sidecar/research-sidecar"

**It refuses to write a fixture from anything but v2.1.0.** The sidecar is asked what it
is (`GET /version`) and must answer version 2.1.0 at the tag's commit — stamping the
checkout first is what lets a source run answer that question at all. A fixture that
merely resembles v2.1.0 would prove the upgrade of a database nobody has.

**It never touches a real data directory.** The sidecar's default `--data-dir` is the
user's own `~/.research-engine`; this always passes a fresh temporary one, and the
environment is reduced to what an installed app has — no server variables, no provider
keys, and the null keyring backend so nothing reads the OS keychain.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import shlex
import signal
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = ROOT / "backend" / "tests" / "fixtures" / "upgrade" / "v2.1.0"

#: What the sidecar must report before anything it writes is kept. The commit is the
#: `v2.1.0` tag's (`git rev-parse v2.1.0^{commit}`), fixed here rather than read from git so
#: a moved tag cannot silently change what "v2.1.0" means.
EXPECTED_VERSION = "2.1.0"
EXPECTED_SHA = "4580ac06e7e5ef214b55fcad580e4a40b3689f30"

QUESTION = "What are the leading approaches to long-term memory in LLM agents?"
#: Preferences that existed in v2.1.0's `UserPreferences` (which forbids unknown keys), set
#: to non-defaults so the upgrade test can tell "kept" from "reset to default".
PREFERENCES = {"retrieval_k": 6, "density": "compact"}


def _env() -> dict[str, str]:
    """What an installed app runs with: none of the server's variables, no keys."""
    keep = ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "SYSTEMROOT", "USERPROFILE")
    env = {k: os.environ[k] for k in keep if k in os.environ}
    env["PYTHON_KEYRING_BACKEND"] = "keyring.backends.null.Keyring"
    return env


class Sidecar:
    def __init__(self, command: list[str], cwd: Path | None, data_dir: Path, log: Path) -> None:
        self._log = log
        self._out = log.open("w")
        self.proc = subprocess.Popen(  # noqa: S603 — the operator names the binary
            [*command, "--fake", "--data-dir", str(data_dir)],
            cwd=cwd,
            env=_env(),
            stdout=self._out,
            stderr=subprocess.STDOUT,
        )
        handshake = self._handshake()
        self.base = f"http://127.0.0.1:{handshake['port']}/api/v1"
        self.token = handshake["token"]
        self._await_socket()

    def _handshake(self) -> dict:
        for _ in range(120):
            for line in self._log.read_text().splitlines():
                if '"ready": true' in line:
                    return json.loads(line)
            if self.proc.poll() is not None:
                raise SystemExit(f"sidecar exited before its handshake:\n{self._log.read_text()}")
            time.sleep(0.5)
        raise SystemExit("sidecar printed no handshake within 60s")

    def _await_socket(self) -> None:
        # The handshake prints just before uvicorn binds (see desktop.yml's smoke).
        for _ in range(60):
            try:
                self.call("GET", "/auth/me")
                return
            except (urllib.error.URLError, ConnectionError):
                time.sleep(0.5)
        raise SystemExit("sidecar never accepted a connection")

    def call(self, method: str, path: str, body: dict | None = None) -> bytes:
        request = urllib.request.Request(  # noqa: S310 — loopback only
            self.base + path,
            method=method,
            data=None if body is None else json.dumps(body).encode(),
            headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
            return response.read()

    def json(self, method: str, path: str, body: dict | None = None):
        return json.loads(self.call(method, path, body))

    def await_run(self, run_id: str, wanted: str) -> None:
        for _ in range(360):
            status = self.json("GET", f"/runs/{run_id}")["run"]["status"]
            if status == wanted:
                return
            if status in {"FAILED", "CANCELLED"}:
                raise SystemExit(f"run {run_id} ended {status} while waiting for {wanted}")
            time.sleep(0.5)
        raise SystemExit(f"run {run_id} never reached {wanted}")

    def await_session(self, session_id: str, settled: set[str]) -> str:
        for _ in range(360):
            status = self.json("GET", f"/research/{session_id}")["status"]
            if status in settled:
                return status
            time.sleep(0.5)
        raise SystemExit(f"session {session_id} never settled into any of {sorted(settled)}")

    def stop(self) -> None:
        # SIGINT is uvicorn's graceful path: the lifespan exits and the checkpointer closes.
        self.proc.send_signal(signal.SIGINT)
        try:
            self.proc.wait(timeout=30)
        except subprocess.TimeoutExpired as err:
            self.proc.kill()
            raise SystemExit("sidecar did not shut down cleanly; no fixture was written") from err
        finally:
            self._out.close()


def _start_run(sidecar: Sidecar, project_id: str) -> str:
    created = sidecar.json(
        "POST",
        "/runs",
        {
            "project_id": project_id,
            "question": QUESTION,
            "depth": "fast",
            "skip_plan_gate": False,
            "dispatch": True,
        },
    )
    run_id = created["run_id"]
    sidecar.await_run(run_id, "AWAITING_PLAN")
    sidecar.call("POST", f"/runs/{run_id}/plan-review", {"decision": "APPROVED"})
    sidecar.await_run(run_id, "AWAITING_REVIEW")
    return run_id


def _populate(sidecar: Sidecar, out: Path) -> dict:
    version = sidecar.json("GET", "/version")
    if version.get("version") != EXPECTED_VERSION or version.get("git_sha") != EXPECTED_SHA:
        raise SystemExit(
            f"this sidecar is {version}, not v{EXPECTED_VERSION} at {EXPECTED_SHA}. A source "
            "checkout must be stamped first (python scripts/stamp_build.py)."
        )

    # First launch seeds the demo session inside the lifespan. It is kept in whatever state
    # v2.1.0 leaves it — recorded, not required: on a fresh install it ends FAILED, because
    # its `corpus_mode` default reads back as true on SQLite and the empty corpus yields no
    # evidence. That is v2.1.0's real first-launch state, so it is the state to upgrade.
    for _ in range(120):
        sessions = sidecar.json("GET", "/research")["sessions"]
        if sessions:
            break
        time.sleep(0.5)
    else:
        raise SystemExit("first launch seeded no demo session")
    demo_session = sessions[0]["session_id"]
    demo_status = sidecar.await_session(demo_session, {"COMPLETED", "FAILED"})

    sidecar.call("PATCH", "/auth/me", {"preferences": PREFERENCES})
    project_id = sidecar.json("POST", "/projects", {"name": "Upgrade fixture"})["id"]

    # Research recorded on the earlier pipeline stays readable and exportable in V3
    # (AGENTS.md: "Do not deepen the session path; do not delete it either").
    session = sidecar.json(
        "POST",
        "/research",
        {"query": QUESTION, "depth": "fast", "project_id": project_id, "corpus_mode": False},
    )["session_id"]
    sidecar.await_session(session, {"AWAITING_APPROVAL"})
    sidecar.call("POST", f"/research/{session}/approve", {"approved": True})
    if sidecar.await_session(session, {"COMPLETED", "FAILED"}) != "COMPLETED":
        raise SystemExit(f"session {session} did not complete")

    completed = _start_run(sidecar, project_id)
    sidecar.call("POST", f"/runs/{completed}/report-review", {"decision": "APPROVED"})
    sidecar.await_run(completed, "COMPLETED")
    # The artifacts a v2.1.0 user may already have exported and kept. The verifier must
    # still accept them, unchanged, after the app that produced them is gone.
    (out / "run-completed.bundle.json").write_bytes(
        sidecar.call("GET", f"/runs/{completed}/bundle.json")
    )
    (out / "session-completed.bundle.json").write_bytes(
        sidecar.call("GET", f"/research/{session}/export.bundle.json")
    )

    # Upgrading while a run waits at a gate is the ordinary case, not an edge one: the
    # gate can wait for days, and the app updates underneath it.
    waiting = _start_run(sidecar, project_id)

    return {
        "sidecar": {"version": version["version"], "git_sha": version["git_sha"]},
        "demo_session_id": demo_session,
        "demo_session_status": demo_status,
        "session_completed_id": session,
        "project_id": project_id,
        "run_completed_id": completed,
        "run_awaiting_review_id": waiting,
        "preferences": PREFERENCES,
    }


def _copy_databases(data_dir: Path, out: Path) -> dict[str, dict[str, int]]:
    """Copy every SQLite file through the backup API and count what each table holds."""
    counts: dict[str, dict[str, int]] = {}
    for source in sorted(data_dir.glob("*.sqlite")):
        target = out / source.name
        target.unlink(missing_ok=True)
        with sqlite3.connect(source) as src, sqlite3.connect(target) as dst:
            src.backup(dst)
        with sqlite3.connect(target) as dst:
            dst.execute("PRAGMA journal_mode=DELETE")
            tables = [
                r[0]
                for r in dst.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' "
                    "ORDER BY name"
                )
            ]
            counts[source.name] = {
                t: dst.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]  # noqa: S608
                for t in tables
            }
    for extra in sorted(data_dir.glob("*.json")):
        (out / extra.name).write_bytes(extra.read_bytes())
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--sidecar", required=True, help="command that starts the v2.1.0 sidecar")
    parser.add_argument("--cwd", type=Path, help="working directory (a checkout's backend/)")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    command = shlex.split(args.sidecar)
    args.out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="v210-install-") as scratch:
        data_dir = Path(scratch) / "data"
        data_dir.mkdir()
        sidecar = Sidecar(command, args.cwd, data_dir, Path(scratch) / "sidecar.log")
        try:
            facts = _populate(sidecar, args.out)
        finally:
            sidecar.stop()
        counts = _copy_databases(data_dir, args.out)

    # A source run is recognised by its working directory; a frozen binary is recorded by its
    # own digest, so the manifest names exactly which installer's engine wrote the files.
    if args.cwd:
        launched = {"launched_as": "source checkout of the v2.1.0 tag"}
    else:
        digest = hashlib.sha256(Path(command[0]).read_bytes()).hexdigest()
        launched = {"launched_as": "frozen v2.1.0 binary", "binary_sha256": digest}
    manifest = {
        "generated_by": "scripts/make_upgrade_fixture.py",
        "generated_at": dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat(),
        **launched,
        **facts,
        "row_counts": counts,
        "files": {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(args.out.iterdir())
            if p.name != "MANIFEST.json"
        },
    }
    (args.out / "MANIFEST.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"wrote the v{EXPECTED_VERSION} upgrade fixture to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
