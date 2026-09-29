"""Phases 0-2: the repository says one version, everywhere, and accounts for what ships."""

from __future__ import annotations

import json
import re

from .constants import AFTER_TAG, QUALITY_PATHS
from .core import (
    Ctx,
    Outcome,
    Unavailable,
    check,
    fail,
    load_allowlist,
    load_sync_version,
    ok,
    skip,
    user_facing_files,
    verdict,
    warn,
)
from .evaluate import (
    cargo_lock_version,
    changelog_heading,
    changelog_section,
    entry_completeness,
    parse_releases_ts,
    parse_version,
    release_list_problems,
    review_references,
    version_references,
)


def _entry(ctx: Ctx) -> dict | None:
    return next(
        (
            e
            for e in parse_releases_ts(ctx.read("frontend/lib/releases.ts"))
            if e["version"] == ctx.tag
        ),
        None,
    )


# ─── Phase 0 — scope freeze ─────────────────────────────────────────────────────────────


@check(
    "A0.01", 0, "The release record exists and names this version", stages=("pre-tag", *AFTER_TAG)
)
def record_exists(ctx: Ctx) -> Outcome:
    if not ctx.record_path.exists():
        return fail(
            f"{ctx.record_path.relative_to(ctx.root)} does not exist — copy "
            "release-audit/TEMPLATE.md there and fill Phase 0 before anything else"
        )
    text = ctx.record_path.read_text(encoding="utf-8")
    if ctx.tag not in text.splitlines()[0]:
        return fail("the record's title does not name this version")
    if not re.search(r"^## Scope", text, re.M):
        return fail("the record has no Scope section (Phase 0/2)")
    return ok(str(ctx.record_path.relative_to(ctx.root)))


# ─── Phase 1 — repository and version consistency ─────────────────────────────────────


@check("A1.01", 1, "VERSION names the version being released")
def version_file(ctx: Ctx) -> Outcome:
    found = ctx.read("VERSION").strip()
    if parse_version(found) is None:
        return fail(f"VERSION holds {found!r}, not a semantic version")
    if found != ctx.version:
        return fail(f"VERSION says {found}, the audit was asked about {ctx.version}")
    return ok(found)


@check("A1.02", 1, "Every derived version constant agrees with VERSION (sync_version.py)")
def derived_versions(ctx: Ctx) -> Outcome:
    sync = load_sync_version(ctx.root)
    files = [str(d.path.relative_to(ctx.root)) for d in sync.DERIVED]
    return verdict(sync.drift(), f"{len(files)} derived files agree", files=files)


@check("A1.03", 1, "desktop/Cargo.lock pins the crate at VERSION")
def cargo_lock(ctx: Ctx) -> Outcome:
    # sync_version.py deliberately does not write the lock (cargo owns it), which is exactly
    # how it sat at 2.0.1 through the whole 2.0.2 line.
    found = cargo_lock_version(ctx.read("desktop/Cargo.lock"))
    if found != ctx.version:
        return fail(
            f"Cargo.lock has research-desktop {found}; run `cargo update -p research-desktop`"
        )
    return ok(found)


@check("A1.04", 1, "releases.ts is newest-first, one entry per version, each dated")
def releases_structure(ctx: Ctx) -> Outcome:
    entries = parse_releases_ts(ctx.read("frontend/lib/releases.ts"))
    if not entries:
        return fail("no entries parsed from frontend/lib/releases.ts")
    problems = release_list_problems(entries)
    if entries[0]["version"] != ctx.tag:
        problems.insert(0, f"the newest entry is {entries[0]['version']}, not {ctx.tag}")
    return verdict(problems, f"{len(entries)} entries, newest {ctx.tag}")


@check("A1.05", 1, "This release's entry has a headline, improvements, and its known gaps")
def releases_entry_complete(ctx: Ctx) -> Outcome:
    entry = _entry(ctx)
    if entry is None:
        return fail(f"no {ctx.tag} entry in releases.ts")
    failures, warnings = entry_completeness(entry)
    if failures:
        return fail("; ".join(failures + warnings))
    if warnings:
        return warn("; ".join(warnings))
    return ok(f"{entry['improved']} improved, {entry['known']} known")


@check(
    "A1.06",
    1,
    "The download state of this release's entry is right for the stage",
    stages=("pre-tag", *AFTER_TAG),
)
def releases_unreleased_flag(ctx: Ctx) -> Outcome:
    entry = _entry(ctx)
    if entry is None:
        return fail(f"no {ctx.tag} entry in releases.ts")
    if ctx.stage == "pre-tag":
        # D-9: the entry merges and deploys before any installer exists. Offering it then
        # sends every visitor to a 404, which reads as a broken product.
        if not entry["unreleased"]:
            return fail("downloadable before its installers exist — set `unreleased: true`")
        return ok("unreleased: true until the installers are verified")
    if ctx.stage == "published":
        return ok(
            "still unreleased; the flip PR comes after verification"
            if entry["unreleased"]
            else "already offered — confirm Phase 21 approved it before the flip"
        )
    if entry["unreleased"]:
        return fail("still `unreleased: true`, so the site offers the previous release")
    dates = ctx.tag_dates(ctx.tag)
    if dates and entry["date"] not in dates:
        return fail(f"dated {entry['date']}, but {ctx.tag} was cut on {' / '.join(sorted(dates))}")
    return ok(f"offered, dated {entry['date']}")


@check(
    "A1.07",
    1,
    "The changelog carries this release, with its known gaps",
    stages=("pre-tag", *AFTER_TAG),
)
def changelog(ctx: Ctx) -> Outcome:
    text = ctx.read("docs/project/37-changelog.md")
    heading = changelog_heading(text, ctx.version)
    if heading is None:
        return fail(f"no `## v{ctx.version} — …` heading in docs/project/37-changelog.md")
    if "**Known**" not in changelog_section(text, ctx.version):
        return fail("the changelog entry has no **Known** block")
    if ctx.stage == "post-release":
        entry = _entry(ctx)
        if entry and heading != entry["date"]:
            return fail(f"changelog says {heading!r}, releases.ts says {entry['date']}")
    elif ctx.stage == "pre-tag" and heading != "unreleased":
        return fail(f"the heading says {heading!r} before the tag exists — use `unreleased`")
    return ok(f"v{ctx.version} — {heading}")


@check("A1.08", 1, "Nothing reads the private package versions (they are not version carriers)")
def non_carriers(ctx: Ctx) -> Outcome:
    # frontend/package.json, desktop/package.json and research_engine/pyproject.toml say 0.1.0
    # and are published nowhere. The day something reads one, it becomes a carrier
    # sync_version.py does not know about — which is how /health said 1.0.0 for two releases.
    readers = []
    for p in ctx.tracked():
        if (
            not p.endswith((".py", ".ts", ".tsx", ".mjs", ".rs"))
            or ".test." in p
            or "/tests/" in p
            or p.startswith("scripts/")
        ):
            continue
        text = ctx.read(p)
        if re.search(
            r"npm_package_version|importlib\.metadata|from ['\"][./]*package\.json['\"]"
            r"|require\(['\"][./]*package\.json['\"]\)|CARGO_PKG_VERSION",
            text,
        ):
            readers.append(p)
    problems = [
        f"{p} is not private"
        for p in ("frontend/package.json", "desktop/package.json")
        if json.loads(ctx.read(p)).get("private") is not True
    ]
    if readers:
        problems.append(
            "these read a package version: "
            + ", ".join(readers)
            + " — add that file to sync_version.py's DERIVED"
        )
    return verdict(problems, "no reader; both package.json private")


@check("A1.09", 1, "Every version named in user-facing text is a reviewed, intended reference")
def historical_references(ctx: Ctx) -> Outcome:
    refs = version_references(user_facing_files(ctx))
    unreviewed, stale, _future = review_references(refs, load_allowlist(ctx), ctx.version)
    problems = [f"unreviewed {r['path']}:{r['line']}: {r['text'][:120]}" for r in unreviewed]
    problems += [
        f"stale allowlist entry (line gone or edited) {a['path']}: {a['text'][:80]}" for a in stale
    ]
    if problems:
        return fail(
            f"{len(unreviewed)} unreviewed, {len(stale)} stale — review each and record it in "
            "release-audit/historical-references.json with its reason",
            problems=problems,
        )
    return ok(f"{len(refs)} references, all reviewed")


@check("A1.10", 1, "No user-facing text names a version newer than this release")
def future_references(ctx: Ctx) -> Outcome:
    refs = version_references(user_facing_files(ctx))
    _u, _s, future = review_references(refs, load_allowlist(ctx), ctx.version)
    return verdict(
        [f"{r['path']}:{r['line']} names {', '.join(r['newer'])}" for r in future], "none"
    )


@check(
    "A1.11",
    1,
    "The release commit is clean and is what origin/main points at",
    stages=("pre-tag",),
    network=True,
)
def clean_on_main(ctx: Ctx) -> Outcome:
    head = ctx.git("rev-parse", "HEAD")
    remote = ctx.remote_main()
    if not remote:
        raise Unavailable("could not read origin/main")
    problems = []
    if ctx.git("status", "--porcelain"):
        problems.append("the working tree has uncommitted changes")
    if remote != head:
        problems.append(
            f"HEAD {head[:9]} is not origin/main {remote[:9]} — tag only what main holds"
        )
    return verdict(problems, f"HEAD = origin/main = {head[:9]}")


@check(
    "A1.12",
    1,
    "The tag is in the state this stage needs",
    stages=("pre-tag", *AFTER_TAG),
    network=True,
)
def tag_state(ctx: Ctx) -> Outcome:
    remote = ctx.git(
        "ls-remote", "origin", f"refs/tags/{ctx.tag}", f"refs/tags/{ctx.tag}^{{}}", check=False
    )
    refs = {name: sha for sha, name in (line.split("\t") for line in remote.splitlines())}
    if ctx.stage == "pre-tag":
        return fail(f"{ctx.tag} already exists on origin") if refs else ok("not yet tagged")
    if not refs:
        return fail(f"{ctx.tag} does not exist on origin")
    peeled = refs.get(f"refs/tags/{ctx.tag}^{{}}") or refs[f"refs/tags/{ctx.tag}"]
    local = ctx.tag_commit()
    if local and peeled != local:
        return fail(f"origin's {ctx.tag} is {peeled[:9]}, the local tag is {local[:9]}")
    if ctx.git("cat-file", "-t", ctx.tag, check=False) != "tag":
        return warn(f"{ctx.tag} → {peeled[:9]} is a lightweight tag; annotate release tags")
    return ok(f"{ctx.tag} → {peeled[:9]} (annotated)", commit=peeled)


@check("A1.13", 1, "The tagged tree is on main and says this version everywhere", stages=AFTER_TAG)
def tag_tree(ctx: Ctx) -> Outcome:
    sha = ctx.release_commit()
    problems = (
        []
        if ctx.git_ok("merge-base", "--is-ancestor", sha, "origin/main")
        else [f"{sha[:9]} is not on origin/main"]
    )
    if (ctx.show(sha, "VERSION") or "").strip() != ctx.version:
        problems.append("the tagged VERSION is not this version")
    for d in load_sync_version(ctx.root).DERIVED:
        rel = str(d.path.relative_to(ctx.root))
        m = d.pattern.search(ctx.show(sha, rel) or "")
        if not m or m[1] != ctx.version:
            problems.append(f"{rel} at the tag says {m[1] if m else None}")
    if cargo_lock_version(ctx.show(sha, "desktop/Cargo.lock") or "") != ctx.version:
        problems.append("desktop/Cargo.lock at the tag is not this version")
    entry = next(
        (
            e
            for e in parse_releases_ts(ctx.show(sha, "frontend/lib/releases.ts") or "")
            if e["version"] == ctx.tag
        ),
        None,
    )
    if entry is None:
        problems.append("the tagged releases.ts has no entry for this version")
    if problems:
        return fail("; ".join(problems))
    if not entry["unreleased"]:
        # Not fatal after the fact, but the site could offer installers before they existed
        # (the D-9 two-stage rule) — say so.
        return warn("tagged with the entry already downloadable (D-9 expects `unreleased: true`)")
    return ok(f"{sha[:9]} on main, consistent, tagged unreleased")


@check("A1.14", 1, "Every published measurement matches a committed evaluation result")
def measured_claims(ctx: Ctx) -> Outcome:
    # The README once advertised 90% citation support while linking to a result whose rate
    # was null. A percentage is a measurement, and a measurement names its evidence.
    measured = {}
    for f in sorted((ctx.root / "backend/evals/results").glob("eval-*.json")):
        rate = json.loads(f.read_text()).get("aggregate", {}).get("citation_support_rate")
        if rate is not None:
            measured[round(rate * 100, 1)] = f.name
    claims, problems = [], []
    sources = [
        "README.md",
        "frontend/lib/releases.ts",
        "frontend/lib/features.ts",
        *[p for p in ctx.tracked() if p.startswith("docs/") and p.endswith(".md")],
    ]
    for rel in sources:
        for n, line in enumerate(ctx.read(rel).splitlines(), 1):
            if not re.search(r"citation support|measured", line, re.I):
                continue
            # A threshold ("clearing the 95% threshold") is a rule, not a measurement.
            for pct in re.findall(r"(\d{2}(?:\.\d)?)\s?%(?!\s+threshold)", line):
                claims.append(f"{rel}:{n} {pct}%")
                if float(pct) not in measured:
                    problems.append(f"{rel}:{n} claims {pct}%, which no committed result measured")
    return verdict(
        problems, f"{len(claims)} claims, each backed", backed_by=sorted(set(measured.values()))
    )


# ─── Phase 2 — feature completeness ─────────────────────────────────────────────────────


@check(
    "A2.01",
    2,
    "Every PR merged since the previous release is accounted for in the record",
    stages=("pre-tag", *AFTER_TAG),
)
def prs_accounted(ctx: Ctx) -> Outcome:
    prev = ctx.previous_tag()
    if prev is None:
        return skip("no previous release to diff against")
    subjects = ctx.git("log", "--first-parent", "--format=%s", f"{prev}..{ctx.release_commit()}")
    prs = sorted(set(re.findall(r"Merge pull request #(\d+)", subjects)), key=int)
    if not ctx.record_path.exists():
        return fail("no release record to account for them in", prs=prs)
    record = ctx.record_path.read_text(encoding="utf-8")
    missing = [p for p in prs if not re.search(rf"#{p}\b", record)]
    return verdict(
        [f"not in the record's scope table: {', '.join('#' + p for p in missing)}"]
        if missing
        else [],
        f"{len(prs)} PRs since {prev}, all accounted for",
        prs=prs,
    )


@check("A2.02", 2, 'Features marked "new in" name a released version')
def features_since(ctx: Ctx) -> Outcome:
    versions = {e["version"] for e in parse_releases_ts(ctx.read("frontend/lib/releases.ts"))}
    cur = parse_version(ctx.version)
    bad = [
        s
        for s in re.findall(r'since: "([^"]+)"', ctx.read("frontend/lib/features.ts"))
        if s not in versions or parse_version(s) > cur
    ]
    return verdict([f"`since` names unreleased versions: {bad}"] if bad else [], "all released")


@check(
    "A2.03",
    2,
    "A release that changes what runs produce carries an evaluation or a waiver",
    stages=("pre-tag", *AFTER_TAG),
)
def eval_gate(ctx: Ctx) -> Outcome:
    prev = ctx.previous_tag()
    if prev is None:
        return skip("no previous release")
    head = ctx.release_commit()
    changed = ctx.git("diff", "--name-only", f"{prev}..{head}", "--", *QUALITY_PATHS).split()
    if not changed:
        return ok(f"no quality-affecting path changed since {prev}")
    new_results = ctx.git(
        "diff", "--name-only", "--diff-filter=A", f"{prev}..{head}", "--", "backend/evals/results/"
    ).split()
    if new_results:
        return ok(f"{len(changed)} quality paths changed; new result(s): {new_results}")
    record = ctx.record_path.read_text(encoding="utf-8") if ctx.record_path.exists() else ""
    if re.search(r"^Eval waiver:\s*\S", record, re.M):
        return warn(f"changed {changed} with no new result; waiver recorded — confirm it")
    return fail(
        f"changed {changed} since {prev} with no new committed eval result and no "
        "`Eval waiver:` line in the record"
    )
