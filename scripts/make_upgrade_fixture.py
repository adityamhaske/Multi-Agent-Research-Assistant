#!/usr/bin/env python3
"""
Write a desktop upgrade fixture by driving the real sidecar of a released version.

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

**`--release 3.0.2`** writes `tests/fixtures/upgrade/v3.0.2-populated/` the same way, from a
checkout of `v3.0.2`. That is RFC V3.1 AC-23's populated store: the last shared corpus a
desktop user can hold before 3.1 moves it into a project of its own. On top of the v2.1.0
journey it uploads every kind 3.0.2 reads (PDF, HTML, Markdown, text) under two projects,
re-uploads one file so the store holds a superseded version, and approves a corpus-only run
so its report is saved into the corpus as a generated document. 3.0.2 embeds with local
Ollama even under `--fake`, as a 3.0.2 user's corpus was, so `nomic-embed-text` must be
running.

    git worktree add --detach "$TMP/v302" v3.0.2
    (cd "$TMP/v302" && python scripts/stamp_build.py)
    python scripts/make_upgrade_fixture.py --release 3.0.2 \\
        --sidecar "python -m desktop.sidecar" --cwd "$TMP/v302/backend"

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
UPGRADE = ROOT / "backend" / "tests" / "fixtures" / "upgrade"

#: What the sidecar must report before anything it writes is kept, and where it goes. Each
#: commit is its tag's (`git rev-parse vX.Y.Z^{commit}`), fixed here rather than read from git
#: so a moved tag cannot silently change what the version means.
RELEASES = {
    "2.1.0": {"sha": "4580ac06e7e5ef214b55fcad580e4a40b3689f30", "out": UPGRADE / "v2.1.0"},
    "3.0.2": {
        "sha": "0a9de70ee90485531120856fce7f5dde4041c0aa",
        "out": UPGRADE / "v3.0.2-populated",
    },
}
FORMATS = ROOT / "backend" / "tests" / "fixtures" / "formats"

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

    def upload(self, project_id: str, filename: str, data: bytes, doc_key: str | None = None):
        """A multipart upload. `doc_key` makes it a revision of that document, which is the
        only way 3.0.2 supersedes one; without it a re-upload is a second document."""
        boundary = "fixture-boundary-7d1f"
        body = b""
        if doc_key:
            body += (
                f"--{boundary}\r\nContent-Disposition: form-data; name=\"doc_key\"\r\n\r\n"
                f"{doc_key}\r\n"
            ).encode()
        body += (
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
            f'filename="{filename}"\r\nContent-Type: application/octet-stream\r\n\r\n'
        ).encode() + data + f"\r\n--{boundary}--\r\n".encode()
        request = urllib.request.Request(  # noqa: S310 — loopback only
            f"{self.base}/projects/{project_id}/corpus/documents",
            method="POST",
            data=body,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": f"multipart/form-data; boundary={boundary}",
            },
        )
        with urllib.request.urlopen(request, timeout=120) as response:  # noqa: S310
            return json.loads(response.read())

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


def _populate_corpus(sidecar: Sidecar, project_id: str) -> dict:
    """A 3.0.2 shared corpus as a user would have it (RFC V3.1 AC-23).

    The four kinds 3.0.2 reads, split across two projects: 3.0.2 put them all in one store,
    which is what 3.1 has to move without losing or mixing any. A re-upload leaves a
    superseded version, and an approved corpus-only run adds its report as a generated one.
    """
    other = sidecar.json("POST", "/projects", {"name": "Second project"})["id"]
    uploaded, keys = {}, {}
    for name, owner in (
        ("paper.pdf", project_id),
        ("page.html", project_id),
        ("notes.md", other),
        ("notes.txt", other),
    ):
        doc = sidecar.upload(owner, name, (FORMATS / name).read_bytes())
        uploaded[name], keys[name] = doc["id"], doc["doc_key"]
    revised = (FORMATS / "notes.txt").read_bytes() + b"Attendance fell in 2022.\n"
    uploaded["notes.txt (v2)"] = sidecar.upload(
        other, "notes.txt", revised, doc_key=keys["notes.txt"]
    )["id"]

    created = sidecar.json(
        "POST",
        "/runs",
        {
            "project_id": project_id,
            "question": "How did enrolment change in 2021?",
            "depth": "fast",
            "corpus_mode": True,
            "skip_plan_gate": True,
            "dispatch": True,
        },
    )
    corpus_run = created["run_id"]
    sidecar.await_run(corpus_run, "AWAITING_REVIEW")
    sidecar.call("POST", f"/runs/{corpus_run}/report-review", {"decision": "APPROVED"})
    sidecar.await_run(corpus_run, "COMPLETED")
    return {"second_project_id": other, "documents": uploaded, "corpus_run_id": corpus_run}


def _populate(sidecar: Sidecar, out: Path, release: str) -> dict:
    version = sidecar.json("GET", "/version")
    expected_sha = RELEASES[release]["sha"]
    if version.get("version") != release or version.get("git_sha") != expected_sha:
        raise SystemExit(
            f"this sidecar is {version}, not v{release} at {expected_sha}. A source "
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
    corpus = _populate_corpus(sidecar, project_id) if release != "2.1.0" else {}

    return {
        "sidecar": {"version": version["version"], "git_sha": version["git_sha"]},
        "demo_session_id": demo_session,
        "demo_session_status": demo_status,
        "session_completed_id": session,
        "project_id": project_id,
        "run_completed_id": completed,
        "run_awaiting_review_id": waiting,
        "preferences": PREFERENCES,
        **corpus,
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
    parser.add_argument("--release", choices=sorted(RELEASES), default="2.1.0")
    parser.add_argument("--sidecar", required=True, help="command that starts that sidecar")
    parser.add_argument("--cwd", type=Path, help="working directory (a checkout's backend/)")
    parser.add_argument("--out", type=Path, help="default: the release's fixture directory")
    args = parser.parse_args()
    release = args.release
    args.out = args.out or RELEASES[release]["out"]

    command = shlex.split(args.sidecar)
    args.out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f"v{release}-install-") as scratch:
        data_dir = Path(scratch) / "data"
        data_dir.mkdir()
        sidecar = Sidecar(command, args.cwd, data_dir, Path(scratch) / "sidecar.log")
        try:
            facts = _populate(sidecar, args.out, release)
        finally:
            sidecar.stop()
        counts = _copy_databases(data_dir, args.out)

    # A source run is recognised by its working directory; a frozen binary is recorded by its
    # own digest, so the manifest names exactly which installer's engine wrote the files.
    if args.cwd:
        launched = {"launched_as": f"source checkout of the v{release} tag"}
    else:
        digest = hashlib.sha256(Path(command[0]).read_bytes()).hexdigest()
        launched = {"launched_as": f"frozen v{release} binary", "binary_sha256": digest}
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
    print(f"wrote the v{release} upgrade fixture to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
