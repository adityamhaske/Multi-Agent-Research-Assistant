"""
The release audit catches what past releases shipped (RELEASE.md, "Historical incidents").

Each test plants one real incident into the audit's pure evaluators — a checksum file listing
names with a space, a `:vX.Y.Z` pull line, release notes one workflow overwrote, a reviewed
line edited into claiming something new — and asserts it is caught. A release check that has
never been seen to fail is a check nobody knows works; these are its negative controls, and
none of them needs a release, a network or a tag to exist.

The last group holds RELEASE.md and the check registry to each other: a check the document
does not describe is invisible to whoever runs a release by hand, and a documented check the
script does not have is a promise nothing keeps.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))

from release_checks import REGISTRY  # noqa: E402
from release_checks.constants import (  # noqa: E402
    CHECKSUMS,
    FAIL,
    INSTALLERS,
    PASS,
    PYTHON_EXCEPTIONS,
    SERVER_PYTHON_JOBS,
    UNAVAILABLE,
    WARN,
)
from release_checks.core import Check, Ctx, Outcome, Unavailable  # noqa: E402
from release_checks.evaluate import (  # noqa: E402
    alembic_heads,
    asset_problems,
    automated_ids,
    cargo_lock_version,
    changelog_heading,
    checksum_problems,
    entry_completeness,
    image_pythons,
    interpreter_drift,
    manual_ids,
    parse_record,
    parse_releases_ts,
    parse_sha256sums,
    release_body_problems,
    release_list_problems,
    review_references,
    secret_hits,
    setup_python_steps,
    version_references,
)

V = "9.8.7"
MB = 1024 * 1024


def _assets(version: str = V) -> list[dict]:
    sizes = {".dmg": 70, ".msi": 75, ".AppImage": 170, ".deb": 120}
    assets = []
    for template in INSTALLERS.values():
        name = template.format(v=version)
        suffix = next(s for s in sizes if name.endswith(s))
        assets.append(
            {
                "name": name,
                "size": sizes[suffix] * MB,
                "digest": "sha256:" + format(len(name), "064x"),
            }
        )
    assets.append({"name": CHECKSUMS, "size": 415, "digest": "sha256:" + "0" * 64})
    return assets


def _sums_for(assets: list[dict]) -> str:
    return "".join(
        f"{a['digest'].removeprefix('sha256:')}  {a['name']}\n"
        for a in assets
        if a["name"] != CHECKSUMS
    )


# ─── Published artifacts ────────────────────────────────────────────────────────────────


def test_the_published_asset_set_passes():
    assert asset_problems(_assets(), V) == []


def test_a_missing_installer_an_extra_file_and_a_space_are_each_caught():
    assets = [a for a in _assets() if not a["name"].endswith(".msi")]
    assets.append({"name": f"Research Assistant_{V}_x64-setup.exe", "size": 80 * MB})
    problems = asset_problems(assets, V)
    assert any("missing" in p and p.endswith(".msi") for p in problems)
    assert any("unexpected asset" in p and "setup.exe" in p for p in problems)
    assert any("contains a space" in p for p in problems)


def test_a_bundle_with_no_engine_in_it_is_caught_by_its_size():
    # The documented failure: a ~5 MB installer, the shell without the engine.
    assets = _assets()
    next(a for a in assets if a["name"].endswith(".dmg"))["size"] = 5 * MB
    assert any("too small to contain the engine" in p for p in asset_problems(assets, V))


def test_checksums_that_match_what_github_stored_pass():
    assets = _assets()
    assert checksum_problems(parse_sha256sums(_sums_for(assets)), assets, V) == []


def test_a_checksum_file_listing_the_bundlers_spaced_names_is_caught():
    # v1.0.1: the hashes were right, the names were the pre-upload ones, and
    # `sha256sum -c` answered "no file was verified".
    assets = _assets()
    spaced = _sums_for(assets).replace("Research.Assistant_", "Research Assistant_")
    problems = checksum_problems(parse_sha256sums(spaced), assets, V)
    assert any("does not list" in p for p in problems)
    assert any("not an installer of this release" in p for p in problems)


def test_a_checksum_that_disagrees_with_the_published_file_is_caught():
    assets = _assets()
    sums = parse_sha256sums(_sums_for(assets))
    dmg = next(n for n in sums if n.endswith(".dmg"))
    sums[dmg] = "f" * 64
    assert any(dmg in p and "GitHub stored" in p for p in checksum_problems(sums, assets, V))


GOOD_BODY = f"""
Multi-arch container images (linux/amd64, linux/arm64) pushed to GHCR:
- `ghcr.io/o/r-api:{V}`
- `ghcr.io/o/r-worker:{V}`
- `ghcr.io/o/r-frontend:{V}`
## Desktop bundles for v{V}
run `xattr -dr com.apple.quarantine "/Applications/Research Assistant.app"` in Terminal once
sha256sum -c SHA256SUMS --ignore-missing
"""


def test_release_notes_with_both_sections_pass():
    assert release_body_problems(GOOD_BODY, V) == []


def test_release_notes_one_workflow_overwrote_are_caught():
    # v2.0.0: both workflows assigned the body; the slower one erased the images.
    desktop_only = GOOD_BODY.split("## Desktop bundles")[1]
    problems = release_body_problems("## Desktop bundles" + desktop_only, V)
    assert any("image section is missing" in p for p in problems)


def test_a_pull_line_naming_the_git_tag_instead_of_the_image_tag_is_caught():
    # Every release until the fix told people to pull `:v2.0.1`, which never existed.
    body = GOOD_BODY.replace(f"-api:{V}", f"-api:v{V}")
    problems = release_body_problems(body, V)
    assert any(f":v{V}" in p for p in problems)
    assert any("api:" in p and "pull line" in p for p in problems)


def test_release_notes_with_a_different_macos_command_are_caught():
    body = GOOD_BODY.replace("xattr -dr", "xattr -d")  # `-r` is what reaches the engine
    assert any("first-launch command" in p for p in release_body_problems(body, V))


# ─── Version references ─────────────────────────────────────────────────────────────────


def test_versions_are_found_and_addresses_and_svg_paths_are_not():
    files = {
        "a.md": "Builds from 3.0.1 are signed.\nConnect to 127.0.0.1:8000.",
        "b.tsx": 'path d="M12 9v2m3.31.826 1.1.1" and Research.Assistant_2.0.2_aarch64.dmg',
    }
    refs = version_references(files)
    assert [(r["path"], r["versions"]) for r in refs] == [("a.md", ["3.0.1"]), ("b.tsx", ["2.0.2"])]


def test_an_unreviewed_line_an_edited_line_and_a_future_version_are_each_caught():
    files = {"docs/x.md": "From 3.0.0, bundles are v2.\nNew in 3.0.1.\nComing in 3.1.0."}
    allow = [
        {"path": "docs/x.md", "text": "From 3.0.0, bundles are v2.", "reason": "history"},
        {"path": "docs/x.md", "text": "New in 3.0.0.", "reason": "was true once"},
    ]
    unreviewed, stale, future = review_references(version_references(files), allow, "3.0.1")
    assert [u["text"] for u in unreviewed] == ["New in 3.0.1.", "Coming in 3.1.0."]
    assert [s["text"] for s in stale] == ["New in 3.0.0."]  # the edit invalidated its review
    assert [f["newer"] for f in future] == [["3.1.0"]]


def test_a_third_party_version_is_not_mistaken_for_a_future_release():
    refs = version_references({"README.md": "Built on Next.js 16.3.5."})
    assert review_references(refs, [], "3.0.1")[2] == []


# ─── The server image and CI run one Python (A10.06) ───────────────────────────────────

DOCKERFILE = (
    "# syntax=docker/dockerfile:1\nFROM python:3.14-slim-bookworm AS base\nFROM base AS api\n"
)
WORKFLOW = """\
name: CI
on:
  push:
    branches: [main]
jobs:
  backend:
    steps:
      - uses: actions/checkout@v7
      # uses: actions/setup-python@v7 — a comment, not a step
      - uses: actions/setup-python@v7
        with:
          python-version: "3.14"
          cache: pip
      - name: Tests
        run: pytest
  stamp:
    steps:
      - name: Python
        uses: actions/setup-python@v7
        with:
          python-version: '3.14.2'
"""
REQUIRED = {"ci.yml": ("backend", "stamp")}


def test_steps_are_attributed_to_their_job_and_read_to_x_y():
    assert setup_python_steps(WORKFLOW) == [("backend", "3.14"), ("stamp", "3.14")]
    assert image_pythons(DOCKERFILE) == ["3.14"]


def test_an_image_and_jobs_on_one_python_pass():
    assert interpreter_drift(DOCKERFILE, {"ci.yml": WORKFLOW}, REQUIRED) == []


def test_a_base_image_bump_the_jobs_did_not_follow_is_caught():
    # #173: Dependabot moved the image from 3.11 to 3.14; every job stayed on 3.11.
    behind = WORKFLOW.replace('"3.14"', '"3.11"').replace("'3.14.2'", "'3.11.15'")
    problems = interpreter_drift(DOCKERFILE, {"ci.yml": behind}, REQUIRED)
    assert problems == [
        "ci.yml: job `backend` sets up Python 3.11; the image runs 3.14",
        "ci.yml: job `stamp` sets up Python 3.11; the image runs 3.14",
    ]


def test_a_python_the_check_cannot_read_fails_rather_than_passes():
    # Unreadable is not agreeing: each of these would otherwise be a silent pass.
    from_file = WORKFLOW.replace('python-version: "3.14"', "python-version-file: .python-version")
    matrix = WORKFLOW.replace('"3.14"', "${{ matrix.python }}")
    for text in (from_file, matrix):
        problems = interpreter_drift(DOCKERFILE, {"ci.yml": text}, REQUIRED)
        assert any("job `backend`" in p and "cannot read" in p for p in problems), problems
    for image in ("FROM python:3-slim AS base\n", "ARG V=3.14\nFROM python:${V}-slim\n"):
        problems = interpreter_drift(image, {"ci.yml": WORKFLOW}, REQUIRED)
        assert any("backend/Dockerfile" in p and "cannot be read" in p for p in problems)


def test_a_required_job_that_stops_setting_up_python_is_caught():
    # A job moved into a container, or onto the runner's default Python, has an interpreter
    # this check cannot see — which must not read as one that agrees.
    without = WORKFLOW.split("  stamp:")[0]
    problems = interpreter_drift(DOCKERFILE, {"ci.yml": without}, REQUIRED)
    assert problems == [
        "ci.yml: job `stamp` no longer sets up Python with actions/setup-python, "
        "so its interpreter cannot be compared with the image's"
    ]


def test_an_image_built_on_two_pythons_is_caught():
    two = DOCKERFILE + "FROM python:3.11-slim AS tools\n"
    assert any("more than one Python" in p for p in interpreter_drift(two, {}, {}))


DESKTOP = """\
jobs:
  sidecar:
    steps:
      - uses: actions/setup-python@v7
        with:
          python-version: "3.11"
"""
EXCEPT = {("desktop.yml", "sidecar"): "3.11"}


def test_a_workflow_nobody_listed_is_compared_not_ignored():
    # The desktop engine's 3.11 is only acceptable because it is named; unnamed, it is drift.
    problems = interpreter_drift(DOCKERFILE, {"ci.yml": WORKFLOW, "desktop.yml": DESKTOP}, REQUIRED)
    assert problems == ["desktop.yml: job `sidecar` sets up Python 3.11; the image runs 3.14"]


def test_a_named_exception_is_held_at_exactly_its_version():
    workflows = {"ci.yml": WORKFLOW, "desktop.yml": DESKTOP}
    assert interpreter_drift(DOCKERFILE, workflows, REQUIRED, EXCEPT) == []
    # Moving the excepted job without moving its exception is drift either way: to a third
    # version, or to the image's (which leaves an exception that excepts nothing).
    for moved in ("3.12", "3.14"):
        workflows["desktop.yml"] = DESKTOP.replace('"3.11"', f'"{moved}"')
        problems = interpreter_drift(DOCKERFILE, workflows, REQUIRED, EXCEPT)
        assert problems == [
            f"desktop.yml: job `sidecar` sets up Python {moved}; its named exception is 3.11 "
            "(PYTHON_EXCEPTIONS) — move the exception with it, or remove it once the job "
            "runs the image's Python"
        ]


def test_an_exception_that_no_longer_describes_a_job_fails():
    stale = {("desktop.yml", "sidecar"): "3.11", ("desktop.yml", "gone"): "3.11"}
    workflows = {"ci.yml": WORKFLOW, "desktop.yml": DESKTOP}
    assert interpreter_drift(DOCKERFILE, workflows, REQUIRED, stale) == [
        "desktop.yml: job `gone` is a named Python exception but sets up no Python — "
        "remove the exception"
    ]
    redundant = {("desktop.yml", "sidecar"): "3.14"}
    workflows["desktop.yml"] = DESKTOP.replace('"3.11"', '"3.14"')
    assert interpreter_drift(DOCKERFILE, workflows, REQUIRED, redundant) == [
        "desktop.yml: job `sidecar` is a named Python exception at the image's own 3.14 — "
        "remove the exception"
    ]


def _python_check(root: Path) -> Outcome:
    args = argparse.Namespace(
        root=root,
        version=V,
        stage="ci",
        offline=True,
        download=False,
        docker=False,
        repo="o/r",
        site="https://example.test",
        previous=None,
    )
    a10_06 = next(c for c in REGISTRY if c.id == "A10.06")
    return a10_06.fn(Ctx(args))


def _copy_interpreter_files(dest: Path) -> None:
    workflows = sorted((ROOT / ".github/workflows").glob("*.yml"))
    for rel in ("backend/Dockerfile", *(str(w.relative_to(ROOT)) for w in workflows)):
        (dest / rel).parent.mkdir(parents=True, exist_ok=True)
        (dest / rel).write_text((ROOT / rel).read_text(encoding="utf-8"), encoding="utf-8")


def test_the_repository_runs_one_server_python(tmp_path):
    # The real files, read by the registered check: the evaluator tests above prove the
    # judgement, this proves the check reads the files that hold it.
    _copy_interpreter_files(tmp_path)
    outcome = _python_check(tmp_path)
    assert outcome.status == PASS, outcome.detail


def test_drift_planted_in_the_real_dockerfile_fails_the_real_check(tmp_path):
    # The negative control: the incident replayed on this repository's own files — the
    # image's Python moved and nothing else did.
    _copy_interpreter_files(tmp_path)
    dockerfile = tmp_path / "backend/Dockerfile"
    image = image_pythons(dockerfile.read_text(encoding="utf-8"))[0]
    major, minor = image.split(".")
    bumped = f"{major}.{int(minor) + 1}"
    dockerfile.write_text(
        dockerfile.read_text(encoding="utf-8").replace(f"python:{image}", f"python:{bumped}"),
        encoding="utf-8",
    )
    outcome = _python_check(tmp_path)
    assert outcome.status == FAIL
    for path, jobs in SERVER_PYTHON_JOBS.items():
        for job in jobs:
            assert f"{path}: job `{job}` sets up Python {image}; the image runs {bumped}" in (
                outcome.detail
            )


def test_the_desktop_engine_moved_alone_fails_the_real_check(tmp_path):
    # The named exception is a pin, not a blind spot: the desktop engine's Python changed
    # with nothing else, and the check says which exception it broke.
    _copy_interpreter_files(tmp_path)
    for (path, job), version in PYTHON_EXCEPTIONS.items():
        workflow = tmp_path / path
        text = workflow.read_text(encoding="utf-8")
        assert f'python-version: "{version}"' in text, f"{path} {job} is not at {version}"
        workflow.write_text(
            text.replace(f'python-version: "{version}"', 'python-version: "3.99"'),
            encoding="utf-8",
        )
    outcome = _python_check(tmp_path)
    assert outcome.status == FAIL
    for (path, job), version in PYTHON_EXCEPTIONS.items():
        assert f"{path}: job `{job}` sets up Python 3.99; its named exception is {version}" in (
            outcome.detail
        )


# ─── Repository data ────────────────────────────────────────────────────────────────────

RELEASES_TS = """
export const RELEASES: Release[] = [
  {
    version: "v2.0.0",
    date: "2026-09-01",
    headline: "Newest.",
    improved: [
      "One.",
    ],
    improvedSummary: "One.",
    known: [],
    knownSummary: "",
    unreleased: true,
  },
  {
    version: "v2.1.0",
    date: "2026-08-01",
    headline: "Older, but a higher number.",
    improved: [
      "Two.",
    ],
    improvedSummary: "Two.",
    known: [
      "A gap.",
    ],
    knownSummary: "A gap.",
  },
];
"""


def test_releases_ts_is_parsed_with_the_fields_the_audit_reads():
    entries = parse_releases_ts(RELEASES_TS)
    assert [(e["version"], e["unreleased"], e["improved"], e["known"]) for e in entries] == [
        ("v2.0.0", True, 1, 0),
        ("v2.1.0", False, 1, 1),
    ]


def test_a_releases_list_out_of_order_is_caught():
    problems = release_list_problems(parse_releases_ts(RELEASES_TS))
    assert any("listed after a lower version" in p for p in problems)


def test_an_entry_with_nothing_known_needs_a_person_to_confirm_it():
    failures, warnings = entry_completeness(parse_releases_ts(RELEASES_TS)[0])
    assert failures == []
    assert any("`known` is empty" in w for w in warnings)


def test_the_lock_version_is_read_from_our_crate_not_the_first_package():
    lock = (
        '[[package]]\nname = "adler2"\nversion = "2.0.1"\n\n'
        '[[package]]\nname = "research-desktop"\nversion = "3.0.1"\n'
    )
    assert cargo_lock_version(lock) == "3.0.1"


def test_the_changelog_heading_says_unreleased_or_a_date():
    text = "## v3.0.2 — unreleased\n\n## v3.0.1 — 2026-09-28\n"
    assert changelog_heading(text, "3.0.2") == "unreleased"
    assert changelog_heading(text, "3.0.1") == "2026-09-28"
    assert changelog_heading(text, "3.0.3") is None


def test_a_migration_branch_is_caught_as_two_heads():
    chain = {"0001": None, "0002": "0001", "0003a": "0002", "0003b": "0002"}
    assert alembic_heads(chain) == ["0003a", "0003b"]
    assert alembic_heads({"0001": None, "0002": "0001"}) == ["0002"]


def test_a_secret_is_caught_and_a_placeholder_that_says_so_is_not():
    real_shaped = "OPENAI_API_KEY=sk-" + "Ab3" * 15
    assert secret_hits(real_shaped) == ["OpenAI-style key"]
    assert secret_hits("key = sk-example-custom-endpoint-key-0001") == []


def test_the_record_parser_reads_statuses_and_the_sign_off():
    record = (
        "| M7.03 | PASS | valid on disk |\n| M8.01 | NOT RUN | no Windows machine |\n"
        "- [x] **Release approved**\n"
    )
    statuses, approved = parse_record(record)
    assert statuses == {"M7.03": "PASS", "M8.01": "NOT RUN"}
    assert approved
    assert parse_record(record.replace("[x]", "[ ]"))[1] is False


# ─── The runner never counts an unmeasured check as a pass ─────────────────────────────


def _run(fn, *, stop: bool = True, network: bool = False, offline: bool = False) -> dict:
    import release_audit

    check = Check("A99.01", 99, "test", ("ci",), network, stop, "test", fn)
    ctx = argparse.Namespace(offline=offline)
    return release_audit.run_one(ctx, check)


def _raise(exc):
    def fn(_ctx):
        raise exc

    return fn


def test_a_check_that_could_not_measure_is_unavailable_not_passed():
    assert _run(_raise(Unavailable("no token")))["status"] == UNAVAILABLE
    assert _run(lambda _c: Outcome("PASS", ""), network=True, offline=True)["status"] == UNAVAILABLE


def test_a_crashed_check_is_a_failure_not_a_silence():
    result = _run(_raise(KeyError("assets")))
    assert result["status"] == FAIL
    assert "raised KeyError" in result["detail"]


def test_a_failure_in_an_advisory_check_is_a_warning():
    assert _run(lambda _c: Outcome(FAIL, "historical"), stop=False)["status"] == WARN


# ─── RELEASE.md and the registry describe the same checks ──────────────────────────────

RELEASE_MD = (ROOT / "RELEASE.md").read_text(encoding="utf-8")


def test_every_automated_check_is_documented_in_release_md():
    registered = {c.id for c in REGISTRY}
    documented = set(automated_ids(RELEASE_MD))
    assert registered - documented == set(), "checks RELEASE.md does not describe"
    assert documented - registered == set(), "RELEASE.md describes checks that do not exist"


def test_check_ids_are_unique():
    ids = [c.id for c in REGISTRY]
    assert len(ids) == len(set(ids))


def test_the_record_template_starts_with_a_row_for_every_manual_check():
    template = (ROOT / "release-audit" / "TEMPLATE.md").read_text(encoding="utf-8")
    rows, _approved = parse_record(template)
    assert manual_ids(RELEASE_MD), "RELEASE.md defines no manual checks"
    assert set(manual_ids(RELEASE_MD)) - set(rows) == set()


@pytest.mark.parametrize("check", REGISTRY, ids=lambda c: c.id)
def test_every_check_names_its_phase_consistently(check):
    assert check.id.startswith(f"A{check.phase}.")
