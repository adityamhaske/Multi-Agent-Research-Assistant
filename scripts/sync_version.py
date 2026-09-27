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

    python scripts/sync_version.py                 # report drift, exit 1 if any
    python scripts/sync_version.py --write          # rewrite the derived files
    python scripts/sync_version.py --tag v3.0.0     # refuse a tag that is not VERSION

CI runs the first form. `--write` is for cutting a release. `--tag` is the release
workflows' guard, run before either of them builds anything a tag would publish.

**A tag that disagrees with `VERSION` ships mislabelled, and nothing else notices.** The
installers are named from `tauri.conf.json` and the images from the tag, so tagging before
the version bump merged would publish `2.1.0` installers under a `v3.0.0` release — every
build step green, every artifact wrong. `--tag` compares exactly (`v` + `VERSION`, no
prefix matching, so `v3.0` is not `v3.0.0`) and runs the drift check too: a tag that
matches a `VERSION` its derived files do not is the same mislabelling one file later.

**`desktop/Cargo.lock` carries the version too, and this script must not write it.**
The lock repeats `version = "..."` once per package — 451 times today — so the
single-substitution rule every entry below relies on would rewrite the first package in
the file (`adler2`) rather than ours. Cargo owns that file: `cargo update -p research-desktop`
rewrites the one line and leaves the dependency graph alone. It is easy to forget, and was
— the lock sat at 2.0.1 through the whole 2.0.2 line, one release behind the manifest it
is supposed to pin.

**The README download badge is deliberately absent from this list.** It points at the
published download page rather than a versioned asset, so it carries no version to drift.
`AGENTS.md` agrees and defers here for the reasoning, so this paragraph is the one home for
it — do not restate it there.
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


def tag_mismatch(tag: str) -> str | None:
    expected = f"v{canonical()}"
    if tag == expected:
        return None
    return (
        f"tag {tag!r} does not name VERSION {canonical()} (expected {expected!r}) — every "
        f"artifact built from this commit would be labelled {canonical()}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--write", action="store_true", help="rewrite the derived files")
    mode.add_argument("--tag", help="fail unless this tag is exactly v + VERSION")
    args = parser.parse_args()

    if args.tag is not None:
        problems = [p for p in [tag_mismatch(args.tag), *drift()] if p]
        if problems:
            print(f"refusing to release {args.tag}:", file=sys.stderr)
            for problem in problems:
                print(f"  {problem}", file=sys.stderr)
            return 1
        print(f"tag {args.tag} names version {canonical()}, consistent across {len(DERIVED)} files")
        return 0

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
