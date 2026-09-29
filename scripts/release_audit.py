#!/usr/bin/env python3
"""
The release audit: every deterministic check RELEASE.md asks for, run against the real thing.

`RELEASE.md` is the process; this is the part of it a machine can do without a human. It
answers one question from the outside, the way a user meets the release: *if someone
downloads vX.Y.Z today from the public site, do the artifacts, the images, the GitHub Release,
the site and the docs all correspond to the same release?* Every check exists because a past
release got that answer wrong while CI was green — each one says which incident.

    python scripts/release_audit.py --stage ci                       # every commit (ci.yml)
    python scripts/release_audit.py --version X.Y.Z                  # before tagging
    python scripts/release_audit.py --version X.Y.Z --published --download --docker
    python scripts/release_audit.py --version X.Y.Z --post-release   # after the site offers it
    python scripts/release_audit.py --list                           # the check registry
    python scripts/release_audit.py --group site,images              # one area at a time

**Stages follow the two-stage release (RELEASE.md, "Order of execution").**

| Stage | When | What it can see |
|---|---|---|
| `ci` | every push and PR | the repository alone — no network, no tag |
| `pre-tag` | release PR merged, before tagging | the commit to tag, its CI runs |
| `published` | tag's workflows finished | tag, GitHub Release, installers, checksums, images |
| `post-release` | flip PR merged and Pages deployed | all of the above plus the live site |

**Checks run concurrently** (`--jobs`, default 8), one module per area under
`scripts/release_checks/`, and the checks that make many requests fan them out again inside.
Almost all the time is network latency, so this is what makes a full post-release audit take
seconds rather than minutes; `--group` narrows a run to the areas you are iterating on.

**Results are five-valued, because unmeasured is not zero.** PASS and FAIL are verdicts. WARN
needs a person's disposition in the release record. SKIP means the check does not apply to
this release (it says why). UNAVAILABLE means the check *could not measure* — no network, no
token, `--download`/`--docker` not given, or the thing is not published yet — and it is never
counted as a pass. Exit 0 when every applicable check passed or warned, 1 when any
stop-the-release check failed, 2 when nothing failed but something went unmeasured.

Standard library only — the same rule as `sync_version.py`: a release check that needs the app
to import stops running exactly when the app stops importing. GitHub is read through its REST
API with `GH_TOKEN`/`GITHUB_TOKEN` or `gh auth token`; the container registry anonymously.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

if sys.version_info < (3, 11):  # noqa: UP036 — the backend's floor; /usr/bin/python3 is older
    sys.exit(f"release_audit.py needs Python 3.11+, this is {sys.version.split()[0]}")

sys.path.insert(0, str(Path(__file__).resolve().parent))

from release_checks import GROUPS, REGISTRY  # noqa: E402
from release_checks.constants import (  # noqa: E402
    FAIL,
    PASS,
    SKIP,
    STAGES,
    UNAVAILABLE,
    WARN,
)
from release_checks.core import ROOT, Check, Ctx, Outcome, Unavailable  # noqa: E402
from release_checks.evaluate import manual_ids, parse_version  # noqa: E402

SYMBOLS = {PASS: "✓", FAIL: "✗", WARN: "!", SKIP: "-", UNAVAILABLE: "?"}


def run_one(ctx: Ctx, c: Check) -> dict:
    started = time.monotonic()
    if c.network and ctx.offline:
        outcome = Outcome(UNAVAILABLE, "offline")
    else:
        try:
            outcome = c.fn(ctx)
        except Unavailable as exc:
            outcome = Outcome(UNAVAILABLE, str(exc))
        except AssertionError as exc:  # a precondition the check states, e.g. a page 404ing
            outcome = Outcome(FAIL, str(exc))
        except Exception as exc:  # noqa: BLE001 — a crashed check is reported, never hidden
            outcome = Outcome(FAIL, f"the check itself raised {type(exc).__name__}: {exc}")
    if outcome.status == FAIL and not c.stop:
        outcome.status = WARN
    return {
        "id": c.id,
        "phase": c.phase,
        "group": c.group,
        "title": c.title,
        "stop": c.stop,
        "status": outcome.status,
        "detail": outcome.detail,
        "evidence": outcome.evidence,
        "seconds": round(time.monotonic() - started, 2),
    }


def select(stage: str, only: set[str] | None, groups: set[str] | None) -> list[Check]:
    return [
        c
        for c in REGISTRY
        if stage in c.stages and (not only or c.id in only) and (not groups or c.group in groups)
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit a release against RELEASE.md.")
    parser.add_argument("--version", help="X.Y.Z (default: VERSION)")
    parser.add_argument("--stage", choices=STAGES, default="pre-tag")
    parser.add_argument("--post-release", action="store_const", dest="stage", const="post-release")
    parser.add_argument("--published", action="store_const", dest="stage", const="published")
    parser.add_argument("--offline", action="store_true", help="skip every network check")
    parser.add_argument("--download", action="store_true", help="download and hash installers")
    parser.add_argument("--docker", action="store_true", help="pull and run the api image")
    parser.add_argument("--previous", help="previous release tag (default: highest lower tag)")
    parser.add_argument("--repo", help="owner/name (default: from releases.ts)")
    parser.add_argument("--site", help="public site URL (default: as pages.yml resolves it)")
    parser.add_argument("--only", help="comma-separated check ids")
    parser.add_argument("--group", help=f"comma-separated areas: {', '.join(GROUPS)}")
    parser.add_argument("--jobs", type=int, default=8, help="checks run at once (default 8)")
    parser.add_argument("--json", type=Path, help="write the full result here")
    parser.add_argument("--list", action="store_true", help="print the check registry")
    parser.add_argument("--root", type=Path, default=ROOT, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    if args.list:
        for c in REGISTRY:
            print(
                f"{c.id:7} {c.group:15} {'STOP' if c.stop else 'warn'} "
                f"{'net' if c.network else '   '} {','.join(c.stages):36} {c.title}"
            )
        return 0

    groups = set(args.group.split(",")) if args.group else None
    if groups and (unknown := groups - set(GROUPS)):
        parser.error(f"unknown group(s) {sorted(unknown)}; choose from {', '.join(GROUPS)}")
    args.version = args.version or (args.root / "VERSION").read_text().strip()
    if parse_version(args.version) is None:
        parser.error(f"{args.version!r} is not X.Y.Z")

    ctx = Ctx(args)
    started = time.monotonic()
    ctx.prepare()
    try:
        commit = ctx.release_commit()
    except Unavailable:
        commit = None
    checks = select(ctx.stage, set(args.only.split(",")) if args.only else None, groups)
    with ThreadPoolExecutor(max_workers=max(1, args.jobs)) as pool:
        results = list(pool.map(lambda c: run_one(ctx, c), checks))
    elapsed = time.monotonic() - started

    width = max((len(r["title"]) for r in results), default=40)
    print(
        f"release audit — v{ctx.version}, stage {ctx.stage}"
        f"{' (offline)' if ctx.offline else ''}, commit {commit[:9] if commit else 'n/a'}\n"
    )
    for note in ctx.notes:
        print(f"  note: {note}")
    for r in results:
        print(
            f" {SYMBOLS[r['status']]} {r['id']:7} {r['title']:<{width}}  "
            f"{r['status']:<11} {r['seconds']:>6.2f}s"
        )
        if r["status"] != PASS:
            print(f"     {r['detail']}")
    counts = {s: sum(r["status"] == s for r in results) for s in SYMBOLS}
    stops = [r for r in results if r["status"] == FAIL and r["stop"]]
    unmeasured = [r for r in results if r["status"] == UNAVAILABLE]
    verdict = (
        "STOP — the release must not proceed"
        if stops
        else "INCOMPLETE — something could not be measured, so this is not a pass"
        if unmeasured
        else "PASS — every automated check for this stage holds"
    )
    print(
        "\n"
        + ", ".join(f"{n} {s}" for s, n in counts.items() if n)
        + f" — {len(results)} checks in {elapsed:.1f}s ({args.jobs} at a time)\n{verdict}"
    )
    release_md = args.root / "RELEASE.md"
    if release_md.exists() and ctx.stage != "ci":
        print(
            f"\nManual checks: {len(manual_ids(release_md.read_text()))} in RELEASE.md — "
            f"record each in {ctx.record_path.relative_to(ctx.root)}"
        )

    if args.json:
        from datetime import UTC, datetime  # noqa: PLC0415 — after the version guard

        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(
            json.dumps(
                {
                    "tool": "scripts/release_audit.py",
                    "version": ctx.version,
                    "tag": ctx.tag,
                    "stage": ctx.stage,
                    "offline": ctx.offline,
                    "download": ctx.download,
                    "docker": ctx.docker,
                    "commit": commit,
                    "previous": ctx.previous_tag(),
                    "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
                    "seconds": round(elapsed, 1),
                    "verdict": verdict.split(" —")[0],
                    "counts": counts,
                    "notes": ctx.notes,
                    "results": results,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    return 1 if stops else 2 if unmeasured else 0


if __name__ == "__main__":
    raise SystemExit(main())
