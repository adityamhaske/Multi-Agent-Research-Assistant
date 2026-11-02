#!/usr/bin/env python3
"""Bundles from real selected-files runs, for gate G-4 (internal/rfcs/V3.1-corpus-scope.md
§14.1, D-20).

G-4 runs the unchanged v3.0.2 verifier against "bundles a real 3.1 selection run produced",
so these come from the desktop engine's own routes, on real models, approved at the review
gate the way a person approves one. The engine runs as a separate process with a scratch data
directory and no keychain (`PYTHON_KEYRING_BACKEND` null), so it reads the key and routing
from the environment and touches nothing of the user's.

    python scripts/gates/g4_real_bundles.py --out <dir> \\
        [--engine "python -m desktop.sidecar"]   # or the packaged research-sidecar binary

Each bundle is written as `bundle-<n>.json` beside `runs.json`, which records the run, its
selection, its grounding report status and the engine's `/api/v1/version`. Pass the bundles
to `g4_bundle_compat.py`.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FORMATS = ROOT / "backend" / "tests" / "fixtures" / "formats"

#: (question, files selected, folder they are filed in). Two runs, two kinds of selection: one
#: file, and a mixed folder of several formats.
RUNS = [
    ("What does the report say about enrolment?", ["report.docx"], "Reports"),
    (
        "What do these files say about the budget and enrolment figures?",
        ["budget.xlsx", "enrolment.csv", "notes.md"],
        "Mixed/Figures",
    ),
]


class Engine:
    def __init__(self, command: list[str], data_dir: Path):
        env = {**os.environ, "PYTHON_KEYRING_BACKEND": "keyring.backends.null.Keyring"}
        self.proc = subprocess.Popen(
            [*command, "--data-dir", str(data_dir)],
            cwd=ROOT / "backend",
            env=env,
            stdout=subprocess.PIPE,
            text=True,
        )
        handshake = json.loads(self.proc.stdout.readline())
        self.base = f"http://127.0.0.1:{handshake['port']}/api/v1"
        self.token = handshake["token"]
        # Keep reading what the engine logs after the handshake, so its writes never block
        # or break, and wait until it answers: the handshake is printed before it listens.
        threading.Thread(target=lambda: [None for _ in self.proc.stdout], daemon=True).start()
        deadline = time.monotonic() + 120
        while True:
            try:
                self.call("GET", "/version")
                break
            except OSError:
                if time.monotonic() > deadline:
                    raise
                time.sleep(1)

    def call(self, method: str, path: str, body=None, raw: bytes | None = None, ctype=None):
        headers = {"Authorization": f"Bearer {self.token}"}
        data = raw
        if body is not None:
            data, headers["Content-Type"] = json.dumps(body).encode(), "application/json"
        elif ctype:
            headers["Content-Type"] = ctype
        req = urllib.request.Request(self.base + path, data=data, method=method, headers=headers)
        with urllib.request.urlopen(req, timeout=600) as resp:
            return json.loads(resp.read() or b"null")

    def upload(self, project: str, path: Path, folder: str) -> dict:
        boundary = uuid.uuid4().hex
        parts = [
            ('name="relative_path"', f"{folder}/{path.name}".encode()),
            (f'name="file"; filename="{path.name}"', path.read_bytes()),
        ]
        body = b""
        for disposition, value in parts:
            body += (
                f"--{boundary}\r\nContent-Disposition: form-data; {disposition}\r\n\r\n".encode()
                + value
                + b"\r\n"
            )
        body += f"--{boundary}--\r\n".encode()
        return self.call(
            "POST",
            f"/projects/{project}/corpus/documents",
            raw=body,
            ctype=f"multipart/form-data; boundary={boundary}",
        )

    def await_status(self, run_id: str, wanted: set[str], timeout: float = 1800) -> dict:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            run = self.call("GET", f"/runs/{run_id}")["run"]
            if run["status"] in wanted | {"FAILED", "CANCELLED"}:
                return run
            time.sleep(5)
        raise TimeoutError(f"run {run_id} never reached {wanted}")

    def stop(self) -> None:
        self.proc.terminate()
        self.proc.wait(timeout=30)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--engine", default=f"{sys.executable} -m desktop.sidecar")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    data = Path(tempfile.mkdtemp(prefix="g4-data-"))
    # No demo run: it would spend model calls on a scripted question nobody reads.
    (data / "demo_seeded.json").write_text(json.dumps({"seeded": True}), encoding="utf-8")
    engine = Engine(shlex.split(args.engine), data)
    record = {"engine": engine.call("GET", "/version"), "runs": []}
    try:
        project = engine.call("POST", "/projects", {"name": f"G-4 {uuid.uuid4().hex[:6]}"})["id"]
        for n, (question, files, folder) in enumerate(RUNS, start=1):
            docs = [engine.upload(project, FORMATS / f, folder) for f in files]
            created = engine.call(
                "POST",
                "/runs",
                {
                    "project_id": project,
                    "question": question,
                    "depth": "fast",
                    "corpus_selection": {"doc_keys": [d["doc_key"] for d in docs]},
                    "skip_plan_gate": True,
                },
            )
            run_id = created["run_id"]
            run = engine.await_status(run_id, {"AWAITING_REVIEW"})
            entry = {
                "run_id": run_id,
                "question": question,
                "files": [f"{folder}/{f}" for f in files],
                "status_at_gate": run["status"],
                "error": run.get("error_message"),
                "grounding_status": (run.get("grounding_report") or {}).get("status"),
                "model_routing": run.get("model_routing"),
            }
            if run["status"] == "AWAITING_REVIEW":
                engine.call("POST", f"/runs/{run_id}/report-review", {"decision": "APPROVED"})
                run = engine.await_status(run_id, {"COMPLETED"})
                bundle = engine.call("GET", f"/runs/{run_id}/bundle.json")
                path = args.out / f"bundle-{n}.json"
                path.write_text(json.dumps(bundle, indent=1), encoding="utf-8")
                entry |= {"bundle": path.name, "bundle_hash": bundle.get("bundle_hash")}
            entry["final_status"] = run["status"]
            record["runs"].append(entry)
            print(json.dumps(entry), flush=True)
    finally:
        engine.stop()
    (args.out / "runs.json").write_text(json.dumps(record, indent=1), encoding="utf-8")
    return 0 if all(r.get("bundle") for r in record["runs"]) else 1


if __name__ == "__main__":
    sys.exit(main())
