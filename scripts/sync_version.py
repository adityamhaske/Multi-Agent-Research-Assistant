#!/usr/bin/env python3
"""
One version constant; everything else derives from it.

`VERSION` at the repository root is the only place a human edits. Four files repeat it,
each for a toolchain that needs a literal it can read without running Python: the API's
`/health` payload, the Tauri bundle, the Rust crate, and the public releases page.

They drifted before. `app/main.py` records it: the OpenAPI version and the `/health`
version "were written out separately and drifted — both still said `1.0.0` through the
whole 1.0.x line, so `/health` reported a version the deployment had not been running for
two releases." That is a measurement about the running system being wrong, which this
repository treats as a P0 class rather than a cosmetic one.

    python scripts/sync_version.py            # report drift, exit 1 if any
    python scripts/sync_version.py --write     # rewrite the derived files

CI runs the first form. `--write` is for cutting a release.

**The README download badge is deliberately absent from this list.** It points at
`docs/getting-started/23-desktop-app.md` rather than a versioned asset, so it carries no
version to drift. `AGENTS.md` still instructs bumping "both the badge label and the href";
that rule predates the change and no longer describes the file.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class Derived:
    """One file that repeats the version, and how to find it there."""

    def __init__(self, path: str, pattern: str, template: str, note: str) -> None:
        self.path = ROOT / path
        # MULTILINE, because two of these anchor at the start of a line.
        self.pattern = re.compile(pattern, re.MULTILINE)
        self.template = template
        self.note = note

    def current(self) -> str | None:
        if not self.path.exists():
            return None
        found = self.pattern.search(self.path.read_text(encoding="utf-8"))
        return found.group(1) if found else None

    def write(self, version: str) -> None:
        text = self.path.read_text(encoding="utf-8")
        self.path.write_text(self.pattern.sub(self.template.format(v=version), text, count=1))


DERIVED = [
    Derived(
        "backend/app/main.py",
        r'^APP_VERSION = "([^"]+)"',
        'APP_VERSION = "{v}"',
        "the version /health and the OpenAPI document report",
    ),
    Derived(
        "desktop/tauri.conf.json",
        r'"version": "([^"]+)"',
        '"version": "{v}"',
        "the desktop bundle's version, which names the installer files",
    ),
    Derived(
        "desktop/Cargo.toml",
        r'^version = "([^"]+)"',
        'version = "{v}"',
        "the Rust crate",
    ),
    Derived(
        "frontend/lib/releases.ts",
        r'version: "v([^"]+)"',
        'version: "v{v}"',
        "the newest entry on the public releases page; the download button reads it",
    ),
]


def canonical() -> str:
    return (ROOT / "VERSION").read_text(encoding="utf-8").strip()


def drift() -> list[str]:
    version = canonical()
    out = []
    for derived in DERIVED:
        current = derived.current()
        if current is None:
            out.append(f"{derived.path.relative_to(ROOT)}: no version found — {derived.note}")
        elif current != version:
            out.append(
                f"{derived.path.relative_to(ROOT)}: {current} != {version} — {derived.note}"
            )
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="rewrite the derived files")
    args = parser.parse_args()

    if args.write:
        for derived in DERIVED:
            derived.write(canonical())
        print(f"wrote {canonical()} to {len(DERIVED)} files")
        return 0

    problems = drift()
    if problems:
        print(f"VERSION says {canonical()}, but:", file=sys.stderr)
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        print("\nRun `python scripts/sync_version.py --write`.", file=sys.stderr)
        return 1
    print(f"version {canonical()} is consistent across {len(DERIVED)} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
