"""Phase 18: nothing secret ships, and the boundaries the docs promise are the ones built."""

from __future__ import annotations

import json
import re

from .constants import AFTER_TAG
from .core import Ctx, Outcome, check, parallel_map, verdict
from .evaluate import secret_hits


@check("A18.01", 18, "No secret-shaped string is tracked in the repository")
def secrets(ctx: Ctx) -> Outcome:
    def scan(p: str) -> list[str]:
        path = ctx.root / p
        if not path.is_file() or path.stat().st_size > 2_000_000:
            return []
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            return []
        return [f"{p}: {label}" for label in secret_hits(text)]

    hits = [h for found in parallel_map(scan, ctx.tracked(), workers=8) for h in found]
    return verdict(hits, "none")


@check("A18.02", 18, "No environment file other than .env.example is tracked")
def env_files(ctx: Ctx) -> Outcome:
    tracked = [
        p
        for p in ctx.tracked()
        if re.search(r"(^|/)\.env(\.|$)", p) and not p.endswith(".env.example")
    ]
    return verdict([f"tracked: {tracked}"] if tracked else [], "only .env.example")


@check("A18.03", 18, "The desktop WebView can reach only its own engine")
def desktop_csp(ctx: Ctx) -> Outcome:
    # The update check runs through the sidecar precisely so this stays sealed.
    csp = json.loads(ctx.read("desktop/tauri.conf.json"))["app"]["security"]["csp"]
    connect = re.search(r"connect-src ([^;]+)", csp)
    sources = connect[1].split() if connect else []
    remote = [
        s
        for s in sources
        if s not in ("ipc:", "http://ipc.localhost", "http://127.0.0.1:*", "'self'")
    ]
    return verdict([f"connect-src allows {remote}"] if remote else [], " ".join(sources))


@check("A18.04", 18, "In the full stack only the frontend publishes a port")
def compose_ports(ctx: Ctx) -> Outcome:
    # README: "The frontend is the only published service" — the database is never exposed.
    current, exposed = None, []
    for line in ctx.read("docker-compose.full.yml").splitlines():
        if m := re.match(r"^  ([a-z][\w-]*):\s*$", line):
            current = m[1]
        elif re.match(r"^    ports:", line) and current != "frontend":
            exposed.append(current)
    return verdict([f"also publishes ports: {exposed}"] if exposed else [], "frontend only")


@check(
    "A18.05",
    18,
    "No open code-scanning alert, no open high or critical dependency alert",
    stages=("pre-tag", *AFTER_TAG),
    network=True,
)
def security_alerts(ctx: Ctx) -> Outcome:
    code, deps = parallel_map(
        ctx.api,
        (
            f"/repos/{ctx.repo}/code-scanning/alerts?state=open&per_page=100",
            f"/repos/{ctx.repo}/dependabot/alerts?state=open&per_page=100",
        ),
    )
    severe = [a for a in deps if a["security_advisory"]["severity"] in ("high", "critical")]
    problems = []
    if code:
        problems.append(f"{len(code)} open code-scanning alert(s)")
    if severe:
        problems.append(f"{len(severe)} open high/critical dependency alert(s)")
    return verdict(
        problems, f"0 code-scanning, {len(deps)} dependency alerts open (none high/critical)"
    )
