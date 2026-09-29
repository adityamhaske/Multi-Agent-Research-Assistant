#!/usr/bin/env python3
"""
Launch the research engine out of a *packaged* desktop build and check it is the build it
claims to be — and, with `--journey`, that it can still carry research through both gates.

The desktop's documented failure is a green build that dies on first launch: three copies of
the sidecar's location wrong at once, a 5 MB bundle with no engine inside, every CI step
passing (AGENTS.md, "two hosts, one contract"). `desktop.yml` already drives the raw
PyInstaller output on all three OSes, and the copy inside the macOS `.app`. It never looked
inside the `.msi`, the `.deb` or the AppImage — so "Windows passed CI" meant "the MSI
compiled", not "the engine an installed copy launches works". This is the one checker for all
of them, used by CI on the installers it builds and by a person on the installers a release
published (RELEASE.md, phases 6-9).

    # the engine inside an installed or extracted build, found by name under a directory
    python scripts/check_packaged_sidecar.py --search "/Applications/Research Assistant.app" \\
        --expect-sha <tag commit> --expect-version 3.0.1 --journey

    # or a binary you already located
    python scripts/check_packaged_sidecar.py --bin path/to/research-sidecar --expect-sha <sha>

**It never touches a real data directory.** The sidecar's default is `~/.research-engine`;
this always passes a fresh temporary one, runs `--fake` (scripted models, no keys, nothing
spent), and removes the three server variables an installed app never has — `app.config`
builds `Settings` at import, so a stray `DATABASE_URL` in the checker's environment would
make a broken bundle look healthy.

Standard library only, so it runs on a CI image or a clean laptop with no project installed.
The one optional import is the bundle verifier, which needs `pydantic`; when that is missing
the verdict is reported as not run rather than as a pass.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NAMES = ("research-sidecar", "research-sidecar.exe")
# The same floor desktop.yml applies to the tree it builds: a real engine is 140-200 MB,
# the documented failure is ~5 MB, and 60 MB sits far from both.
DEFAULT_MIN_TREE_MB = 60
QUESTION = "What are the leading approaches to long-term memory in LLM agents?"


class CheckFailed(Exception):
    """A check that ran and found the build wrong — distinct from one that could not run."""


def find_binary(root: Path) -> Path:
    for dirpath, _dirs, files in os.walk(root):
        for name in NAMES:
            if name in files:
                return Path(dirpath) / name
    raise CheckFailed(f"no {' or '.join(NAMES)} anywhere under {root}")


def tree_size_mb(directory: Path) -> float:
    total = 0
    for dirpath, _dirs, files in os.walk(directory):
        for name in files:
            try:
                total += (Path(dirpath) / name).stat().st_size
            except OSError:
                continue
    return total / (1024 * 1024)


class Engine:
    """One launched sidecar, its handshake, and a tiny authenticated HTTP client."""

    def __init__(self, binary: Path, data_dir: Path, startup_timeout: float) -> None:
        env = {
            k: v
            for k, v in os.environ.items()
            if k not in ("DATABASE_URL", "JWT_SECRET_KEY", "REDIS_URL")
        }
        self.log: list[str] = []
        self.proc = subprocess.Popen(  # noqa: S603 — the binary under test, by design
            [str(binary), "--fake", "--data-dir", str(data_dir)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
        )
        self.handshake: dict | None = None
        ready = threading.Event()

        def pump() -> None:
            assert self.proc.stdout is not None
            for line in self.proc.stdout:
                self.log.append(line.rstrip())
                if self.handshake is None and '"ready"' in line:
                    try:
                        payload = json.loads(line.strip())
                    except ValueError:
                        continue
                    if payload.get("ready") is True:
                        self.handshake = payload
                        ready.set()

        threading.Thread(target=pump, daemon=True).start()
        deadline = time.monotonic() + startup_timeout
        while not ready.wait(0.5):
            if self.proc.poll() is not None:
                raise CheckFailed(
                    f"the engine exited with {self.proc.returncode} before its handshake:\n"
                    + self.tail()
                )
            if time.monotonic() > deadline:
                raise CheckFailed(f"no handshake within {startup_timeout:.0f}s:\n" + self.tail())
        assert self.handshake is not None
        self.base = f"http://127.0.0.1:{self.handshake['port']}/api/v1"
        self.token = self.handshake["token"]
        # The handshake prints just before uvicorn binds, so wait for the socket itself.
        for _ in range(60):
            if self.request("GET", "/auth/me", auth=False, expect=None) is not None:
                return
            time.sleep(0.5)
        raise CheckFailed("the handshake arrived but the port never answered:\n" + self.tail())

    def tail(self, lines: int = 40) -> str:
        return "\n".join(self.log[-lines:])

    def request(
        self,
        method: str,
        path: str,
        body: dict | None = None,
        *,
        auth: bool = True,
        expect: int | str | None = "2xx",
        raw: bool = False,
    ):
        """One call. `expect="2xx"` accepts any success, as `curl -f` does in desktop.yml;
        `expect=None` returns the status code, or None if nothing answered at all."""
        headers = {"Content-Type": "application/json"}
        if auth:
            headers["Authorization"] = f"Bearer {self.token}"
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 — loopback only
                status, payload = resp.status, resp.read()
        except urllib.error.HTTPError as exc:
            status, payload = exc.code, exc.read()
        except (urllib.error.URLError, ConnectionError, TimeoutError):
            if expect is None:
                return None
            raise
        if expect is None:
            return status
        if not (200 <= status < 300 if expect == "2xx" else status == expect):
            raise CheckFailed(
                f"{method} {path} answered {status}, expected {expect}: {payload[:300]!r}"
            )
        if raw:
            return payload
        return json.loads(payload) if payload else None

    def stop(self) -> None:
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=15)


def await_status(engine: Engine, run_id: str, want: str, timeout: float = 240) -> None:
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        last = engine.request("GET", f"/runs/{run_id}")["run"]["status"]
        if last == want:
            return
        if last in ("FAILED", "CANCELLED"):
            raise CheckFailed(f"run {run_id} ended {last} while waiting for {want}")
        time.sleep(1)
    raise CheckFailed(f"run {run_id} never reached {want} (last: {last})")


def verify_bundle(path: Path) -> str:
    """The standalone verifier's verdict, or an honest statement that it did not run."""
    sys.path.insert(0, str(ROOT / "backend"))
    try:
        from research_engine.verify_bundle import main as verify_main  # noqa: PLC0415
    except ImportError as exc:
        return f"NOT RUN — the verifier could not be imported here ({exc})"
    code = verify_main([str(path)])
    if code != 0:
        raise CheckFailed(f"verify_bundle refused the bundle the packaged engine produced ({code})")
    return "PASS"


def journey(engine: Engine, scratch: Path) -> dict:
    """Create → plan gate → report gate → export → bundle, as desktop.yml drives it."""
    project = engine.request("POST", "/projects", {"name": "Packaged-app check"})["id"]
    run = engine.request(
        "POST",
        "/runs",
        {
            "project_id": project,
            "question": QUESTION,
            "depth": "fast",
            "skip_plan_gate": False,
            "dispatch": True,
        },
    )["run_id"]
    await_status(engine, run, "AWAITING_PLAN")
    engine.request("POST", f"/runs/{run}/plan-review", {"decision": "APPROVED"})
    await_status(engine, run, "AWAITING_REVIEW")
    engine.request("POST", f"/runs/{run}/report-review", {"decision": "APPROVED"})

    report = engine.request("GET", f"/runs/{run}/export.md", raw=True)
    if not report.strip():
        raise CheckFailed("the approved run exported an empty Markdown report")
    bundle_bytes = engine.request("GET", f"/runs/{run}/bundle.json", raw=True)
    bundle_path = scratch / "packaged.bundle.json"
    bundle_path.write_bytes(bundle_bytes)
    bundle = json.loads(bundle_bytes)
    actions = [a["action"] for a in bundle.get("approval_chain", [])]
    if "approved" not in actions:
        raise CheckFailed(f"no report approval in the bundle's approval chain: {actions}")
    if not bundle.get("evidence"):
        raise CheckFailed("the packaged engine produced a bundle with no evidence")
    if bundle.get("demo") is not True:
        raise CheckFailed("a scripted (--fake) run was not stamped as a demo")
    # PDF export is deliberately absent on this host (WeasyPrint is excluded from the
    # bundle); a 200 would mean the exclusion stopped working.
    pdf = engine.request("GET", f"/runs/{run}/export.pdf", expect=None)
    if pdf != 501:
        raise CheckFailed(f"expected 501 for the desktop PDF export, got {pdf}")
    return {
        "run_id": run,
        "approval_chain": actions,
        "evidence": len(bundle["evidence"]),
        "bundle_version": bundle.get("bundle_version"),
        "verify_bundle": verify_bundle(bundle_path),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    where = parser.add_mutually_exclusive_group(required=True)
    where.add_argument("--bin", type=Path, help="the research-sidecar executable")
    where.add_argument("--search", type=Path, help="find research-sidecar[.exe] under here")
    parser.add_argument("--expect-sha", help="the commit the build must report")
    parser.add_argument("--expect-version", help="the version the build must report")
    parser.add_argument("--min-tree-mb", type=float, default=DEFAULT_MIN_TREE_MB)
    parser.add_argument("--journey", action="store_true", help="also drive a research run")
    parser.add_argument("--startup-timeout", type=float, default=180)
    parser.add_argument("--json", type=Path, help="write the evidence here")
    args = parser.parse_args(argv)

    evidence: dict = {"checks": {}}
    engine: Engine | None = None
    scratch = Path(tempfile.mkdtemp(prefix="packaged-sidecar-"))
    try:
        binary = args.bin if args.bin else find_binary(args.search)
        if not binary.is_file():
            raise CheckFailed(f"{binary} does not exist")
        evidence["binary"] = str(binary)
        size = tree_size_mb(binary.parent)
        evidence["tree_mb"] = round(size, 1)
        if size < args.min_tree_mb:
            raise CheckFailed(
                f"the engine's directory is {size:.1f} MB, below the {args.min_tree_mb} MB floor "
                "— too small to contain the engine"
            )
        evidence["checks"]["tree_size"] = "PASS"

        engine = Engine(binary, scratch / "data", args.startup_timeout)
        evidence["checks"]["launch"] = "PASS"

        # The desktop's whole security boundary is the per-launch token.
        unauth = engine.request("GET", "/auth/me", auth=False, expect=None)
        if unauth != 401:
            raise CheckFailed(f"an unauthenticated request answered {unauth}, not 401")
        engine.request("GET", "/auth/me")
        evidence["checks"]["token_gate"] = "PASS"

        info = engine.request("GET", "/version")
        evidence["version"] = info
        if args.expect_sha and info.get("git_sha") != args.expect_sha:
            raise CheckFailed(
                f"the packaged engine reports git_sha={info.get('git_sha')}, "
                f"expected {args.expect_sha}"
            )
        if args.expect_version and info.get("version") != args.expect_version:
            raise CheckFailed(
                f"the packaged engine reports version={info.get('version')}, "
                f"expected {args.expect_version}"
            )
        evidence["checks"]["identity"] = (
            "PASS"
            if (args.expect_sha or args.expect_version)
            else ("NOT CHECKED — no --expect-sha/--expect-version given")
        )

        if args.journey:
            evidence["journey"] = journey(engine, scratch)
            evidence["checks"]["journey"] = "PASS"
        evidence["result"] = "PASS"
    except CheckFailed as exc:
        evidence["result"] = "FAIL"
        evidence["error"] = str(exc)
        if engine is not None:
            evidence["log_tail"] = engine.tail()
    finally:
        if engine is not None:
            engine.stop()
        shutil.rmtree(scratch, ignore_errors=True)

    print(json.dumps(evidence, indent=2))
    if args.json:
        args.json.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    return 0 if evidence["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
