"""
Pure evaluation: text and API payloads in, verdicts out. No network, no git, no files.

Every judgement a check makes about a published artifact lives here rather than inside the
check, so `backend/tests/workflow/test_release_audit.py` can plant each historical failure —
a checksum with a space in its name, a `:vX.Y.Z` pull line, a stale reviewed reference — and
watch it be caught, without a release existing.
"""

from __future__ import annotations

import re

from .constants import CHECKSUMS, IMAGES, INSTALLERS, MACOS_UNQUARANTINE, SIZE_FLOOR_MB

# A version string, not an IP address (127.0.0.1 has four parts) and not the fourth part of
# one. The lookbehind allows letters so `Assistant_3.0.1_` and `V3.0.0` are still found.
VERSION_RX = re.compile(r"(?<![\d.])v?(\d+)\.(\d+)\.(\d+)(?!\.?\d)")
# SVG path data (`d="M12 9v2…"`, `icon: "M…"`) is full of `3.31.826`-shaped numbers.
SVG_PATH_RX = re.compile(r"""\b(?:d|icon)\s*[:=]\s*["'][Mm][^"']*["']""")


def parse_version(text: str) -> tuple[int, int, int] | None:
    m = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)(?:-[0-9A-Za-z.-]+)?", text.strip())
    return (int(m[1]), int(m[2]), int(m[3])) if m else None


def parse_releases_ts(text: str) -> list[dict]:
    """The entries of `frontend/lib/releases.ts`, in file order, with the fields we audit."""
    body = text.split("export const RELEASES", 1)[-1]
    entries = []
    for chunk in re.split(r"\n  \{\n", body)[1:]:
        version = re.search(r'^\s*version: "([^"]+)"', chunk, re.M)
        if not version:
            continue
        date = re.search(r'^\s*date: "([^"]+)"', chunk, re.M)
        entries.append(
            {
                "version": version[1],
                "date": date[1] if date else None,
                "unreleased": bool(re.search(r"^\s*unreleased: true", chunk, re.M)),
                "headline": bool(re.search(r"^\s*headline:\s*\S", chunk, re.M)),
                "improved": _array_len(chunk, "improved"),
                "known": _array_len(chunk, "known"),
                "improvedSummary": bool(re.search(r'improvedSummary:\s*\n?\s*"[^"]+"', chunk)),
                "knownSummary": bool(re.search(r'knownSummary:\s*\n?\s*"[^"]+"', chunk)),
            }
        )
    return entries


def _array_len(chunk: str, name: str) -> int:
    m = re.search(rf"^\s*{name}: \[(.*?)^\s*\],", chunk, re.S | re.M)
    return len(re.findall(r'^\s*"', m[1], re.M)) if m else 0


def release_list_problems(entries: list[dict]) -> list[str]:
    problems = []
    seen: set[str] = set()
    previous: tuple | None = None
    previous_date = None
    for e in entries:
        v = parse_version(e["version"])
        if not e["version"].startswith("v") or v is None:
            problems.append(f"{e['version']!r} is not a v-prefixed version (it must match the tag)")
            continue
        if e["version"] in seen:
            problems.append(f"{e['version']} appears twice")
        seen.add(e["version"])
        if previous is not None and v >= previous:
            problems.append(f"{e['version']} is listed after a lower version — newest first")
        previous = v
        if not e["date"] or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", e["date"]):
            problems.append(f"{e['version']} has no ISO date")
        elif previous_date and e["date"] > previous_date:
            problems.append(f"{e['version']} is dated after the release listed above it")
        else:
            previous_date = e["date"]
    return problems


def entry_completeness(entry: dict) -> tuple[list[str], list[str]]:
    """(failures, warnings) for one entry: `known` may be empty only when nothing is known."""
    failures, warnings = [], []
    if not entry["headline"]:
        failures.append("no headline")
    if entry["improved"] == 0:
        failures.append("no `improved` items")
    if not entry["improvedSummary"]:
        failures.append("no `improvedSummary`")
    if entry["known"] == 0:
        warnings.append("`known` is empty — confirm in the record that nothing is known")
    elif not entry["knownSummary"]:
        failures.append("`known` has items but no `knownSummary`")
    return failures, warnings


def cargo_lock_version(text: str, package: str = "research-desktop") -> str | None:
    m = re.search(rf'name = "{re.escape(package)}"\nversion = "([^"]+)"', text)
    return m[1] if m else None


def changelog_heading(text: str, version: str) -> str | None:
    """What follows `## vX.Y.Z — ` in the changelog: a date, `unreleased`, or None."""
    m = re.search(rf"^## v{re.escape(version)} — (.+)$", text, re.M)
    return m[1].strip() if m else None


def changelog_section(text: str, version: str) -> str:
    m = re.search(rf"^## v{re.escape(version)} — .*?(?=^## v|\Z)", text, re.M | re.S)
    return m[0] if m else ""


def normalize_line(line: str) -> str:
    return " ".join(line.split())


def version_references(files: dict[str, str]) -> list[dict]:
    """Every line in `files` that names a version, with the versions it names."""
    refs = []
    for path, text in sorted(files.items()):
        for number, line in enumerate(text.splitlines(), 1):
            scrubbed = SVG_PATH_RX.sub("", line)
            found = [f"{m[1]}.{m[2]}.{m[3]}" for m in VERSION_RX.finditer(scrubbed)]
            if found:
                refs.append(
                    {"path": path, "line": number, "text": normalize_line(line), "versions": found}
                )
    return refs


def review_references(
    refs: list[dict], allowlist: list[dict], current: str
) -> tuple[list[dict], list[dict], list[dict]]:
    """(unreviewed, stale allowlist entries, references to versions newer than `current`).

    Keyed on the exact line text, not the line number, so an unrelated edit above a reviewed
    line leaves it reviewed, while an edit *to* it asks for a fresh review.
    """
    reviewed = {(a["path"], normalize_line(a["text"])) for a in allowlist}
    present = {(r["path"], r["text"]) for r in refs}
    unreviewed = [r for r in refs if (r["path"], r["text"]) not in reviewed]
    stale = [a for a in allowlist if (a["path"], normalize_line(a["text"])) not in present]
    cur = parse_version(current)
    future = []
    for r in refs:
        newer = [v for v in r["versions"] if (pv := parse_version(v)) and cur and pv > cur]
        # Only this product's version family: a third-party `16.3.5` is not a claim about us.
        newer = [v for v in newer if parse_version(v)[0] <= cur[0] + 1]
        if newer:
            future.append({**r, "newer": newer})
    return unreviewed, stale, future


def parse_sha256sums(text: str) -> dict[str, str]:
    sums = {}
    for line in text.splitlines():
        m = re.fullmatch(r"([0-9a-fA-F]{64})\s+\*?(.+)", line.strip())
        if m:
            sums[m[2].strip()] = m[1].lower()
    return sums


def asset_problems(assets: list[dict], version: str) -> list[str]:
    """The published asset list against exactly what desktop.yml should have produced."""
    expected = {t.format(v=version) for t in INSTALLERS.values()} | {CHECKSUMS}
    names = {a["name"] for a in assets}
    problems = [f"missing: {n}" for n in sorted(expected - names)]
    problems += [f"unexpected asset: {n}" for n in sorted(names - expected)]
    problems += [f"asset name contains a space: {n!r}" for n in sorted(names) if " " in n]
    for a in assets:
        suffix = next((s for s in SIZE_FLOOR_MB if a["name"].endswith(s)), None)
        if suffix and a["size"] < SIZE_FLOOR_MB[suffix] * 1024 * 1024:
            problems.append(
                f"{a['name']} is {a['size'] / 1048576:.1f} MB, under the "
                f"{SIZE_FLOOR_MB[suffix]} MB floor — too small to contain the engine"
            )
    return problems


def checksum_problems(sums: dict[str, str], assets: list[dict], version: str) -> list[str]:
    """SHA256SUMS names exactly the installers, and each hash is what GitHub stored."""
    installers = {t.format(v=version) for t in INSTALLERS.values()}
    problems = [f"SHA256SUMS does not list {n}" for n in sorted(installers - set(sums))]
    problems += [
        f"SHA256SUMS lists {n}, which is not an installer of this release"
        for n in sorted(set(sums) - installers)
    ]
    for a in assets:
        digest = (a.get("digest") or "").removeprefix("sha256:").lower()
        if a["name"] in sums and digest and sums[a["name"]] != digest:
            problems.append(
                f"{a['name']}: SHA256SUMS says {sums[a['name']][:12]}…, "
                f"GitHub stored {digest[:12]}…"
            )
    return problems


def release_body_problems(body: str, version: str) -> list[str]:
    problems = []
    if f"Desktop bundles for v{version}" not in body:
        problems.append("the desktop workflow's appended section is missing — was it overwritten?")
    if "Multi-arch container images" not in body:
        problems.append("the release workflow's image section is missing — was it overwritten?")
    if re.search(rf":v{re.escape(version)}\b", body):
        problems.append(f"an image is referenced as `:v{version}`; the pushed tag is `:{version}`")
    for image in IMAGES:
        if not re.search(rf"-{image}:{re.escape(version)}\b", body):
            problems.append(f"no `{image}:{version}` pull line")
    if MACOS_UNQUARANTINE not in body:
        problems.append("the macOS first-launch command is missing or differs from the site's")
    if "SHA256SUMS" not in body:
        problems.append("no instruction to verify downloads against SHA256SUMS")
    return problems


def markdown_links(text: str) -> list[str]:
    # Code spans and fenced blocks are not links, however they look.
    text = re.sub(r"```.*?```", "", text, flags=re.S)
    text = re.sub(r"`[^`\n]*`", "", text)
    return re.findall(r"\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)", text)


def alembic_heads(revisions: dict[str, str | None]) -> list[str]:
    """Revisions nothing descends from. A healthy chain has exactly one."""
    parents = {p for p in revisions.values() if p}
    return sorted(r for r in revisions if r not in parents)


SECRET_PATTERNS = (
    ("AWS access key", r"\bAKIA[0-9A-Z]{16}\b"),
    ("GitHub token", r"\bgh[pousr]_[A-Za-z0-9]{36,}\b"),
    ("OpenAI-style key", r"\bsk-(?:proj-|ant-)?[A-Za-z0-9_-]{32,}\b"),
    ("Google API key", r"\bAIza[0-9A-Za-z_-]{35}\b"),
    ("Tavily key", r"\btvly-[A-Za-z0-9]{20,}\b"),
    ("private key", r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |)PRIVATE KEY-----"),
    ("Slack token", r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
)


# A fixture key announces itself; a real one never contains these words.
PLACEHOLDER_RX = re.compile(r"example|fake|dummy|placeholder|test|redacted|x{8,}", re.I)


def secret_hits(text: str) -> list[str]:
    return [
        label
        for label, rx in SECRET_PATTERNS
        if any(not PLACEHOLDER_RX.search(m[0]) for m in re.finditer(rx, text))
    ]


def parse_record(text: str) -> tuple[dict[str, str], bool]:
    """(manual-check id → status, approved?) from a release record."""
    statuses = {}
    for m in re.finditer(
        r"^\|\s*(M\d+\.\d+)\s*\|\s*(PASS|FAIL|N/A|NOT RUN|ACCEPTED|PENDING)\s*\|", text, re.M
    ):
        statuses[m[1]] = m[2]
    approved = bool(re.search(r"^- \[x\] \*\*Release approved\*\*", text, re.M | re.I))
    return statuses, approved


def manual_ids(release_md: str) -> list[str]:
    return sorted(set(re.findall(r"\*\*(M\d+\.\d+)\*\*", release_md)), key=id_key)


def automated_ids(release_md: str) -> list[str]:
    return sorted(set(re.findall(r"\b(A\d+\.\d+)\b", release_md)), key=id_key)


def id_key(cid: str) -> tuple[int, int]:
    a, b = cid[1:].split(".")
    return int(a), int(b)
