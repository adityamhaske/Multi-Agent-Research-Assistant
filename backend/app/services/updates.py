"""
Whether a newer release exists — and, when that cannot be established, saying so.

`build_info()` already answers "what am I?"; this answers "is there something newer?".
The two are deliberately separate: the first is a fact the build carries and can always
state, the second is a *measurement over the network* and can fail.

**Four answers, not two.** "Up to date" and "update available" are the two anyone plans
for. The other two are the ones that make this honest:

- `check_failed` — offline, rate-limited, GitHub down, DNS broken. The user is told the
  check did not happen. Rendering this as "up to date" would be the unmeasured-vs-zero
  bug `AGENTS.md` treats as P0: a reassuring answer nobody measured, whose consequence is
  a user who never learns an update exists.
- `unknown_local_version` — a source checkout has no `_build.py` by design, so
  `build_info()` answers `unknown`. There is nothing to compare, and guessing "older"
  would offer every developer a download they do not want.

**Where the call happens, and why it is here rather than in the browser.** The desktop
WebView's CSP (`desktop/tauri.conf.json`) allows `connect-src` to `ipc:` and
`127.0.0.1:*` only, so a `fetch` to github.com from the frontend is blocked outright.
Loosening the CSP to permit it would trade a real security boundary for a convenience;
running the call here instead keeps the WebView sealed and puts this host's one outbound
request where the rest of the app's egress already lives.

**Stdlib and httpx only.** The sidecar imports this at request time, so it may not reach
`app.config` — an installed desktop app has no `DATABASE_URL` or `JWT_SECRET_KEY` to build
`Settings` from (#50), and `test_sidecar_startup.py` fails if this module grows such an
import.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

import httpx

#: The releases endpoint, hardcoded. Never built from user input, so there is no SSRF
#: surface here and no need for the guard the corpus and retriever paths carry.
RELEASES_URL = (
    "https://api.github.com/repos/adityamhaske/Multi-Agent-Research-Assistant/releases/latest"
)

#: Short: this runs behind a button a person is waiting on. A check that hangs for 30s
#: reads as a broken app, and "we could not reach GitHub quickly" is a perfectly good
#: answer to show them.
TIMEOUT_SECONDS = 8.0

UpdateState = Literal["up_to_date", "update_available", "check_failed", "unknown_local_version"]

_VERSION = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)")


class UnknownVersion(ValueError):
    """A version string that cannot be compared, rather than one that compares as older."""


@dataclass(frozen=True)
class UpdateCheck:
    """What the check found. `state` is the whole answer; the rest is detail for the UI."""

    state: UpdateState
    running_version: str
    #: What the latest release is, when that much was established. `None` only when the
    #: check itself failed — note that `unknown_local_version` still carries it, because
    #: that half *was* measured.
    latest_version: str | None = None
    release_url: str | None = None
    #: Why, when `state` is `check_failed`. Shown to the user: a failure they cannot see
    #: the reason for is one they cannot act on.
    detail: str = ""


def _parts(version: str | None) -> tuple[int, int, int]:
    if not isinstance(version, str):
        raise UnknownVersion(f"not a version string: {version!r}")
    found = _VERSION.match(version.strip())
    if not found:
        raise UnknownVersion(f"not a version string: {version!r}")
    return tuple(int(g) for g in found.groups())  # type: ignore[return-value]


def is_newer(*, running: str | None, latest: str | None) -> bool:
    """Whether `latest` is a later release than `running`.

    Numeric, per component. Lexical comparison puts `2.0.10` before `2.0.9`, which is
    wrong for exactly the releases where anyone is still paying attention.

    Raises `UnknownVersion` rather than returning a verdict when either side cannot be
    parsed — the caller has a state for that and needs to reach it.
    """
    return _parts(latest) > _parts(running)


async def check(running_version: str, transport: httpx.BaseTransport | None = None) -> UpdateCheck:
    """Ask GitHub for the newest release and compare it to this build.

    `transport` is injectable so the tests can drive every branch — including the network
    failures, which are the branches that matter — without a live call.
    """
    try:
        async with httpx.AsyncClient(
            transport=transport,
            timeout=TIMEOUT_SECONDS,
            follow_redirects=True,
            headers={"Accept": "application/vnd.github+json"},
        ) as client:
            response = await client.get(RELEASES_URL)
        if response.status_code != 200:
            return UpdateCheck(
                state="check_failed",
                running_version=running_version,
                detail=f"GitHub answered {response.status_code}.",
            )
        tag = response.json().get("tag_name")
        release_url = response.json().get("html_url")
    except Exception as e:  # noqa: BLE001 — every failure here is the same answer to a user
        # Deliberately broad: a DNS error, a timeout, a TLS failure and a body that is not
        # JSON are one outcome from where the user sits — the check did not happen. What
        # must never happen is any of them reaching the "up to date" branch below.
        return UpdateCheck(
            state="check_failed",
            running_version=running_version,
            detail=f"Could not reach GitHub: {type(e).__name__}.",
        )

    if not isinstance(tag, str) or not _VERSION.match(tag.strip()):
        return UpdateCheck(
            state="check_failed",
            running_version=running_version,
            detail="GitHub's response did not name a release version.",
        )

    latest = tag.strip().lstrip("v")
    try:
        newer = is_newer(running=running_version, latest=latest)
    except UnknownVersion:
        # This build never recorded its version. The release *is* known, so report it and
        # let the person decide; what we cannot do is claim they are behind or current.
        return UpdateCheck(
            state="unknown_local_version",
            running_version=running_version,
            latest_version=latest,
            release_url=release_url,
            detail="This build did not record its own version, so it cannot be compared.",
        )

    return UpdateCheck(
        state="update_available" if newer else "up_to_date",
        running_version=running_version,
        latest_version=latest,
        release_url=release_url,
    )
