#!/usr/bin/env python3
"""
Gate G-3: the released 3.0.2 app opens 3.1 data (internal/rfcs/V3.1-corpus-scope.md §14.1,
§16 rollback).

Downgrading to 3.0.x is supported on read. Two commands:

    # build the three 3.1 data directories with this checkout
    python scripts/gates/g3_downgrade_open.py prepare OUT

    # launch a released 3.0.2 engine on a copy of each, and record what it did
    python scripts/gates/g3_downgrade_open.py check OUT --bin <research-sidecar> \\
        --installer <the installer it came from> --sha256sums <the release's SHA256SUMS> \\
        --json release-audit/v3.1.0/evidence/G-3/<os>.json

The three directories, and what 3.0.2 must do with each:

| Directory | What it is | 3.0.2 must |
|---|---|---|
| `migrated` | The v3.0.2-populated fixture after a 3.1 launch moved its shared corpus into "Documents from before 3.1", plus a 3.1 folder upload | start; list its projects and runs; find no shared corpus (3.1 retired it) |
| `restored` | `migrated` with the backup renamed back to `corpus.sqlite`, the documented downgrade step | also list every legacy document and search them through a corpus-only run |
| `corpus31` | A data dir whose `corpus.sqlite` 3.1 wrote: new kinds, nested folders, a revision | list it, search it, and not crash on the kinds it cannot read |

Everything runs on copies. 3.0.2 runs its own open-time migration and must not be handed the
prepared directories themselves. 3.0.2 embeds through local Ollama even under `--fake`, so
`nomic-embed-text` must be served at `OLLAMA_BASE_URL`, and `prepare` embeds `corpus31` with
it for the same reason.

The checker refuses anything that does not report 3.0.2 at its tag's commit, and records the
installer's sha256 with its `SHA256SUMS` line.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.util
import json
import os
import re
import shutil
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
FIXTURE = BACKEND / "tests" / "fixtures" / "upgrade" / "v3.0.2-populated"
FORMATS = BACKEND / "tests" / "fixtures" / "formats"
RELEASE = {"version": "3.0.2", "git_sha": "0a9de70ee90485531120856fce7f5dde4041c0aa"}
TOKEN = "g3-prepare"


def _ids(path: Path) -> list[str]:
    with sqlite3.connect(path) as conn:
        return sorted(r[0] for r in conn.execute("SELECT id FROM corpus_documents"))


# ── prepare ───────────────────────────────────────────────────────────────────────


async def _migrate_and_add_a_folder(data: Path) -> None:
    sys.path.insert(0, str(BACKEND))
    import httpx
    from desktop.sidecar import create_sidecar_app

    app = create_sidecar_app(data_dir=data, token=TOKEN, fake=True)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://127.0.0.1:9"
        ) as c:
            auth = {"Authorization": f"Bearer {TOKEN}"}
            made = await c.post(
                "/api/v1/projects", headers=auth, json={"name": "Made in 3.1"}
            )
            up = await c.post(
                f"/api/v1/projects/{made.json()['id']}/corpus/documents",
                headers=auth,
                files={"file": ("report.docx", (FORMATS / "report.docx").read_bytes())},
                data={"relative_path": "Thesis/Chapter 2/report.docx"},
            )
            if up.status_code != 201:
                raise SystemExit(
                    f"3.1 could not upload into the migrated data dir: {up.text}"
                )


async def _corpus_written_by_3_1(path: Path) -> list[str]:
    sys.path.insert(0, str(BACKEND))
    from research_engine.corpus import CorpusStore
    from research_engine.embeddings import LocalEmbeddings

    store = CorpusStore(
        path,
        LocalEmbeddings(
            os.environ.get("CORPUS_EMBEDDINGS_MODEL", "nomic-embed-text"),
            os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434/v1"),
        ),
    )
    legacy = await store.ingest("notes.txt", (FORMATS / "notes.txt").read_bytes())
    await store.ingest(
        "notes.txt",
        (FORMATS / "notes.txt").read_bytes() + b"Attendance fell in 2022.\n",
        doc_key=legacy.doc_key,
    )
    for name in ("paper.pdf", "report.docx", "budget.xlsx", "deck.pptx", "stats.py"):
        doc = await store.ingest(name, (FORMATS / name).read_bytes())
    folder = await store.ensure_folder_path(["Thesis", "Chapter 2"])
    await store.add_membership(doc.doc_key, folder, "stats.py")
    return _ids(path)


def prepare(out: Path) -> dict:
    if out.exists():
        raise SystemExit(f"{out} exists; prepare writes a fresh directory")
    migrated = out / "migrated"
    shutil.copytree(
        FIXTURE,
        migrated,
        ignore=shutil.ignore_patterns("MANIFEST.json", "*.bundle.json"),
    )
    legacy_ids = _ids(migrated / "corpus.sqlite")
    asyncio.run(_migrate_and_add_a_folder(migrated))
    if (migrated / "corpus.sqlite").exists():
        raise SystemExit(
            "3.1 did not move the shared corpus; nothing to downgrade from"
        )

    restored = out / "restored"
    shutil.copytree(migrated, restored)
    shutil.copyfile(restored / "corpus.legacy-3.0.sqlite", restored / "corpus.sqlite")

    corpus31 = out / "corpus31"
    corpus31.mkdir()
    ids31 = asyncio.run(_corpus_written_by_3_1(corpus31 / "corpus.sqlite"))

    manifest = json.loads((FIXTURE / "MANIFEST.json").read_text(encoding="utf-8"))
    expect = {
        "migrated": {
            "documents": [],
            "runs": [manifest["run_completed_id"]],
            "search": False,
        },
        "restored": {
            "documents": legacy_ids,
            "runs": [manifest["run_completed_id"]],
            "search": True,
        },
        "corpus31": {"documents": ids31, "runs": [], "search": True},
    }
    (out / "expect.json").write_text(
        json.dumps(expect, indent=2) + "\n", encoding="utf-8"
    )
    return expect


# ── check ─────────────────────────────────────────────────────────────────────────


def _checker():
    spec = importlib.util.spec_from_file_location(
        "check_packaged_sidecar", ROOT / "scripts" / "check_packaged_sidecar.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _installer(installer: Path, sums: Path) -> dict:
    digest = hashlib.sha256(installer.read_bytes()).hexdigest()
    listed = {
        line.split()[-1].lstrip("*"): line.split()[0]
        for line in sums.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }
    published = listed.get(installer.name)
    if published != digest:
        raise SystemExit(
            f"{installer.name} has sha256 {digest}; SHA256SUMS lists {published or 'nothing'}"
        )
    return {"name": installer.name, "sha256": digest, "matches_SHA256SUMS": True}


_TOKEN = re.compile(r'("token":\s*")[^"]+(")')


def _tail(engine, lines: int) -> str:
    """The engine's last lines, with the handshake's per-launch token removed: evidence is
    committed, and a token-shaped string in it is one a reader has to rule out."""
    return _TOKEN.sub(r"\1REDACTED\2", engine.tail(lines))


def _check_dir(cps, binary: Path, data: Path, want: dict) -> dict:
    with tempfile.TemporaryDirectory(prefix="g3-") as tmp:
        copy = Path(tmp) / "data"
        shutil.copytree(data, copy)
        engine = cps.Engine(binary, copy, 240)
        try:
            version = engine.request("GET", "/version")
            if {k: version.get(k) for k in RELEASE} != RELEASE:
                raise cps.CheckFailed(
                    f"this engine is {version}, not the released 3.0.2"
                )
            projects = engine.request("GET", "/projects")["projects"]
            listed = sorted(d["id"] for d in engine.request("GET", "/corpus/documents"))
            if listed != want["documents"]:
                raise cps.CheckFailed(
                    f"3.0.2 listed {listed}, expected {want['documents']}"
                )
            for run in want["runs"]:
                engine.request("GET", f"/runs/{run}")
            searched = None
            if want["search"]:
                pid = projects[0]["id"]
                run = engine.request(
                    "POST",
                    "/runs",
                    {
                        "project_id": pid,
                        "question": "How did enrolment change in 2021?",
                        "depth": "fast",
                        "corpus_mode": True,
                        "skip_plan_gate": True,
                        "dispatch": True,
                    },
                )["run_id"]
                cps.await_status(engine, run, "AWAITING_REVIEW")
                sources = [
                    s["url"] for s in engine.request("GET", f"/runs/{run}")["sources"]
                ]
                cited = {u[len("corpus://") :].split("#", 1)[0] for u in sources}
                if not cited or not cited <= set(want["documents"]):
                    raise cps.CheckFailed(
                        f"the corpus run over {data.name} cited {sources}"
                    )
                searched = {"run_id": run, "cited": sorted(cited)}
            # Still alive after all of it: the "does not crash on new kinds" half.
            if engine.proc.poll() is not None:
                raise cps.CheckFailed(
                    f"the engine exited with {engine.proc.returncode}"
                )
            return {
                "result": "PASS",
                "version": version,
                "projects": sorted(p["name"] for p in projects),
                "documents_listed": len(listed),
                "search": searched,
                "log_tail": _tail(engine, 15),
            }
        except cps.CheckFailed as exc:
            return {"result": "FAIL", "error": str(exc), "log_tail": _tail(engine, 40)}
        finally:
            engine.stop()


def check(out: Path, binary: Path, installer: Path, sums: Path) -> dict:
    cps = _checker()
    expect = json.loads((out / "expect.json").read_text(encoding="utf-8"))
    evidence = {
        "gate": "G-3",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "platform": sys.platform,
        "installer": _installer(installer, sums),
        "binary": str(binary),
        "directories": {
            name: _check_dir(cps, binary, out / name, want)
            for name, want in expect.items()
        },
    }
    failed = [n for n, r in evidence["directories"].items() if r["result"] != "PASS"]
    evidence["result"] = "FAIL" if failed else "PASS"
    return evidence


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("prepare")
    p.add_argument("out", type=Path)
    c = sub.add_parser("check")
    c.add_argument("out", type=Path)
    c.add_argument("--bin", type=Path, required=True)
    c.add_argument("--installer", type=Path, required=True)
    c.add_argument("--sha256sums", type=Path, required=True)
    c.add_argument("--json", type=Path)
    args = parser.parse_args(argv)

    if args.command == "prepare":
        print(json.dumps(prepare(args.out), indent=2))
        return 0
    evidence = check(args.out, args.bin, args.installer, args.sha256sums)
    text = json.dumps(evidence, indent=2) + "\n"
    print(text)
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(text, encoding="utf-8")
    return 0 if evidence["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
