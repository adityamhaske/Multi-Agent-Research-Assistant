"""Phases 3 and 6: what CI actually ran on the release commit and the tag, and the guards that
exist because a past release shipped broken with CI green."""

from __future__ import annotations

import json
from collections.abc import Iterable

from .constants import AFTER_TAG, REQUIRED_CHECKS
from .core import Ctx, Outcome, Unavailable, check, fail, ok, parallel_map, verdict, warn

# Every release incident that has a guard in a workflow, and the guard. Deleting one is a
# release-process regression even when every build stays green — which is the point: these
# failures were all invisible to a green build.
WORKFLOW_GUARDS = (
    (
        ".github/workflows/release.yml",
        "scripts/sync_version.py --tag",
        "a tag ahead of its version bump publishes images labelled with the wrong version",
    ),
    (
        ".github/workflows/desktop.yml",
        "scripts/sync_version.py --tag",
        "a tag ahead of its version bump publishes installers named for the previous version",
    ),
    (
        ".github/workflows/desktop.yml",
        "needs: sidecar",
        "the shell raced the sidecar and shipped a 5 MB app with no engine",
    ),
    (
        ".github/workflows/desktop.yml",
        "name: The bundle actually contains the backend",
        "a 5 MB bundle passed CI and died on first launch",
    ),
    (
        ".github/workflows/desktop.yml",
        "name: Smoke — the frozen binary reports the commit that built it",
        "a stale or wrong stamp would ship an engine that lies about its commit",
    ),
    (
        ".github/workflows/desktop.yml",
        "name: Smoke — a run reaches a bundle the standalone verifier passes",
        "every V2 route on the packaged app answered 500 while the source suite was green",
    ),
    (
        ".github/workflows/desktop.yml",
        "name: The copy actually inside the bundle reports the commit that built it",
        "the copy the .app launches is not necessarily the one CI smoke-tested",
    ),
    (
        ".github/workflows/desktop.yml",
        "name: The app inside the published disk image has a valid signature",
        "every macOS build 1.0.1-3.0.0 was reported as damaged",
    ),
    (
        ".github/workflows/desktop.yml",
        "name: The installed .deb carries a working engine that reports this commit",
        "a .deb that compiled was never installed or launched",
    ),
    (
        ".github/workflows/desktop.yml",
        "name: The AppImage carries a working engine that reports this commit",
        "an AppImage that compiled was never extracted or launched",
    ),
    (
        ".github/workflows/desktop.yml",
        "name: The installed .msi carries a working engine that reports this commit",
        '"Windows passed CI" meant the MSI compiled, not that an installed copy worked',
    ),
    (
        ".github/workflows/desktop.yml",
        'mv "$f" "${f// /.}"',
        "SHA256SUMS listed names with a space GitHub never serves (v1.0.1)",
    ),
    (
        ".github/workflows/desktop.yml",
        "name: Fail if no installers were produced",
        "a green release with an empty asset list",
    ),
    (
        ".github/workflows/desktop.yml",
        "append_body: true",
        "the two workflows overwrote each other's release notes (v2.0.0)",
    ),
    (
        ".github/workflows/release.yml",
        "append_body: true",
        "the two workflows overwrote each other's release notes (v2.0.0)",
    ),
    (
        ".github/workflows/release.yml",
        "IMAGE_TAG=${GITHUB_REF_NAME#v}",
        "every release told people to pull a `:vX.Y.Z` image tag that does not exist",
    ),
    (
        ".github/workflows/release.yml",
        "name: Verify both architectures are present",
        "an amd64-only image does not start on the Ampere deploy target",
    ),
    (
        ".github/workflows/release.yml",
        "startsWith(github.ref, 'refs/tags/') }}",
        "only a version tag may move `latest`",
    ),
    (
        ".github/workflows/release.yml",
        "name: The pushed image reports the commit that built it",
        "every image through 3.0.1 answered /api/v1/version with `unknown`",
    ),
    (
        ".github/workflows/pages.yml",
        "out/.nojekyll",
        "Jekyll silently drops `_next/`, i.e. every stylesheet and script",
    ),
    (
        ".github/workflows/pages.yml",
        "needs: build",
        "a retry after a Pages outage failed with 'Artifact count is 2'",
    ),
    (
        ".github/workflows/pages.yml",
        "name: Fail if the export is empty or missing pages",
        "a green deploy that published nothing",
    ),
    (
        ".github/workflows/pages.yml",
        "out/build.json",
        "nothing on the live site said which commit it was built from",
    ),
    (
        ".github/workflows/ci.yml",
        "npm run build:pages",
        "a change that broke the public site went green on the PR and red on deploy",
    ),
    (
        ".github/workflows/ci.yml",
        "python scripts/sync_version.py",
        "/health reported 1.0.0 through the whole 1.0.x line",
    ),
    (
        ".github/workflows/ci.yml",
        "scripts/release_audit.py --stage ci",
        "release-content invariants stop being enforced per commit",
    ),
)

DESKTOP_TAG_STEPS = {
    **{
        f"Sidecar ({os_})": [
            "The tag names VERSION",
            "Stamp the build with this commit",
            "Smoke — handshake, token gate, watchdog flag",
            "Smoke — the frozen binary reports the commit that built it",
            "Smoke — a run reaches a bundle the standalone verifier passes",
        ]
        for os_ in ("ubuntu-latest", "macos-latest", "windows-latest")
    },
    "Shell (macos-latest)": [
        "The bundle actually contains the backend",
        "The copy actually inside the bundle reports the commit that built it",
        "The app inside the published disk image has a valid signature",
    ],
    "Shell (ubuntu-latest)": [
        "The bundle actually contains the backend",
        "The installed .deb carries a working engine that reports this commit",
        "The AppImage carries a working engine that reports this commit",
    ],
    "Shell (windows-latest)": [
        "The bundle actually contains the backend",
        "The installed .msi carries a working engine that reports this commit",
    ],
    "Publish release": [
        "Collect installers and checksum them",
        "Fail if no installers were produced",
        "Publish to GitHub Releases",
    ],
}


def job_problems(jobs: list[dict], required: Iterable[str]) -> list[str]:
    by_name = {j["name"]: j for j in jobs}
    problems = []
    for name in required:
        job = by_name.get(name)
        if job is None:
            problems.append(f"no job {name!r}")
        elif job["conclusion"] != "success":
            problems.append(f"{name}: {job['conclusion'] or job['status']}")
    return problems


def step_problems(jobs: list[dict], wanted: dict[str, Iterable[str]]) -> tuple[list, list]:
    """(failed or skipped steps, steps absent from the run). Absent means the guard was not in
    that commit's workflow — reported, never counted as having passed."""
    problems, absent = [], []
    by_name = {j["name"]: j for j in jobs}
    for job_name, steps in wanted.items():
        job = by_name.get(job_name)
        if job is None:
            problems.append(f"no job {job_name!r}")
            continue
        conclusions = {s["name"]: s["conclusion"] for s in job.get("steps", [])}
        for step in steps:
            if step not in conclusions:
                absent.append(f"{job_name} › {step}")
            elif conclusions[step] != "success":
                problems.append(f"{job_name} › {step}: {conclusions[step]}")
    return problems, absent


@check(
    "A3.01",
    3,
    "CI on the release commit passed every required job, the E2E journeys included",
    stages=("pre-tag", *AFTER_TAG),
    network=True,
)
def ci_green(ctx: Ctx) -> Outcome:
    sha = ctx.release_commit()
    run = ctx.run_for(sha, "CI", "push", "main")
    jobs = ctx.jobs(run)
    problems = job_problems(
        jobs,
        (
            "backend",
            "frontend",
            "golden-e2e",
            "One version, everywhere",
            "Eval results are write-once",
        ),
    )
    failed, absent = step_problems(
        jobs, {"backend": ["Migration round-trip (populated database, both directions)", "Tests"]}
    )
    problems += failed + [f"step absent: {a}" for a in absent]
    return verdict(problems, run["html_url"], run=run["html_url"], commit=sha)


@check(
    "A3.02",
    3,
    "Desktop and Pages on the release commit passed",
    stages=("pre-tag", *AFTER_TAG),
    network=True,
)
def desktop_and_pages_green(ctx: Ctx) -> Outcome:
    sha = ctx.release_commit()
    run = ctx.run_for(sha, "Desktop", "push", "main")
    problems = job_problems(ctx.jobs(run), [c for c in REQUIRED_CHECKS if "(" in c])
    try:
        pages = ctx.run_for(sha, "Pages", "push", "main")
        if pages["conclusion"] != "success":
            problems.append(f"Pages: {pages['conclusion']}")
    except Unavailable:
        # pages.yml only runs when frontend/ or docs/ changed; a release commit always
        # changes releases.ts, so its absence is itself worth a look.
        problems.append("no Pages run on the release commit (did it not touch frontend/?)")
    return verdict(problems, run["html_url"], desktop_run=run["html_url"])


@check(
    "A3.03",
    3,
    "main still requires every release-critical check (the ruleset)",
    stages=("pre-tag", *AFTER_TAG),
    network=True,
)
def ruleset(ctx: Ctx) -> Outcome:
    active = [
        rs for rs in ctx.api(f"/repos/{ctx.repo}/rulesets") if rs.get("enforcement") == "active"
    ]
    details = parallel_map(lambda rs: ctx.api(f"/repos/{ctx.repo}/rulesets/{rs['id']}"), active)
    contexts = {
        c["context"]
        for d in details
        for rule in d.get("rules", [])
        if rule["type"] == "required_status_checks"
        for c in rule["parameters"]["required_status_checks"]
    }
    missing = [c for c in REQUIRED_CHECKS if c not in contexts]
    return verdict(
        [f"no longer required on main: {missing}"] if missing else [],
        f"{len(REQUIRED_CHECKS)} checks required",
        required=sorted(contexts),
    )


@check(
    "A6.01",
    6,
    "The tag's Desktop run passed every job, publishing included",
    stages=AFTER_TAG,
    network=True,
)
def desktop_tag_run(ctx: Ctx) -> Outcome:
    run = ctx.run_for(ctx.release_commit(), "Desktop", "push", ctx.tag)
    return verdict(
        job_problems(ctx.jobs(run), DESKTOP_TAG_STEPS),
        run["html_url"],
        run=run["html_url"],
        started=run["run_started_at"],
    )


@check(
    "A6.02",
    6,
    "Every packaged-app guard ran and passed on the tag's installers",
    stages=AFTER_TAG,
    network=True,
)
def desktop_tag_guards(ctx: Ctx) -> Outcome:
    run = ctx.run_for(ctx.release_commit(), "Desktop", "push", ctx.tag)
    failed, absent = step_problems(ctx.jobs(run), DESKTOP_TAG_STEPS)
    if failed:
        return fail("; ".join(failed), absent=absent)
    if absent:
        # A guard added after this tag was cut did not exist for its build — that release's
        # installers were not checked that way, which the record must say.
        return warn(f"{len(absent)} guard(s) not in this tag's workflow: {absent}")
    return ok("all guards passed")


@check("A6.03", 6, "Every workflow guard a past release incident put in place is still there")
def workflow_guards(ctx: Ctx) -> Outcome:
    missing = [
        f"{f}: `{needle}` ({why})"
        for f, needle, why in WORKFLOW_GUARDS
        if needle not in ctx.read(f)
    ]
    return verdict(
        ["guards removed: " + "; ".join(missing)] if missing else [],
        f"{len(WORKFLOW_GUARDS)} guards present",
    )


@check("A6.04", 6, "The Tauri bundle config ships the engine and signs the whole macOS bundle")
def tauri_config(ctx: Ctx) -> Outcome:
    bundle = json.loads(ctx.read("desktop/tauri.conf.json")).get("bundle", {})
    problems = []
    if bundle.get("macOS", {}).get("signingIdentity") != "-":
        problems.append(
            'bundle.macOS.signingIdentity is not "-" — a downloaded Mac build '
            "is reported as damaged"
        )
    if bundle.get("resources", {}).get("../backend/dist/research-sidecar/") != "sidecar/":
        problems.append("bundle.resources no longer copies the engine to sidecar/")
    if bundle.get("targets") != "all":
        problems.append(
            f"bundle.targets is {bundle.get('targets')!r}; the release needs dmg, "
            "msi, AppImage and deb"
        )
    if not bundle.get("active"):
        problems.append("bundling is off")
    return verdict(problems, "engine bundled, macOS bundle signed")
