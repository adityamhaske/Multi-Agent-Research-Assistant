"""Phase 10: the container images, as an anonymous `docker pull` sees them."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess

from .constants import AFTER_TAG, IMAGES, PLATFORMS
from .core import Ctx, Outcome, Unavailable, check, fail, ok, parallel_map, skip, verdict
from .evaluate import parse_version


def _index(ctx: Ctx, image: str, ref: str) -> tuple[dict | None, str | None]:
    manifest, headers = ctx.ghcr(image, ref)
    return manifest, (headers or {}).get("docker-content-digest")


def _platforms(index: dict) -> set[str]:
    return {
        f"{m['platform']['os']}/{m['platform']['architecture']}"
        for m in index.get("manifests", [])
        if "platform" in m
    }


@check(
    "A10.01",
    10,
    "api, worker and frontend are published at X.Y.Z and X.Y for amd64 and arm64",
    stages=AFTER_TAG,
    network=True,
)
def images_exist(ctx: Ctx) -> Outcome:
    major_minor = ".".join(ctx.version.split(".")[:2])
    pairs = [(image, ref) for image in IMAGES for ref in (ctx.version, major_minor)]
    found = parallel_map(lambda p: _index(ctx, *p), pairs)
    problems, digests = [], {}
    for (image, ref), (index, digest) in zip(pairs, found, strict=True):
        if index is None:
            problems.append(f"{image}:{ref} does not exist")
            continue
        digests[f"{image}:{ref}"] = digest
        problems += [f"{image}:{ref} lacks {p}" for p in PLATFORMS if p not in _platforms(index)]
    return verdict(problems, f"{len(pairs)} tags, both architectures", digests=digests)


@check("A10.02", 10, "`latest` is this release", stages=AFTER_TAG, network=True)
def images_latest(ctx: Ctx) -> Outcome:
    newest = max(
        (
            parse_version(r["tag_name"])
            for r in ctx.releases()
            if not r["draft"] and not r["prerelease"] and parse_version(r["tag_name"])
        ),
        default=None,
    )
    if newest and newest > parse_version(ctx.version):
        return skip(f"a newer release exists ({'.'.join(map(str, newest))}); latest is its")
    pairs = [(image, ref) for image in IMAGES for ref in (ctx.version, "latest")]
    digests = dict(
        zip(pairs, (d for _i, d in parallel_map(lambda p: _index(ctx, *p), pairs)), strict=True)
    )
    problems = [
        f"{image}:latest is {str(digests[(image, 'latest')])[:19]}, "
        f"{ctx.version} is {str(digests[(image, ctx.version)])[:19]}"
        for image in IMAGES
        if digests[(image, "latest")] != digests[(image, ctx.version)]
    ]
    return verdict(problems, "latest = " + ctx.version)


def _provenance(ctx: Ctx, image: str, index: dict, attestation: dict) -> tuple[str, str | None]:
    subject = attestation["annotations"]["vnd.docker.reference.digest"]
    platform = next(
        (
            f"{x['platform']['os']}/{x['platform']['architecture']}"
            for x in index["manifests"]
            if x["digest"] == subject
        ),
        "?",
    )
    manifest, _h = ctx.ghcr(image, attestation["digest"])
    layer = next(
        (
            layer
            for layer in manifest["layers"]
            if "provenance" in layer.get("annotations", {}).get("in-toto.io/predicate-type", "")
        ),
        None,
    )
    if layer is None:
        return platform, None
    statement, _h = ctx.ghcr(image, layer["digest"], blob=True)
    revision = re.search(r'"vcs:revision": "([0-9a-f]{40})"', json.dumps(statement))
    return platform, revision[1] if revision else None


@check(
    "A10.03",
    10,
    "Every published image was built from the tagged commit (provenance)",
    stages=AFTER_TAG,
    network=True,
)
def images_provenance(ctx: Ctx) -> Outcome:
    sha = ctx.release_commit()
    work, problems = [], []
    for image, (index, _d) in zip(
        IMAGES, parallel_map(lambda i: _index(ctx, i, ctx.version), IMAGES), strict=True
    ):
        if index is None:
            problems.append(f"{image}:{ctx.version} missing")
            continue
        work += [
            (image, index, m)
            for m in index.get("manifests", [])
            if (m.get("annotations") or {}).get("vnd.docker.reference.type")
            == "attestation-manifest"
        ]
    seen = {}
    for (image, _i, _m), (platform, revision) in zip(
        work, parallel_map(lambda w: _provenance(ctx, *w), work), strict=True
    ):
        seen[f"{image} {platform}"] = revision
        if revision != sha:
            problems.append(f"{image} {platform} was built from {str(revision)[:9]}, not {sha[:9]}")
    if len(seen) < len(IMAGES) * len(PLATFORMS) and not problems:
        problems.append(f"only {len(seen)} of {len(IMAGES) * len(PLATFORMS)} carry provenance")
    return verdict(problems, f"all {len(seen)} built from {sha[:9]}", revisions=seen)


@check("A10.04", 10, "The documented deploy path pulls a released image, not a stale moving tag")
def deploy_default_tag(ctx: Ctx) -> Outcome:
    # `edge` was the bootstrap's default while no release existed, and stayed the default
    # after: a fresh deploy in September 2026 pulled a pre-1.0 build from 5 August.
    boot = re.search(r"^IMAGE_TAG=(\S+)", ctx.read("deploy/oracle-bootstrap.sh"), re.M)
    demo = re.search(r"IMAGE_TAG:-([^}]+)\}", ctx.read("deploy/docker-compose.demo.yml"))
    tags = {
        "deploy/oracle-bootstrap.sh": boot[1] if boot else None,
        "deploy/docker-compose.demo.yml": demo[1] if demo else None,
    }
    bad = {f: t for f, t in tags.items() if t not in ("latest", ctx.version)}
    if bad:
        return fail(f"deploy defaults to {bad} — a tag no release moves", defaults=tags)
    return ok(f"deploy defaults: {tags}")


@check(
    "A10.05",
    10,
    "A running api image reports the tagged commit and version",
    stages=AFTER_TAG,
    network=True,
)
def image_identity(ctx: Ctx) -> Outcome:
    if not ctx.docker:
        raise Unavailable("pass --docker to pull and run the api image")
    if not shutil.which("docker"):
        raise Unavailable("docker is not installed")
    ref = f"ghcr.io/{ctx.repo.lower()}-api:{ctx.version}"
    pulled = subprocess.run(["docker", "pull", "-q", ref], capture_output=True, text=True)
    if pulled.returncode != 0:
        raise Unavailable(f"docker pull {ref}: {pulled.stderr.strip()[:200]}")
    # Read APP_VERSION from the file rather than importing the app: `app.config` validates a
    # DSN and a signing key at import, which this probe has no reason to supply.
    probe = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--entrypoint",
            "python",
            ref,
            "-c",
            "import json, re, pathlib; from research_engine.build_info import build_info; "
            'v = re.search(r\'^APP_VERSION = "([^"]+)"\', '
            "pathlib.Path('app/main.py').read_text(), re.M); "
            "print(json.dumps({**build_info().as_dict(), 'app_version': v and v[1]}))",
        ],
        capture_output=True,
        text=True,
        env=dict(os.environ),
    )
    if probe.returncode != 0:
        return fail(f"the image could not report its build: {probe.stderr.strip()[-300:]}")
    info = json.loads(probe.stdout.strip().splitlines()[-1])
    sha = ctx.release_commit()
    problems = []
    if info.get("app_version") != ctx.version:
        problems.append(f"/health would report {info.get('app_version')}")
    if info.get("git_sha") != sha:
        problems.append(
            f"/api/v1/version reports git_sha={info.get('git_sha')}, not {sha[:9]} "
            "— the image was not stamped"
        )
    return verdict(problems, f"{ctx.version} at {sha[:9]}", build=info)
