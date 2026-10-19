"""
Pure evaluation: text and API payloads in, verdicts out. No network, no git, no files.

Every judgement a check makes about a published artifact lives here rather than inside the
check, so `backend/tests/workflow/test_release_audit.py` can plant each historical failure —
a checksum with a space in its name, a `:vX.Y.Z` pull line, a stale reviewed reference — and
watch it be caught, without a release existing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

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
                "improvedSummary": bool(
                    re.search(r'improvedSummary:\s*\n?\s*"[^"]+"', chunk)
                ),
                "knownSummary": bool(
                    re.search(r'knownSummary:\s*\n?\s*"[^"]+"', chunk)
                ),
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
            problems.append(
                f"{e['version']!r} is not a v-prefixed version (it must match the tag)"
            )
            continue
        if e["version"] in seen:
            problems.append(f"{e['version']} appears twice")
        seen.add(e["version"])
        if previous is not None and v >= previous:
            problems.append(
                f"{e['version']} is listed after a lower version — newest first"
            )
        previous = v
        if not e["date"] or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", e["date"]):
            problems.append(f"{e['version']} has no ISO date")
        elif previous_date and e["date"] > previous_date:
            problems.append(
                f"{e['version']} is dated after the release listed above it"
            )
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
        warnings.append(
            "`known` is empty — confirm in the record that nothing is known"
        )
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
                    {
                        "path": path,
                        "line": number,
                        "text": normalize_line(line),
                        "versions": found,
                    }
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
    stale = [
        a for a in allowlist if (a["path"], normalize_line(a["text"])) not in present
    ]
    cur = parse_version(current)
    future = []
    for r in refs:
        newer = [
            v for v in r["versions"] if (pv := parse_version(v)) and cur and pv > cur
        ]
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
    problems += [
        f"asset name contains a space: {n!r}" for n in sorted(names) if " " in n
    ]
    for a in assets:
        suffix = next((s for s in SIZE_FLOOR_MB if a["name"].endswith(s)), None)
        if suffix and a["size"] < SIZE_FLOOR_MB[suffix] * 1024 * 1024:
            problems.append(
                f"{a['name']} is {a['size'] / 1048576:.1f} MB, under the "
                f"{SIZE_FLOOR_MB[suffix]} MB floor — too small to contain the engine"
            )
    return problems


def checksum_problems(
    sums: dict[str, str], assets: list[dict], version: str
) -> list[str]:
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
        problems.append(
            "the desktop workflow's appended section is missing — was it overwritten?"
        )
    if "Multi-arch container images" not in body:
        problems.append(
            "the release workflow's image section is missing — was it overwritten?"
        )
    if re.search(rf":v{re.escape(version)}\b", body):
        problems.append(
            f"an image is referenced as `:v{version}`; the pushed tag is `:{version}`"
        )
    for image in IMAGES:
        if not re.search(rf"-{image}:{re.escape(version)}\b", body):
            problems.append(f"no `{image}:{version}` pull line")
    if MACOS_UNQUARANTINE not in body:
        problems.append(
            "the macOS first-launch command is missing or differs from the site's"
        )
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


@dataclass(frozen=True)
class Runtime:
    """An interpreter an image ships, which every workflow job and every stated floor must
    name too (A10.06 for the backend's Python, A10.07 for the frontend's Node).

    One description per runtime keeps the two checks one rule. They differ only in what they
    read — which Dockerfile, which `setup-*` action, how a version is spelled — and #172 is
    the reason: the frontend image drifted from CI's Node exactly as #173 had the backend's
    Python, after a check existed for only one of them.
    """

    name: str
    dockerfile: str
    from_rx: str  # captures the version from a `FROM` line
    from_form: str  # how that `FROM` is written, for a message
    action: str  # the `uses:` that installs the runtime in a job
    version_rx: str  # captures the version from that step's `with:` block
    version_form: str  # how a readable version is written, for a message
    exceptions: str  # the constant naming jobs allowed to differ


PYTHON = Runtime(
    name="Python",
    dockerfile="backend/Dockerfile",
    from_rx=r"^\s*FROM\s+(?:--\S+\s+)*python:(\d+\.\d+)\b",
    from_form="python:X.Y",
    action="actions/setup-python",
    # `python-version: "3.14"`, quoted or not, a patch allowed; anything else is unreadable.
    version_rx=r"""\s*python-version:\s*["']?(\d+\.\d+)(?:\.\d+)?["']?\s*(?:#.*)?$""",
    version_form='python-version: "X.Y"',
    exceptions="PYTHON_EXCEPTIONS",
)
NODE = Runtime(
    name="Node",
    dockerfile="frontend/Dockerfile",
    # `node:26-bookworm-slim`: a major and nothing else. `node:lts`, or a build argument,
    # names no version this can compare.
    from_rx=r"^\s*FROM\s+(?:--\S+\s+)*node:(\d+)(?![\d.])",
    from_form="node:N",
    action="actions/setup-node",
    # `node-version: "26"`, `26.x` or `26.1.0` all mean 26; `lts/*` and a version file do not
    # say which, so they are unreadable rather than agreeing.
    version_rx=r"""\s*node-version:\s*["']?(\d+)(?:\.(?:\d+|x))*["']?\s*(?:#.*)?$""",
    version_form='node-version: "N"',
    exceptions="NODE_EXCEPTIONS",
)


def image_versions(dockerfile: str, runtime: Runtime) -> list[str]:
    """The version of every stage built on `runtime`'s image. A stage on a tag that names
    none (`python:3-slim`, `node:lts`) or on a build argument contributes nothing, and an
    empty list is what lets the caller fail on it."""
    return re.findall(runtime.from_rx, dockerfile, re.M | re.I)


def setup_steps(workflow: str, runtime: Runtime) -> list[tuple[str, str | None]]:
    """(job, version) for every step installing `runtime` in a workflow, in file order.

    The version is None when the step does not state one literally — a version file, a
    matrix expression, an alias like `lts/*` — because a value this cannot read is not a
    value that agrees. Line-based rather than YAML: the `ci` stage runs with no dependencies
    installed.
    """
    lines = workflow.splitlines()
    uses = re.compile(rf"\s*(?:-\s+)?uses:\s*{re.escape(runtime.action)}@")
    version_rx = re.compile(runtime.version_rx)
    steps: list[tuple[str, str | None]] = []
    job, in_jobs = "?", False
    for i, line in enumerate(lines):
        if re.match(r"\S", line):
            in_jobs = bool(re.match(r"jobs:\s*$", line))
        elif in_jobs and (m := re.match(r" {2}([\w-]+):\s*(?:#.*)?$", line)):
            job = m[1]
        if not uses.match(line):
            continue
        start = next((j for j in range(i, -1, -1) if re.match(r"\s*- ", lines[j])), i)
        indent = len(lines[start]) - len(lines[start].lstrip())
        end = next(
            (
                j
                for j in range(start + 1, len(lines))
                if lines[j].strip() and len(lines[j]) - len(lines[j].lstrip()) <= indent
            ),
            len(lines),
        )
        version = None
        for body in lines[start:end]:
            if m := version_rx.match(body):
                version = m[1]
        steps.append((job, version))
    return steps


def runtime_drift(
    dockerfile: str,
    workflows: dict[str, str],
    required: dict[str, tuple[str, ...]],
    exceptions: dict[tuple[str, str], str] | None = None,
    *,
    runtime: Runtime,
) -> list[str]:
    """Every way an image and the workflows can disagree about `runtime`, or fail to say.
    `workflows` is every workflow, not a chosen few: a job nobody listed is compared with the
    image, and only a named exception may differ — by exactly its named version."""
    exceptions = exceptions or {}
    rt = runtime
    images = sorted(set(image_versions(dockerfile, rt)))
    if not images:
        return [
            f"{rt.dockerfile}: no stage is `FROM {rt.from_form}`, so the image's {rt.name} "
            "cannot be read"
        ]
    if len(images) > 1:
        return [
            f"{rt.dockerfile} builds on more than one {rt.name} ({', '.join(images)})"
        ]
    image, problems = images[0], []
    seen: set[tuple[str, str]] = set()
    for path, text in workflows.items():
        steps = setup_steps(text, rt)
        seen |= {(path, j) for j, _v in steps}
        problems += [
            f"{path}: job `{job}` no longer sets up {rt.name} with {rt.action}, "
            "so its interpreter cannot be compared with the image's"
            for job in required.get(path, ())
            if (path, job) not in seen
        ]
        for job, version in steps:
            named = exceptions.get((path, job))
            if version is None:
                problems.append(
                    f"{path}: job `{job}` sets up a {rt.name} this check cannot read — "
                    f"state it as {rt.version_form}"
                )
            elif named is not None and version != named:
                problems.append(
                    f"{path}: job `{job}` sets up {rt.name} {version}; its named exception is "
                    f"{named} ({rt.exceptions}) — move the exception with it, or remove it "
                    f"once the job runs the image's {rt.name}"
                )
            elif named is None and version != image:
                problems.append(
                    f"{path}: job `{job}` sets up {rt.name} {version}; the image runs {image}"
                )
    for (path, job), named in exceptions.items():
        if (path, job) not in seen:
            problems.append(
                f"{path}: job `{job}` is a named {rt.name} exception but sets up no "
                f"{rt.name} — remove the exception"
            )
        elif named == image:
            problems.append(
                f"{path}: job `{job}` is a named {rt.name} exception at the image's own "
                f"{image} — remove the exception"
            )
    return problems


def image_pythons(dockerfile: str) -> list[str]:
    return image_versions(dockerfile, PYTHON)


def setup_python_steps(workflow: str) -> list[tuple[str, str | None]]:
    return setup_steps(workflow, PYTHON)


def interpreter_drift(
    dockerfile: str,
    workflows: dict[str, str],
    required: dict[str, tuple[str, ...]],
    exceptions: dict[tuple[str, str], str] | None = None,
) -> list[str]:
    return runtime_drift(dockerfile, workflows, required, exceptions, runtime=PYTHON)


def floor_drift(
    image: str,
    files: dict[str, str | None],
    required: dict[str, tuple[str, ...]],
    anywhere: tuple[str, ...] = (),
    *,
    runtime: Runtime = PYTHON,
) -> list[str]:
    """Every stated `runtime` floor that is not the image's version, or can no longer be read.

    `files` maps a path to its text, or None when it is gone. Each pattern captures the
    version's parts — (major, minor) for Python, the major for Node — which are joined with
    dots. A pattern in `required` must match its file at least once, so a reworded line
    fails instead of dropping out of the check; one in `anywhere` is compared wherever it
    matches, so a floor stated in a new document is checked rather than missed.
    """
    name, problems = runtime.name, []
    for path, text in files.items():
        own = required.get(path, ())
        if text is None:
            if own:
                problems.append(
                    f"{path} is missing, so the {name} floor it states cannot be read"
                )
            continue
        for rx in dict.fromkeys((*own, *anywhere)):
            stated = sorted({".".join(m.groups()) for m in re.finditer(rx, text, re.M)})
            if not stated and rx in own:
                problems.append(
                    f"{path}: no line states the {name} floor in the form this check reads "
                    f"(`{rx}`)"
                )
            problems += [
                f"{path}: states a {name} {v} floor; CI runs only the image's {image}"
                for v in stated
                if v != image
            ]
    return problems


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
        r"^\|\s*(M\d+\.\d+)\s*\|\s*(PASS|FAIL|N/A|NOT RUN|ACCEPTED|PENDING)\s*\|",
        text,
        re.M,
    ):
        statuses[m[1]] = m[2]
    approved = bool(re.search(r"^- \[x\] \*\*Release approved\*\*", text, re.M | re.I))
    return statuses, approved


def merged_prs(first_parent_subjects: str) -> list[str]:
    """PR numbers merged to `main`, from `git log --first-parent --format=%s` output.

    Both merge styles land here: a merge commit says `Merge pull request #N`, and a squash
    merge ends its subject with GitHub's ` (#N)`. Reading only the first let every
    squash-merged PR between 3.0.1 and 3.0.2 skip the scope check unseen.
    """
    prs = re.findall(r"^Merge pull request #(\d+)", first_parent_subjects, re.M)
    prs += re.findall(r"\(#(\d+)\)$", first_parent_subjects, re.M)
    return sorted(set(prs), key=int)


def records_eval_waiver(record: str) -> bool:
    """Whether a release record carries a written `Eval waiver:` line.

    The template's own line, `Eval waiver: <!-- … -->`, is an instruction, not a waiver: a
    record copied and never edited must not turn a missing evaluation into a warning.
    """
    return bool(re.search(r"^Eval waiver:[ \t]*(?!<!--)\S", record, re.M))


def manual_ids(release_md: str) -> list[str]:
    return sorted(set(re.findall(r"\*\*(M\d+\.\d+)\*\*", release_md)), key=id_key)


def automated_ids(release_md: str) -> list[str]:
    return sorted(set(re.findall(r"\b(A\d+\.\d+)\b", release_md)), key=id_key)


def id_key(cid: str) -> tuple[int, int]:
    a, b = cid[1:].split(".")
    return int(a), int(b)
