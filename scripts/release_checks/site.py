"""Phases 12-17: the docs, the README, and the live public site — checked as served, because
`main` being right has never meant GitHub Pages is."""

from __future__ import annotations

import html
import json
import re
import urllib.parse

from .constants import AFTER_TAG, INSTALLERS, MACOS_UNQUARANTINE, SITE_PAGES, SITE_ROUTES
from .core import (
    Ctx,
    Outcome,
    check,
    fail,
    http,
    ok,
    parallel_map,
    status_of,
    verdict,
    warn,
)
from .evaluate import markdown_links, parse_releases_ts

# ─── Phase 12/13 — documentation and README ────────────────────────────────────────────


@check("A12.01", 12, "Every relative link in docs/ and the README resolves")
def doc_links(ctx: Ctx) -> Outcome:
    broken = []
    for rel in [
        p
        for p in ctx.tracked()
        if p.endswith(".md") and (p.startswith("docs/") or p == "README.md")
    ]:
        for target in markdown_links(ctx.read(rel)):
            path = target.split("#", 1)[0]
            if not path or re.match(r"^[a-z]+:", path):
                continue
            if path.startswith("/"):
                if path.rstrip("/") not in SITE_ROUTES and not path.startswith("/docs/"):
                    broken.append(f"{rel} → {target} (no such site route)")
            elif not (ctx.root / rel).parent.joinpath(path).resolve().exists():
                broken.append(f"{rel} → {target}")
    return verdict([f"{len(broken)} broken"] if broken else [], "all resolve", broken=broken)


@check("A12.02", 12, "Every surface gives the same macOS first-launch command")
def first_launch_command(ctx: Ctx) -> Outcome:
    surfaces = (
        "frontend/app/(site)/download/page.tsx",
        "docs/getting-started/23-desktop-app.md",
        "docs/getting-started/24-troubleshooting.md",
        ".github/workflows/desktop.yml",
    )
    missing = [s for s in surfaces if MACOS_UNQUARANTINE not in ctx.read(s)]
    return verdict(
        [f"does not give `{MACOS_UNQUARANTINE}`: {missing}"] if missing else [],
        f"{len(surfaces)} surfaces agree",
    )


@check("A13.01", 13, "The README's pipeline diagram shows both human gates")
def readme_gates(ctx: Ctx) -> Outcome:
    # The README claimed one human gate for weeks after the design gate shipped.
    graph = ctx.read("backend/research_engine/graph.py")
    readme = ctx.read("README.md")
    wants = {"plan_gate_node": "DESIGN GATE", "hitl_gate_node": "REVIEW GATE"}
    missing = [label for node, label in wants.items() if node in graph and label not in readme]
    return verdict([f"the diagram lacks {missing}"] if missing else [], "design and review gates")


@check(
    "A13.02",
    13,
    "Every absolute link in the README answers",
    stages=("post-release",),
    network=True,
)
def readme_external_links(ctx: Ctx) -> Outcome:
    urls = sorted({u for u in markdown_links(ctx.read("README.md")) if u.startswith("http")})
    statuses = parallel_map(status_of, urls)
    bad = [f"{u} → {s}" for u, s in zip(urls, statuses, strict=True) if s >= 400]
    return verdict(bad, f"{len(urls)} links answer")


# ─── Phase 14 — landing page, and every internal link ──────────────────────────────────


def _hrefs(page: str) -> list[str]:
    return [html.unescape(h) for h in re.findall(r'href="([^"]+)"', page)]


def _page(ctx: Ctx, path: str) -> str:
    status, _h, body = ctx.fetch(path)
    if status != 200:
        raise AssertionError(f"{path} answered {status}")
    return body.decode()


@check(
    "A14.01",
    14,
    "The live landing page presents this release as current",
    stages=("post-release",),
    network=True,
)
def live_landing(ctx: Ctx) -> Outcome:
    page = _page(ctx, "/")
    problems = []
    new_in = set(re.findall(r"New in (?:<!-- -->)?(v\d+\.\d+\.\d+)", page))
    if new_in != {ctx.tag}:
        problems.append(f'"New in" names {sorted(new_in) or "nothing"}, not {ctx.tag}')
    ld = re.search(r'"softwareVersion":"([^"]+)"', page)
    if not ld or ld[1] != ctx.tag:
        problems.append(f"structured data says softwareVersion={ld[1] if ld else None}")
    return verdict(problems, f"New in {ctx.tag}; softwareVersion {ctx.tag}")


@check(
    "A14.02",
    14,
    "Every internal link on the five public pages answers, assets included",
    stages=("post-release",),
    network=True,
)
def live_links(ctx: Ctx) -> Outcome:
    base = ctx.base_path()
    prefix = ctx.site[: len(ctx.site) - len(base)] + base
    pages = parallel_map(lambda p: _page(ctx, p), SITE_PAGES)
    targets: set[str] = set()
    for path, text in zip(SITE_PAGES, pages, strict=True):
        for ref in _hrefs(text) + re.findall(r'src="([^"]+)"', text):
            url = urllib.parse.urljoin(ctx.site + path, ref).split("#", 1)[0]
            if url == prefix or url.startswith(prefix + "/"):
                targets.add(url)
    ordered = sorted(targets)
    statuses = parallel_map(lambda u: http(u, method="HEAD")[0], ordered, workers=24)
    broken = [f"{u} → {s}" for u, s in zip(ordered, statuses, strict=True) if s >= 400]
    # `_next/` is what .nojekyll protects; the favicon is what basePath did not cover.
    if not any("/_next/" in t for t in targets):
        broken.append("no `_next/` asset referenced — was the export's asset path lost?")
    if not any("icon" in t for t in targets):
        broken.append("no favicon referenced")
    return verdict(broken, f"{len(targets)} internal URLs answer", checked=len(targets))


@check(
    "A14.03",
    14,
    "robots.txt allows crawling and the sitemap names this site",
    stages=("post-release",),
    network=True,
)
def live_robots(ctx: Ctx) -> Outcome:
    robots, sitemap = parallel_map(lambda p: ctx.fetch(p)[2], ("/robots.txt", "/sitemap.xml"))
    problems = []
    if b"Allow: /" not in robots:
        problems.append("robots.txt does not allow crawling")
    if ctx.site.encode() not in sitemap:
        problems.append("sitemap.xml does not reference the site URL")
    return verdict(problems, "crawlable")


# ─── Phase 15 — download page ───────────────────────────────────────────────────────────


def _installer_urls(ctx: Ctx, version: str) -> list[str]:
    return [
        f"https://github.com/{ctx.repo}/releases/download/v{version}/{t.format(v=version)}"
        for t in INSTALLERS.values()
    ]


@check(
    "A15.01",
    15,
    "The live download page offers exactly this release's installers",
    stages=("post-release",),
    network=True,
)
def live_download(ctx: Ctx) -> Outcome:
    page = _page(ctx, "/download/")
    selected = re.search(r'<option value="([^"]+)" selected', page)
    links = {h for h in _hrefs(page) if "/releases/download/" in h}
    want = set(_installer_urls(ctx, ctx.version))
    problems = []
    if not selected or selected[1] != ctx.version:
        problems.append(f"the selector defaults to {selected[1] if selected else None}")
    if links != want:
        problems.append(f"missing {sorted(want - links)}; unexpected {sorted(links - want)}")
    return verdict(problems, f"4 installers of {ctx.tag}")


@check(
    "A15.02",
    15,
    "Every version the download page offers has all its files",
    stages=("post-release",),
    network=True,
)
def live_download_versions(ctx: Ctx) -> Outcome:
    offered = re.findall(r'<option value="([^"]+)"', _page(ctx, "/download/"))
    urls = [
        u
        for v in offered
        for u in (
            *_installer_urls(ctx, v),
            f"https://github.com/{ctx.repo}/archive/refs/tags/v{v}.zip",
        )
    ]
    statuses = parallel_map(lambda u: http(u, method="HEAD")[0], urls, workers=24)
    broken = [f"{u} → {s}" for u, s in zip(urls, statuses, strict=True) if s != 200]
    return verdict(
        [f"{len(broken)} of {len(urls)} do not answer 200"] if broken else [],
        f"{len(offered)} versions, {len(urls)} files answer",
        offered=offered,
        broken=broken,
    )


@check("A15.03", 15, "The download page builds the same file names the release publishes")
def download_names(ctx: Ctx) -> Outcome:
    page = ctx.read("frontend/app/(site)/download/page.tsx")
    built = {
        b.replace("${version}", "{v}")
        for b in re.findall(
            r"(Research\.Assistant_\$\{version\}_[\w.-]+?\.(?:dmg|msi|AppImage|deb))", page
        )
    }
    want = set(INSTALLERS.values())
    problems = (
        [] if built == want else [f"page builds {sorted(built)}; release publishes {sorted(want)}"]
    )
    if ctx.stage in AFTER_TAG and not ctx.offline:
        names = {a["name"] for a in ctx.release()["assets"]}
        missing = sorted(n for t in built if (n := t.format(v=ctx.version)) not in names)
        if missing:
            problems.append(f"the page would link {missing}, which the release does not have")
    return verdict(problems, "names agree")


# ─── Phase 16 — releases page ───────────────────────────────────────────────────────────


@check(
    "A16.01",
    16,
    "The live releases page leads with this release and links its tag",
    stages=("post-release",),
    network=True,
)
def live_releases(ctx: Ctx) -> Outcome:
    page = _page(ctx, "/releases/")
    first = re.search(r'id="(v\d+\.\d+\.\d+)"', page)
    problems = []
    if not first or first[1] != ctx.tag:
        problems.append(f"the first entry is {first[1] if first else None}")
    if f"/releases/tag/{ctx.tag}" not in page:
        problems.append("no link to the tag's GitHub Release")
    return verdict(problems, f"{ctx.tag} first")


@check(
    "A16.02",
    16,
    "The releases page and GitHub list the same releases",
    stages=AFTER_TAG,
    network=True,
)
def releases_match_github(ctx: Ctx) -> Outcome:
    site = {
        e["version"]
        for e in parse_releases_ts(ctx.read("frontend/lib/releases.ts"))
        if not e["unreleased"]
    }
    gh = {r["tag_name"] for r in ctx.releases() if not r["draft"]}
    problems = []
    # This release may still be unreleased on the site at the `published` stage.
    if gh - site - {ctx.tag}:
        problems.append(f"on GitHub, missing from the site: {sorted(gh - site - {ctx.tag})}")
    if site - gh:
        problems.append(f"on the site, no GitHub Release: {sorted(site - gh)}")
    return verdict(problems, f"{len(gh)} releases agree")


@check(
    "A16.03",
    16,
    "Each release's date on the site is the day its tag was cut",
    stages=AFTER_TAG,
    stop=False,
)
def release_dates(ctx: Ctx) -> Outcome:
    wrong = []
    for e in parse_releases_ts(ctx.read("frontend/lib/releases.ts")):
        dates = ctx.tag_dates(e["version"])
        if not e["unreleased"] and dates and e["date"] not in dates:
            wrong.append(f"{e['version']}: site {e['date']}, tag {'/'.join(sorted(dates))}")
    current = [w for w in wrong if w.startswith(ctx.tag + ":")]
    if current:
        return fail("; ".join(current))
    return warn("historical: " + "; ".join(wrong)) if wrong else ok("all match")


# ─── Phase 17 — what GitHub Pages is actually serving ──────────────────────────────────


def _latest_deployment(ctx: Ctx) -> dict:
    deployments = ctx.api(f"/repos/{ctx.repo}/deployments?environment=github-pages&per_page=5")
    if not deployments:
        raise AssertionError("no github-pages deployment")
    return deployments[0]


@check(
    "A17.01",
    17,
    "GitHub Pages last deployed origin/main, successfully",
    stages=("post-release",),
    network=True,
)
def pages_deployment(ctx: Ctx) -> Outcome:
    latest = _latest_deployment(ctx)
    statuses = ctx.api(f"/repos/{ctx.repo}/deployments/{latest['id']}/statuses")
    state = statuses[0]["state"] if statuses else None
    main = ctx.remote_main()
    problems = []
    if state != "success":
        problems.append(f"latest deployment is {state}")
    if latest["sha"] != main:
        problems.append(f"deployed {latest['sha'][:9]}, origin/main is {main[:9]}")
    return verdict(
        problems,
        f"{latest['sha'][:9]} deployed {latest['created_at']}",
        deployed=latest["sha"],
        main=main,
        created_at=latest["created_at"],
    )


@check(
    "A17.02",
    17,
    "The live site's build stamp names the deployed commit and this version",
    stages=("post-release",),
    network=True,
)
def pages_build_stamp(ctx: Ctx) -> Outcome:
    status, _h, body = ctx.fetch("/build.json")
    if status == 404:
        return warn(
            "no /build.json on the live site — built before pages.yml published one; "
            "A17.01's deployment record is the only evidence of what is served"
        )
    stamp = json.loads(body)
    deployed = _latest_deployment(ctx)
    problems = []
    if stamp.get("commit") != deployed["sha"]:
        problems.append(
            f"serves a build of {str(stamp.get('commit'))[:9]}, deployed {deployed['sha'][:9]}"
        )
    if stamp.get("version") != ctx.version:
        problems.append(f"built at VERSION {stamp.get('version')}")
    return verdict(
        problems, f"{str(stamp.get('commit'))[:9]} at {stamp.get('version')}", stamp=stamp
    )
