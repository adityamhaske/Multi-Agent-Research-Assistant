"""
"Is there a newer version?" is a measurement, so it can fail to be taken.

The states this pins exist because there are four different true answers, and three of
them are not "you are up to date":

- the check ran and found nothing newer
- the check ran and found something newer
- the check could not run (offline, GitHub down, a timeout)
- this build never recorded its own version, so there is nothing to compare against

Collapsing the last two into the first is the unmeasured-vs-zero bug `AGENTS.md` calls a
P0 class, wearing different clothes. An update checker that answers "you're up to date"
when it could not reach the network has not told the user something reassuring; it has told
them something false, and the failure mode is that they never update.

The comparison itself is pinned separately because `2.0.10` sorts before `2.0.9` as text,
and a version check that is wrong only after the tenth patch release is a check that will
be wrong exactly when it is load-bearing.
"""

from __future__ import annotations

import httpx
import pytest

from app.services import updates

# ── Comparing two versions ────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("running", "latest", "newer"),
    [
        ("2.0.1", "2.0.2", True),
        ("2.0.2", "2.0.2", False),
        ("2.0.3", "2.0.2", False),  # a dev build ahead of the last release
        # Text sorting says "2.0.10" < "2.0.9". Numeric comparison is the whole reason
        # this function exists rather than a `!=`.
        ("2.0.9", "2.0.10", True),
        ("2.0.10", "2.0.9", False),
        ("2.0.2", "2.1.0", True),
        ("2.0.2", "3.0.0", True),
        ("10.0.0", "9.9.9", False),
        # The tag carries a `v`; `VERSION` does not. Whichever way round, same answer.
        ("2.0.1", "v2.0.2", True),
    ],
)
def test_is_newer_compares_numerically_not_lexically(running, latest, newer):
    assert updates.is_newer(running=running, latest=latest) is newer


@pytest.mark.parametrize("bad", ["unknown", "", "not-a-version", "2.x", None])
def test_an_unparseable_version_is_never_silently_treated_as_older(bad):
    """`build_info()` answers `unknown` for an unstamped source checkout, on purpose. That
    must not read as "older than the release", which would offer every developer running
    from source a download they do not want."""
    with pytest.raises(updates.UnknownVersion):
        updates.is_newer(running=bad, latest="2.0.2")


# ── The four answers ──────────────────────────────────────────────────────────────


def _github(status: int = 200, tag: str = "v2.0.3"):
    """A stand-in for the releases API, returning what the real one returns."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status,
            json={"tag_name": tag, "html_url": f"https://github.com/o/r/releases/tag/{tag}"},
        )

    return httpx.MockTransport(handler)


async def test_a_newer_release_is_reported_with_where_to_get_it():
    result = await updates.check(running_version="2.0.2", transport=_github(tag="v2.0.3"))
    assert result.state == "update_available"
    assert result.latest_version == "2.0.3"
    assert result.release_url.endswith("/releases/tag/v2.0.3")


async def test_the_current_release_reports_up_to_date():
    result = await updates.check(running_version="2.0.3", transport=_github(tag="v2.0.3"))
    assert result.state == "up_to_date"
    assert result.latest_version == "2.0.3"


async def test_a_network_failure_is_not_reported_as_up_to_date():
    """The assertion this file exists for.

    Negative control: return `up_to_date` from the failure branch and this is the only
    test that objects — every other state still passes, and the app quietly stops telling
    anyone about updates.
    """

    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route to host")

    result = await updates.check(running_version="2.0.2", transport=httpx.MockTransport(refuse))
    assert result.state == "check_failed"
    assert result.state != "up_to_date"
    assert result.detail, "a failed check must say why, or the user cannot act on it"
    assert result.latest_version is None


async def test_a_github_error_status_is_a_failed_check_not_a_verdict():
    """Rate limiting (403) and outages (5xx) answer with a body that is not a release."""
    result = await updates.check(running_version="2.0.2", transport=_github(status=503))
    assert result.state == "check_failed"
    assert "503" in result.detail


async def test_an_unstamped_build_says_so_rather_than_comparing():
    """A source checkout has no `_build.py`, so `build_info()` answers `unknown`."""
    result = await updates.check(running_version="unknown", transport=_github(tag="v2.0.3"))
    assert result.state == "unknown_local_version"
    # It still reports what the latest release is — that part *was* measured.
    assert result.latest_version == "2.0.3"


async def test_a_malformed_release_payload_is_a_failed_check():
    """A 200 whose body is not what we expect is not a verdict either."""

    def nonsense(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"unexpected": "shape"})

    result = await updates.check(running_version="2.0.2", transport=httpx.MockTransport(nonsense))
    assert result.state == "check_failed"


# ── The route ─────────────────────────────────────────────────────────────────────


async def test_the_desktop_serves_the_check_behind_its_token(monkeypatch):
    import tempfile

    from desktop.sidecar import create_sidecar_app

    async def _fixed(running_version, transport=None):  # noqa: ARG001
        return updates.UpdateCheck(
            state="update_available",
            running_version=running_version,
            latest_version="9.9.9",
            release_url="https://example.invalid/releases/tag/v9.9.9",
        )

    monkeypatch.setattr(updates, "check", _fixed)

    app = create_sidecar_app(data_dir=tempfile.mkdtemp(), token="upd", fake=True)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://d.invalid") as client:
        assert (await client.get("/api/v1/updates/check")).status_code == 401
        resp = await client.get("/api/v1/updates/check", headers={"Authorization": "Bearer upd"})
    assert resp.status_code == 200
    assert resp.json()["state"] == "update_available"
    assert resp.json()["latest_version"] == "9.9.9"


def test_the_capability_is_declared_by_both_hosts():
    """Desktop can point you at a new build; the server is updated by pulling an image."""
    from app.schemas.capabilities import DESKTOP, SERVER

    assert DESKTOP.update_check is True
    assert SERVER.update_check is False


def test_the_checker_never_reaches_server_configuration():
    """The sidecar imports this at request time, so it may not pull `app.config` (#50)."""
    import subprocess
    import sys

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys, app.services.updates; print('app.config' in sys.modules)",
        ],
        capture_output=True,
        text=True,
        check=False,
        cwd=str(__import__("pathlib").Path(__file__).resolve().parents[2]),
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "False", "app.services.updates pulled in app.config"
