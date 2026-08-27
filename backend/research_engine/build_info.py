"""
What this build is, and which commit it came from.

A desktop user with an installed `.dmg` and a maintainer reading a bug report need the same
thing: the exact revision that produced the artifact in front of them. Nothing in this
product recorded it — there was no git SHA anywhere, and five hand-maintained version
constants, two of which had already drifted for a whole release line.

**Absent means `"unknown"`, never a guess.** `scripts/stamp_build.py` writes `_build.py`
at build time and it is git-ignored, so a source checkout legitimately has none. Reporting
the working tree's HEAD instead would be a plausible answer that is wrong precisely when it
matters — a bundle built from a dirty tree, or copied between machines. This repository's
rule is that a measurement it could not take must say so; a version string is a
measurement.

Lives in `research_engine/` rather than `app/` because the engine is what the desktop
bundle actually contains, and this has to be readable from inside it with no configuration.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

UNKNOWN = "unknown"


@dataclass(frozen=True)
class BuildInfo:
    """The five facts a build can state about itself."""

    version: str
    git_sha: str
    #: True when the working tree had uncommitted changes at build time. The one honest
    #: answer to "which commit is this?" for a local build — a SHA alone would claim the
    #: artifact matches that commit when it does not.
    dirty: bool
    #: A hash of the canonical API surface. Two builds with the same value serve the same
    #: contract, whatever their versions say.
    contract_version: str
    built_at: str

    def as_dict(self) -> dict:
        return asdict(self)


def build_info() -> BuildInfo:
    """This build's identity, or an honest `unknown` when it was never stamped."""
    try:
        from research_engine import _build  # type: ignore[attr-defined]
    except ImportError:
        return BuildInfo(
            version=UNKNOWN,
            git_sha=UNKNOWN,
            # Not `False`: "we did not look" is not "the tree was clean". A build with no
            # stamp cannot claim either.
            dirty=True,
            contract_version=UNKNOWN,
            built_at=UNKNOWN,
        )
    return BuildInfo(
        version=getattr(_build, "VERSION", UNKNOWN),
        git_sha=getattr(_build, "GIT_SHA", UNKNOWN),
        dirty=bool(getattr(_build, "DIRTY", True)),
        contract_version=getattr(_build, "CONTRACT_VERSION", UNKNOWN),
        built_at=getattr(_build, "BUILT_AT", UNKNOWN),
    )
