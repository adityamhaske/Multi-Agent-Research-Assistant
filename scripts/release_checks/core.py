"""
The machinery every check module shares: the registry, the context a check reads the world
through, and the network clients.

**Checks run concurrently** (`release_audit.py --jobs`), so the context is written for that:
every cache is filled under a lock, nothing a check does mutates shared state, and the one
operation that writes to the repository — fetching `main` and the tags — happens once in
`Ctx.prepare()`, before any check starts, instead of inside whichever checks need it (two
concurrent `git fetch`es race for the same ref lock). Checks that make many independent
requests fan them out through `parallel_map`, which is where the time actually goes.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import subprocess
import threading
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .constants import AFTER_TAG, FAIL, PASS, SKIP, STAGES, WARN
from .evaluate import id_key, parse_version

ROOT = Path(__file__).resolve().parents[2]


# ─── Results and the registry ───────────────────────────────────────────────────────────


@dataclass
class Outcome:
    status: str
    detail: str
    evidence: dict = field(default_factory=dict)


class Unavailable(Exception):
    """The check could not measure. Never a pass: unmeasured is not zero."""


@dataclass
class Check:
    id: str
    phase: int
    title: str
    stages: tuple[str, ...]
    network: bool
    stop: bool
    group: str
    fn: Callable[[Ctx], Outcome]


REGISTRY: list[Check] = []


def check(
    cid: str,
    phase: int,
    title: str,
    *,
    stages: Iterable[str] = STAGES,
    network: bool = False,
    stop: bool = True,
):
    """Register a check. Its group is the module it lives in, which `--group` selects on."""

    def register(fn: Callable[[Ctx], Outcome]) -> Callable[[Ctx], Outcome]:
        group = fn.__module__.rsplit(".", 1)[-1]
        REGISTRY.append(Check(cid, phase, title, tuple(stages), network, stop, group, fn))
        REGISTRY.sort(key=lambda c: id_key(c.id))
        return fn

    return register


def ok(detail: str, **evidence) -> Outcome:
    return Outcome(PASS, detail, evidence)


def fail(detail: str, **evidence) -> Outcome:
    return Outcome(FAIL, detail, evidence)


def warn(detail: str, **evidence) -> Outcome:
    return Outcome(WARN, detail, evidence)


def skip(detail: str, **evidence) -> Outcome:
    return Outcome(SKIP, detail, evidence)


def verdict(problems: list[str], success: str, **evidence) -> Outcome:
    return fail("; ".join(problems), **evidence) if problems else ok(success, **evidence)


def parallel_map(fn: Callable[[Any], Any], items: Iterable[Any], workers: int = 16) -> list:
    """`map`, concurrently, in order — for the many-small-requests checks (link crawls,
    per-version download probes, per-image registry reads)."""
    items = list(items)
    if len(items) <= 1:
        return [fn(i) for i in items]
    with ThreadPoolExecutor(max_workers=min(workers, len(items))) as pool:
        return list(pool.map(fn, items))


# ─── HTTP ───────────────────────────────────────────────────────────────────────────────


class _KeepMethodRedirect(urllib.request.HTTPRedirectHandler):
    """urllib turns a redirected HEAD into a GET, which would download every installer to
    learn that it exists. GitHub serves release assets through a redirect, so keep HEAD."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is not None and req.get_method() == "HEAD":
            new.method = "HEAD"
        return new


OPENER = urllib.request.build_opener(_KeepMethodRedirect)


def http(url: str, method: str = "GET", headers: dict | None = None, timeout: float = 60):
    """(status, headers, body). Raises Unavailable when nothing answered at all."""
    req = urllib.request.Request(url, method=method, headers=headers or {})
    req.add_header("User-Agent", "release-audit")
    try:
        with OPENER.open(req, timeout=timeout) as resp:  # noqa: S310 — https URLs we build
            return resp.status, dict(resp.headers), resp.read() if method != "HEAD" else b""
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers or {}), exc.read() if method != "HEAD" else b""
    except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
        raise Unavailable(f"{url} did not answer: {exc}") from exc


def status_of(url: str) -> int:
    """HEAD, falling back to GET for hosts that refuse HEAD, before judging a link."""
    status, _h, _b = http(url, method="HEAD")
    if status in (403, 405):
        status, _h, _b = http(url)
    return status


# ─── Context ────────────────────────────────────────────────────────────────────────────


class Ctx:
    def __init__(self, args) -> None:
        self.root: Path = args.root
        self.version: str = args.version
        self.tag = f"v{self.version}"
        self.stage: str = args.stage
        self.offline: bool = args.offline or args.stage == "ci"
        self.download: bool = args.download
        self.docker: bool = args.docker
        self.repo: str = args.repo or self._repo_from_releases_ts()
        self.site: str = (args.site or self._site_url()).rstrip("/")
        self.record_path = self.root / "release-audit" / self.tag / "record.md"
        self._previous = args.previous
        self._cache: dict = {}
        self._lock = threading.Lock()
        self._token: str | None = None
        self.notes: list[str] = []

    def prepare(self) -> None:
        """Everything that writes shared state, done once before any check runs."""
        if not self.offline:
            fetched = subprocess.run(
                ["git", "fetch", "-q", "--tags", "origin", "main"],
                cwd=self.root,
                capture_output=True,
                text=True,
                check=False,
            )
            if fetched.returncode != 0:
                self.notes.append(f"git fetch failed: {fetched.stderr.strip()[:200]}")
            self.token()

    def memo(self, key, compute: Callable[[], Any]) -> Any:
        with self._lock:
            if key in self._cache:
                return self._cache[key]
        value = compute()  # outside the lock: a duplicate fetch is cheaper than serialising
        with self._lock:
            return self._cache.setdefault(key, value)

    # repository
    def read(self, rel: str) -> str:
        return (self.root / rel).read_text(encoding="utf-8")

    def git(self, *args: str, check: bool = True) -> str:
        proc = subprocess.run(
            ["git", *args], cwd=self.root, capture_output=True, text=True, check=False
        )
        if check and proc.returncode != 0:
            raise RuntimeError(f"git {' '.join(args)}: {proc.stderr.strip()}")
        return proc.stdout.strip() if proc.returncode == 0 else ""

    def git_ok(self, *args: str) -> bool:
        return (
            subprocess.run(
                ["git", *args], cwd=self.root, capture_output=True, check=False
            ).returncode
            == 0
        )

    def show(self, ref: str, rel: str) -> str | None:
        proc = subprocess.run(
            ["git", "show", f"{ref}:{rel}"], cwd=self.root, capture_output=True, check=False
        )
        return proc.stdout.decode("utf-8") if proc.returncode == 0 else None

    def tracked(self) -> list[str]:
        return self.memo("tracked", lambda: self.git("ls-files").splitlines())

    def tag_commit(self, tag: str | None = None) -> str | None:
        return self.git("rev-list", "-n1", tag or self.tag, check=False) or None

    def release_commit(self) -> str:
        """What is being released: HEAD before the tag exists, the tag's commit after."""
        if self.stage in AFTER_TAG:
            sha = self.tag_commit()
            if not sha:
                raise Unavailable(f"{self.tag} does not exist locally — `git fetch --tags`")
            return sha
        return self.git("rev-parse", "HEAD")

    def remote_main(self) -> str:
        return self.memo(
            "remote-main",
            lambda: self.git("ls-remote", "origin", "refs/heads/main", check=False).split("\t")[0],
        )

    def previous_tag(self) -> str | None:
        if self._previous:
            return self._previous
        cur = parse_version(self.version)
        tags = [
            (pv, t)
            for t in self.git("tag", "-l", "v*").split()
            if (pv := parse_version(t)) and "-" not in t and pv < cur
        ]
        return max(tags)[1] if tags else None

    def tag_dates(self, tag: str) -> set[str]:
        """A tag's date as its tagger saw it and in UTC — a releases.ts date matching either
        is right, because which one a person writes depends on where they were standing."""
        raw = self.git(
            "for-each-ref",
            "--format=%(taggerdate:iso-strict)%(creatordate:iso-strict)",
            f"refs/tags/{tag}",
            check=False,
        )
        if not raw:
            return set()
        when = datetime.fromisoformat(raw[:25])
        return {when.date().isoformat(), when.astimezone(UTC).date().isoformat()}

    def _repo_from_releases_ts(self) -> str:
        m = re.search(
            r'REPOSITORY_URL = "https://github\.com/([^"]+)"', self.read("frontend/lib/releases.ts")
        )
        return m[1] if m else "adityamhaske/Multi-Agent-Research-Assistant"

    def _site_url(self) -> str:
        # The same decision pages.yml makes: a CUSTOM_DOMAIN file serves from its root.
        custom = self.root / "CUSTOM_DOMAIN"
        if custom.exists() and custom.read_text().strip():
            return f"https://{custom.read_text().strip()}"
        owner, name = self.repo.split("/")
        return f"https://{owner.lower()}.github.io/{name}"

    def base_path(self) -> str:
        return urllib.parse.urlparse(self.site).path.rstrip("/")

    # GitHub
    def token(self) -> str | None:
        with self._lock:
            if self._token is None:
                self._token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN") or ""
                if not self._token and shutil.which("gh"):
                    proc = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True)
                    self._token = proc.stdout.strip() if proc.returncode == 0 else ""
            return self._token or None

    def api(self, path: str, *, allow: tuple[int, ...] = ()):
        if self.offline:
            raise Unavailable("offline")

        def fetch():
            headers = {"Accept": "application/vnd.github+json"}
            if self.token():
                headers["Authorization"] = f"Bearer {self.token()}"
            status, _h, body = http(f"https://api.github.com{path}", headers=headers)
            if status in allow:
                return (status, None)
            if status >= 400:
                return (status, body[:200])
            return (status, json.loads(body))

        status, payload = self.memo(("api", path), fetch)
        if status >= 400 and status not in allow:
            raise Unavailable(f"GitHub API {path} answered {status}: {payload!r}")
        return payload

    def release(self) -> dict:
        found = self.api(f"/repos/{self.repo}/releases/tags/{self.tag}", allow=(404,))
        if found is None:
            raise Unavailable(f"no GitHub Release for {self.tag} yet")
        return found

    def releases(self) -> list[dict]:
        return self.api(f"/repos/{self.repo}/releases?per_page=100")

    def run_for(self, sha: str, workflow: str, event: str, branch: str | None = None) -> dict:
        runs = self.api(f"/repos/{self.repo}/actions/runs?head_sha={sha}&per_page=100")
        found = [
            r
            for r in runs["workflow_runs"]
            if r["name"] == workflow
            and r["event"] == event
            and (branch is None or r["head_branch"] == branch)
        ]
        if not found:
            raise Unavailable(f"no {workflow} run ({event}) for {sha[:9]}")
        return max(found, key=lambda r: (r["run_attempt"], r["id"]))

    def jobs(self, run: dict) -> list[dict]:
        return self.api(f"/repos/{self.repo}/actions/runs/{run['id']}/jobs?per_page=100")["jobs"]

    def fetch(self, path: str, method: str = "GET"):
        if self.offline:
            raise Unavailable("offline")
        url = self.site + "/" + path.lstrip("/")
        if method != "GET":
            return http(url, method=method)
        return self.memo(("site", url), lambda: http(url))

    # container registry — anonymous on purpose: the audit must see what an anonymous
    # `docker pull` sees, not what the maintainer's credentials can reach.
    def ghcr(self, image: str, ref: str, *, blob: bool = False):
        if self.offline:
            raise Unavailable("offline")
        name = f"{self.repo.lower()}-{image}"

        def token():
            status, _h, body = http(f"https://ghcr.io/token?scope=repository:{name}:pull")
            if status != 200:
                raise Unavailable(f"no registry token for {name} ({status})")
            return json.loads(body)["token"]

        headers = {"Authorization": f"Bearer {self.memo(('ghcr-token', name), token)}"}
        if not blob:
            headers["Accept"] = ", ".join(
                (
                    "application/vnd.oci.image.index.v1+json",
                    "application/vnd.docker.distribution.manifest.list.v2+json",
                    "application/vnd.oci.image.manifest.v1+json",
                    "application/vnd.docker.distribution.manifest.v2+json",
                )
            )
        kind = "blobs" if blob else "manifests"

        def get():
            return http(f"https://ghcr.io/v2/{name}/{kind}/{ref}", headers=headers)

        status, hdrs, body = self.memo(("ghcr", name, kind, ref), get)
        if status == 404:
            return None, None
        if status >= 400:
            raise Unavailable(f"registry answered {status} for {name}:{ref}")
        return json.loads(body), {k.lower(): v for k, v in hdrs.items()}


# ─── Shared readers ─────────────────────────────────────────────────────────────────────


def load_sync_version(root: Path):
    """`scripts/sync_version.py` is the one list of derived version constants; reuse it."""
    spec = importlib.util.spec_from_file_location("sync_version", root / "scripts/sync_version.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def user_facing_files(ctx: Ctx) -> dict[str, str]:
    """Text a user reads or a release publishes, minus what is a version history by design:
    the changelog and `releases.ts` name every version on purpose, and `governance/` is never
    published."""

    def collect():
        out = {}
        for p in ctx.tracked():
            take = (
                p in ("README.md", "deploy/README.md")
                or p in (".github/workflows/desktop.yml", ".github/workflows/release.yml")
                or (
                    p.startswith("docs/")
                    and p.endswith(".md")
                    and not p.startswith("docs/governance/")
                    and p != "docs/project/37-changelog.md"
                )
                or (
                    p.startswith("frontend/")
                    and p.endswith((".ts", ".tsx"))
                    and ".test." not in p
                    and "/e2e/" not in p
                    and "__fixtures__" not in p
                    and not p.startswith("frontend/scripts/")
                    and p != "frontend/lib/releases.ts"
                )
            )
            if take and (ctx.root / p).is_file():
                out[p] = ctx.read(p)
        return out

    return ctx.memo("user-facing", collect)


def load_allowlist(ctx: Ctx) -> list[dict]:
    path = ctx.root / "release-audit" / "historical-references.json"
    return json.loads(path.read_text(encoding="utf-8"))["references"] if path.exists() else []


__all__ = [
    "AFTER_TAG",
    "FAIL",
    "PASS",
    "SKIP",
    "STAGES",
    "WARN",
    "REGISTRY",
    "Check",
    "Ctx",
    "Outcome",
    "Unavailable",
    "check",
    "fail",
    "http",
    "load_allowlist",
    "load_sync_version",
    "ok",
    "parallel_map",
    "skip",
    "status_of",
    "user_facing_files",
    "verdict",
    "warn",
]
