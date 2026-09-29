"""Phase 11: the GitHub Release — what a user actually downloads, and whether it is what the
tag's own run built."""

from __future__ import annotations

import hashlib
import urllib.request
from datetime import datetime, timedelta

from .constants import AFTER_TAG, CHECKSUMS
from .core import (
    OPENER,
    Ctx,
    Outcome,
    Unavailable,
    check,
    fail,
    http,
    ok,
    parallel_map,
    skip,
    verdict,
)
from .evaluate import (
    asset_problems,
    checksum_problems,
    parse_sha256sums,
    parse_version,
    release_body_problems,
)


def _sums(ctx: Ctx) -> dict[str, str]:
    asset = next((a for a in ctx.release()["assets"] if a["name"] == CHECKSUMS), None)
    if asset is None:
        raise Unavailable("no SHA256SUMS asset")
    status, _h, body = ctx.memo(("sums", ctx.tag), lambda: http(asset["browser_download_url"]))
    if status != 200:
        raise Unavailable(f"SHA256SUMS answered {status}")
    return parse_sha256sums(body.decode())


def _parse_time(stamp: str) -> datetime:
    return datetime.fromisoformat(stamp.replace("Z", "+00:00"))


@check(
    "A11.01",
    11,
    "The GitHub Release exists, is public, and is marked the way the tag says",
    stages=AFTER_TAG,
    network=True,
)
def gh_release(ctx: Ctx) -> Outcome:
    rel = ctx.release()
    problems = []
    if rel["draft"]:
        problems.append("still a draft")
    if rel["prerelease"] != ("-" in ctx.version):
        problems.append(f"prerelease={rel['prerelease']} disagrees with the version's suffix")
    if ctx.version not in (rel.get("name") or ""):
        problems.append(f"the title {rel.get('name')!r} does not name {ctx.version}")
    return verdict(problems, rel["html_url"], url=rel["html_url"], published_at=rel["published_at"])


@check(
    "A11.02",
    11,
    'GitHub\'s "latest release" is this one (the in-app update check reads it)',
    stages=AFTER_TAG,
    network=True,
)
def gh_latest(ctx: Ctx) -> Outcome:
    # Settings → About asks api.github.com/…/releases/latest (app/services/updates.py). A
    # release not marked latest is one no installed copy will ever be told about.
    latest = ctx.api(f"/repos/{ctx.repo}/releases/latest")["tag_name"]
    if latest == ctx.tag:
        return ok(latest)
    if parse_version(latest) and parse_version(latest) > parse_version(ctx.version):
        return skip(f"{latest} is newer")
    return fail(f"GitHub's latest is {latest}; installed apps are told {latest} is current")


@check(
    "A11.03",
    11,
    "Exactly the four installers and SHA256SUMS, named as served, not undersized",
    stages=AFTER_TAG,
    network=True,
)
def gh_assets(ctx: Ctx) -> Outcome:
    assets = ctx.release()["assets"]
    return verdict(
        asset_problems(assets, ctx.version),
        "4 installers + SHA256SUMS",
        assets={a["name"]: {"size": a["size"], "digest": a.get("digest")} for a in assets},
    )


@check(
    "A11.04",
    11,
    "Every asset was uploaded by the tag's own Desktop run",
    stages=AFTER_TAG,
    network=True,
)
def gh_assets_provenance(ctx: Ctx) -> Outcome:
    # A hand-uploaded or re-uploaded file carries a name and a checksum line like any other.
    # The run that built and tested it is the only thing that vouches for it.
    run = ctx.run_for(ctx.release_commit(), "Desktop", "push", ctx.tag)
    start = _parse_time(run["run_started_at"])
    end = _parse_time(run["updated_at"]) + timedelta(minutes=5)
    problems = []
    for a in ctx.release()["assets"]:
        uploader = (a.get("uploader") or {}).get("login")
        if uploader != "github-actions[bot]":
            problems.append(f"{a['name']} was uploaded by {uploader}")
        if not start <= _parse_time(a["created_at"]) <= end:
            problems.append(f"{a['name']} was uploaded at {a['created_at']}, outside the tag run")
    return verdict(problems, f"all uploaded during {run['html_url']}")


@check(
    "A11.05",
    11,
    "SHA256SUMS lists every installer, and every hash is what GitHub stored",
    stages=AFTER_TAG,
    network=True,
)
def gh_checksums(ctx: Ctx) -> Outcome:
    assets = ctx.release()["assets"]
    if not all(a.get("digest") for a in assets):
        raise Unavailable("GitHub did not report asset digests; use --download")
    sums = _sums(ctx)
    return verdict(checksum_problems(sums, assets, ctx.version), "4 hashes match", sums=sums)


def _hash_download(url: str) -> str:
    digest = hashlib.sha256()
    req = urllib.request.Request(url, headers={"User-Agent": "release-audit"})
    with OPENER.open(req, timeout=900) as resp:  # noqa: S310 — a GitHub release asset
        for chunk in iter(lambda: resp.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


@check(
    "A11.06",
    11,
    "Every installer, downloaded, hashes to its SHA256SUMS line",
    stages=AFTER_TAG,
    network=True,
)
def gh_download_hashes(ctx: Ctx) -> Outcome:
    if not ctx.download:
        raise Unavailable("pass --download to fetch the installers (~460 MB) and hash them")
    sums = _sums(ctx)
    installers = [a for a in ctx.release()["assets"] if a["name"] != CHECKSUMS]
    hashed = dict(
        zip(
            (a["name"] for a in installers),
            parallel_map(
                lambda a: _hash_download(a["browser_download_url"]), installers, workers=4
            ),
            strict=True,
        )
    )
    problems = [
        f"{n}: downloaded {h[:12]}…, SHA256SUMS {str(sums.get(n))[:12]}…"
        for n, h in hashed.items()
        if sums.get(n) != h
    ]
    return verdict(problems, f"{len(hashed)} downloads verified", hashed=hashed)


@check(
    "A11.07",
    11,
    "The release notes carry both workflows' sections and the right pull tags",
    stages=AFTER_TAG,
    network=True,
)
def gh_release_body(ctx: Ctx) -> Outcome:
    return verdict(
        release_body_problems(ctx.release().get("body") or "", ctx.version),
        "images, installers, first launch, checksums",
    )


@check("A11.08", 11, "The tag's source archive downloads", stages=AFTER_TAG, network=True)
def source_archive(ctx: Ctx) -> Outcome:
    url = f"https://github.com/{ctx.repo}/archive/refs/tags/{ctx.tag}.zip"
    status, _h, _b = http(url, method="HEAD")
    return ok(url) if status == 200 else fail(f"{url} answered {status}")


@check(
    "A11.09",
    11,
    "The Release workflow on the tag built, stitched and published every image",
    stages=AFTER_TAG,
    network=True,
)
def release_tag_run(ctx: Ctx) -> Outcome:
    run = ctx.run_for(ctx.release_commit(), "Release", "push", ctx.tag)
    jobs = ctx.jobs(run)
    problems = [f"{j['name']}: {j['conclusion']}" for j in jobs if j["conclusion"] != "success"]
    if len(jobs) < 10:
        problems.append(f"only {len(jobs)} jobs (6 builds + 3 manifests + release expected)")
    return verdict(problems, run["html_url"], run=run["html_url"])
