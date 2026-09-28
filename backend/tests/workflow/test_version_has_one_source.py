"""
One version constant, and a build that can say which commit made it (Phase 9).

Two problems, and the second is the one users feel.

**Five hand-maintained constants.** `app/main.py` records what that cost: the OpenAPI
version and the `/health` version "were written out separately and drifted — both still
said `1.0.0` through the whole 1.0.x line, so `/health` reported a version the deployment
had not been running for two releases." A running system reporting the wrong version is a
false measurement, which this repository treats as a P0 class rather than a cosmetic one.
`VERSION` is now the only place a human edits, and `scripts/sync_version.py` is what makes
that true rather than intended.

**No revision anywhere.** Before this there was no git SHA in the product at all — nothing
connected an installed `.dmg` to a commit. `scripts/stamp_build.py` writes one at build
time and `GET /api/v1/version` serves it, on both hosts at the same path.

The rule that matters most here is the one about absence: **an unstamped build reports
`unknown`, never a guess.** Filling it in from the working tree would produce a plausible
answer that is wrong exactly when it matters — a bundle built from a dirty tree, or copied
between machines. A version string is a measurement, and a measurement that could not be
taken has to say so.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from research_engine.build_info import UNKNOWN, BuildInfo, build_info

ROOT = Path(__file__).resolve().parents[3]


def _sync(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "sync_version.py"), *args],
        capture_output=True,
        text=True,
        check=False,
    )


# ── One source ────────────────────────────────────────────────────────────────────


def test_the_repository_has_a_canonical_version():
    assert (ROOT / "VERSION").read_text(encoding="utf-8").strip()


def test_every_derived_constant_agrees_with_it():
    """What CI runs. Red here means a release was cut without `--write`."""
    result = _sync()
    assert result.returncode == 0, result.stdout + result.stderr


def test_the_checker_actually_detects_drift(tmp_path, monkeypatch):
    """A consistency check that cannot fail is not a check.

    Asserted by pointing the script at a copy with one constant edited, rather than by
    editing the real tree — `AGENTS.md` is explicit that a planted-failure sweep left
    active produces entirely fictional findings.
    """
    import shutil

    sandbox = tmp_path / "repo"
    (sandbox / "backend" / "app").mkdir(parents=True)
    (sandbox / "desktop").mkdir(parents=True)
    (sandbox / "frontend" / "lib").mkdir(parents=True)
    (sandbox / "scripts").mkdir(parents=True)
    shutil.copy(ROOT / "scripts" / "sync_version.py", sandbox / "scripts" / "sync_version.py")
    (sandbox / "VERSION").write_text("2.0.1\n")
    (sandbox / "backend" / "app" / "main.py").write_text('APP_VERSION = "9.9.9"\n')
    (sandbox / "desktop" / "tauri.conf.json").write_text('{"version": "2.0.1"}\n')
    (sandbox / "desktop" / "Cargo.toml").write_text('version = "2.0.1"\n')
    (sandbox / "frontend" / "lib" / "releases.ts").write_text('  version: "v2.0.1",\n')

    result = subprocess.run(
        [sys.executable, str(sandbox / "scripts" / "sync_version.py")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    assert "9.9.9" in result.stderr


# ── The tag the release workflows build from ─────────────────────────────────────


def _version() -> str:
    return (ROOT / "VERSION").read_text(encoding="utf-8").strip()


def test_a_tag_naming_version_may_be_released():
    """What `desktop.yml` and `release.yml` run before building anything a tag publishes."""
    result = _sync("--tag", f"v{_version()}")
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize(
    "tag",
    [
        "v9.9.9",  # the bump never merged: installers would ship labelled as the old version
        "{v}",  # no `v`: not the shape either workflow triggers on
        "v{short}",  # a prefix of the version is not the version
        "v{v}-rc1",  # a pre-release must say so in VERSION, or its artifacts claim the final
    ],
)
def test_a_tag_that_does_not_name_version_is_refused(tag):
    version = _version()
    tag = tag.format(v=version, short=version.rsplit(".", 1)[0])
    result = _sync("--tag", tag)
    assert result.returncode == 1
    assert "does not name VERSION" in result.stderr


def test_a_matching_tag_on_a_drifted_tree_is_refused(tmp_path):
    """The tag agreeing with `VERSION` is not enough when a derived file does not."""
    import shutil

    sandbox = tmp_path / "repo"
    (sandbox / "backend" / "app").mkdir(parents=True)
    (sandbox / "desktop").mkdir(parents=True)
    (sandbox / "frontend" / "lib").mkdir(parents=True)
    (sandbox / "scripts").mkdir(parents=True)
    shutil.copy(ROOT / "scripts" / "sync_version.py", sandbox / "scripts" / "sync_version.py")
    (sandbox / "VERSION").write_text("3.0.0\n")
    (sandbox / "backend" / "app" / "main.py").write_text('APP_VERSION = "3.0.0"\n')
    (sandbox / "desktop" / "tauri.conf.json").write_text('{"version": "2.1.0"}\n')
    (sandbox / "desktop" / "Cargo.toml").write_text('version = "3.0.0"\n')
    (sandbox / "frontend" / "lib" / "releases.ts").write_text('  version: "v3.0.0",\n')

    result = subprocess.run(
        [sys.executable, str(sandbox / "scripts" / "sync_version.py"), "--tag", "v3.0.0"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    assert "tauri.conf.json: 2.1.0 != 3.0.0" in result.stderr


def test_checking_a_tag_never_writes():
    """`--tag` runs in the release workflows; a guard that could rewrite files is not one."""
    result = _sync("--tag", f"v{_version()}", "--write")
    assert result.returncode == 2
    assert "not allowed with" in result.stderr


def test_no_module_hard_codes_a_version_the_script_does_not_know_about():
    """A sixth constant would drift silently, which is how the first five did."""
    import re

    pattern = re.compile(r'"\d+\.\d+\.\d+"')
    offenders = []
    for path in [
        ROOT / "backend" / "app" / "main.py",
        ROOT / "desktop" / "tauri.conf.json",
        ROOT / "desktop" / "Cargo.toml",
    ]:
        found = pattern.findall(path.read_text(encoding="utf-8"))
        canonical = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
        wrong = [v for v in found if v.strip('"') != canonical]
        if wrong:
            offenders.append(f"{path.name}: {wrong}")
    assert not offenders, f"version-shaped literals that are not the canonical version: {offenders}"


# ── Honest absence ────────────────────────────────────────────────────────────────


def test_an_unstamped_build_reports_unknown_rather_than_guessing(monkeypatch):
    """The rule this module exists for. A source checkout has no stamp.

    `sys.modules[...] = None` is how Python spells "this import fails" — patching
    `__import__` does not work here, because a stamp written earlier in the session is
    already cached and never re-imported. The first version of this test passed against a
    stamped tree while asserting the unstamped behaviour, which is the shape of test this
    whole effort keeps finding.

    **Both patches are needed, and the second was missing.** `build_info()` runs
    `from research_engine import _build`, which resolves by `getattr` on the *package*
    first and only falls back to `sys.modules`. So once anything has imported `_build` —
    any earlier test that calls `build_info()`, and there are several now — the attribute
    is bound on `research_engine` and the `sys.modules` patch never gets consulted. This
    test then read a real stamp while asserting the unstamped path: exactly the failure
    its own docstring describes, one level further down.

    It passed anyway for a reason worth stating: `_build.py` is git-ignored, so CI has no
    stamp and the import fails on its own there. The isolation was doing nothing and
    nothing could tell, until a local run with a stamped tree ordered the tests this way.
    """
    import research_engine

    monkeypatch.setitem(sys.modules, "research_engine._build", None)
    monkeypatch.delattr(research_engine, "_build", raising=False)

    info = build_info()
    assert info.git_sha == UNKNOWN
    assert info.version == UNKNOWN
    assert info.contract_version == UNKNOWN


def test_an_unstamped_build_does_not_claim_a_clean_tree():
    """`dirty=False` would be a claim nobody checked. "We did not look" is not "clean"."""
    import research_engine.build_info as module

    unstamped = BuildInfo(
        version=UNKNOWN, git_sha=UNKNOWN, dirty=True, contract_version=UNKNOWN, built_at=UNKNOWN
    )
    assert unstamped.dirty is True
    assert module.UNKNOWN == "unknown"


def test_the_payload_carries_every_field_a_reader_needs():
    payload = build_info().as_dict()
    assert set(payload) == {"version", "git_sha", "dirty", "contract_version", "built_at"}


# ── Both hosts, one path ──────────────────────────────────────────────────────────


@pytest.mark.parametrize("host", ["server", "desktop"])
def test_both_hosts_serve_version_at_the_same_path(host):
    """A client that had to know which host it was talking to in order to ask "what are
    you?" would be exactly the `isDesktop` branch this work exists to remove."""
    import tempfile

    if host == "server":
        from app.main import app
    else:
        from desktop.sidecar import create_sidecar_app

        app = create_sidecar_app(data_dir=tempfile.mkdtemp(), token="version", fake=True)

    assert "/api/v1/version" in app.openapi()["paths"]


async def test_the_desktop_keeps_version_behind_its_token():
    """One token, no exceptions — a second rule is a second thing to get wrong."""
    import tempfile

    import httpx

    from desktop.sidecar import create_sidecar_app

    app = create_sidecar_app(data_dir=tempfile.mkdtemp(), token="version", fake=True)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://d.invalid") as client:
        assert (await client.get("/api/v1/version")).status_code == 401
        authorised = await client.get(
            "/api/v1/version", headers={"Authorization": "Bearer version"}
        )
    assert authorised.status_code == 200
    assert set(authorised.json()) == {
        "version",
        "git_sha",
        "dirty",
        "contract_version",
        "built_at",
    }
