"""The provider SDKs and their HTTP stack install at exactly the versions constraints.txt names.

These packages decide what a provider call retries, raises, pools and verifies, and they
arrived as transitive floats: openai 2.x → 3.x reached the worker image with no diff in this
repository, narrowed which transport errors the SDK retries, and turned a latent
cross-event-loop bug into failed runs. The same float hid it locally — a developer venv
still on openai 2.x retried the error away, so the suite passed there against a defect the
image shipped. Hence the last test: a suite run on other versions says nothing about what
ships.
"""

from __future__ import annotations

import importlib.metadata as md
from pathlib import Path

import pytest
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

BACKEND = Path(__file__).resolve().parents[2]
CONSTRAINTS = BACKEND / "constraints.txt"
REQUIREMENTS = BACKEND / "requirements.txt"
DOCKERFILE = BACKEND / "Dockerfile"

#: Removing one of these from constraints.txt returns it to floating, so the removal has to
#: be argued here as well.
GOVERNED = {
    "openai",
    "anthropic",
    "google-genai",
    "langchain-core",
    "langchain-openai",
    "langchain-anthropic",
    "langchain-google-genai",
    "httpx",
    "httpcore",
    "httpx2",
    "httpcore2",
    "truststore",
    "anyio",
    "h11",
}


def _entries(path: Path) -> list[str]:
    return [
        line.split("#", 1)[0].strip()
        for line in path.read_text().splitlines()
        if line.split("#", 1)[0].strip()
    ]


def _pins() -> dict[str, str]:
    pins: dict[str, str] = {}
    for entry in _entries(CONSTRAINTS):
        req = Requirement(entry)
        specs = list(req.specifier)
        assert len(specs) == 1 and specs[0].operator == "==" and req.marker is None, (
            f"constraints.txt: {entry!r} — every entry is one exact, unconditional pin; "
            "a range here floats again"
        )
        pins[canonicalize_name(req.name)] = specs[0].version
    return pins


def test_every_install_that_reads_requirements_also_reads_the_constraints():
    """One home: the Dockerfile, both CI jobs, pip-audit and the desktop sidecar build all
    run `pip install -r requirements.txt`, and none of them passes a `-c` flag of its own."""
    assert "-c constraints.txt" in _entries(REQUIREMENTS)


def test_the_governed_packages_are_pinned_exactly():
    missing = sorted(GOVERNED - set(_pins()))
    assert missing == [], f"no exact pin in constraints.txt for: {missing}"


def test_each_pin_meets_the_floor_requirements_asks_for():
    pins = _pins()
    unmet = [
        f"{req.name}: requirements.txt asks {req.specifier}, constraints.txt pins "
        f"{pins[canonicalize_name(req.name)]}"
        for req in (Requirement(e) for e in _entries(REQUIREMENTS) if not e.startswith("-"))
        if canonicalize_name(req.name) in pins
        and pins[canonicalize_name(req.name)] not in req.specifier
    ]
    assert unmet == []


def test_the_image_build_copies_the_constraints_beside_the_requirements():
    """The builder stage copies only what the install needs, for layer caching — and a `-c`
    naming a file that was not copied fails the image build, not this suite."""
    copies = [line for line in DOCKERFILE.read_text().splitlines() if line.startswith("COPY")]
    assert any("requirements.txt" in line and "constraints.txt" in line for line in copies), copies


@pytest.mark.parametrize("name", sorted(GOVERNED))
def test_this_environment_runs_the_pinned_version(name):
    pinned = _pins()[canonicalize_name(name)]
    installed = md.version(name)
    assert installed == pinned, (
        f"{name} {installed} is installed but constraints.txt pins {pinned}. Reinstall "
        "(pip install -r requirements.txt) — the suite is only evidence for the versions "
        "that ship."
    )
