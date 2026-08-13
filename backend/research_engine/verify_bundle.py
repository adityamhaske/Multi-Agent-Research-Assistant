"""
Standalone research bundle verifier (docs/12 M12).

No AI. No network. No app installed. Reads a `.bundle.json`, runs every integrity
check, prints a human-readable report, and exits 0 (pass) or 1 (fail).

    python -m research_engine.verify_bundle path/to/bundle.json
    python -m research_engine.verify_bundle path/to/bundle.json --format json

The only import from the engine is the bundle schema (Pydantic models). Everything
else is stdlib. A third party on a bare machine with Python + pydantic can run this.

Checks:
  1. Schema validity
  2. Bundle integrity (bundle_hash)
  3. Report integrity (report_hash)
  4. Evidence integrity (per-snippet content_hash)
  5. Citation resolution (every [n] in the report body points at a source)
  6. Claim–evidence linkage (every cited source has evidence)
  7. Approval chain integrity (approved entry links to this report)
  8. Trace status (informational, not a failure)
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

from research_engine.bundle import (
    BundleManifest,
    compute_bundle_hash,
    content_hash,
)

# Minimal citation regex — duplicated from evals.metrics to keep this module
# dependency-free from the eval harness. Same pattern, same semantics.
_CITE_RE = re.compile(r"\[(\d+(?:\s*,\s*\d+)*)\]")
_SOURCES_HEADING_RE = re.compile(
    r"^#{1,6}\s*(sources|references|citations|bibliography)\b", re.I
)


# ── Result types ──────────────────────────────────────────────────────────────────


@dataclass
class CheckResult:
    name: str
    passed: bool
    detail: str = ""


@dataclass
class VerifyResult:
    passed: bool
    checks: list[CheckResult] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


# ── Individual checks ─────────────────────────────────────────────────────────────


def _check_bundle_integrity(bundle: BundleManifest) -> CheckResult:
    expected = compute_bundle_hash(bundle)
    if bundle.bundle_hash == expected:
        return CheckResult("bundle_integrity", True)
    return CheckResult(
        "bundle_integrity",
        False,
        f"bundle_hash mismatch: recorded {bundle.bundle_hash[:16]}… "
        f"but computed {expected[:16]}… — the bundle was modified after assembly",
    )


def _check_report_integrity(bundle: BundleManifest) -> CheckResult:
    expected = content_hash(bundle.report)
    if bundle.report_hash == expected:
        return CheckResult("report_integrity", True)
    return CheckResult(
        "report_integrity",
        False,
        f"report_hash mismatch: recorded {bundle.report_hash[:16]}… "
        f"but computed {expected[:16]}… — the report text was modified",
    )


def _check_evidence_integrity(bundle: BundleManifest) -> CheckResult:
    bad: list[str] = []
    for i, e in enumerate(bundle.evidence):
        expected = content_hash(e.snippet)
        if e.content_hash != expected:
            bad.append(f"  snippet {i} from {e.source_url}: hash mismatch")
    if not bad:
        return CheckResult("evidence_integrity", True)
    return CheckResult(
        "evidence_integrity",
        False,
        f"{len(bad)} snippet(s) tampered:\n" + "\n".join(bad),
    )


def _body_before_sources(text: str) -> str:
    for i, line in enumerate(text.splitlines()):
        if _SOURCES_HEADING_RE.match(line.strip()):
            return "\n".join(text.splitlines()[:i])
    return text


def _check_citation_resolution(bundle: BundleManifest) -> CheckResult:
    body = _body_before_sources(bundle.report)
    valid_indices = {s.get("index") for s in bundle.sources if isinstance(s.get("index"), int)}
    cited: list[int] = []
    for m in _CITE_RE.finditer(body):
        cited.extend(int(p.strip()) for p in m.group(1).split(","))
    unresolved = sorted({n for n in cited if n not in valid_indices})
    if not unresolved:
        return CheckResult("citation_resolution", True)
    return CheckResult(
        "citation_resolution",
        False,
        f"Unresolved citation markers: {unresolved} — no matching source entry",
    )


def _check_claim_evidence_linkage(bundle: BundleManifest) -> CheckResult:
    source_indices = {s.get("index") for s in bundle.sources if isinstance(s.get("index"), int)}
    urls_by_index: dict[int, str] = {}
    for s in bundle.sources:
        idx = s.get("index")
        if isinstance(idx, int):
            urls_by_index[idx] = s.get("url", "")

    evidence_urls = {e.source_url for e in bundle.evidence}
    gaps: list[str] = []
    for claim in bundle.claims:
        for idx in claim.citation_indices:
            if idx not in source_indices:
                gaps.append(f'  claim cites [{idx}] which has no source entry: "{claim.sentence[:60]}…"')
            elif urls_by_index.get(idx, "") not in evidence_urls:
                gaps.append(
                    f'  claim cites [{idx}] ({urls_by_index.get(idx, "?")}) '
                    f"which has no evidence snippet"
                )
    if not gaps:
        return CheckResult("claim_evidence_linkage", True)
    # Deduplicate — multiple claims citing the same gapped source.
    unique = sorted(set(gaps))
    return CheckResult(
        "claim_evidence_linkage",
        False,
        f"{len(unique)} linkage gap(s):\n" + "\n".join(unique),
    )


def _check_approval_chain(bundle: BundleManifest) -> CheckResult:
    if not bundle.approval_chain:
        return CheckResult(
            "approval_chain",
            False,
            "No approval records — this report was never human-reviewed",
        )

    approved_entries = [a for a in bundle.approval_chain if a.action == "approved"]
    if not approved_entries:
        return CheckResult(
            "approval_chain",
            False,
            "No 'approved' entry in the chain — the report was never approved",
        )

    empty_hashes = [a for a in bundle.approval_chain if not a.draft_hash]
    if empty_hashes:
        return CheckResult(
            "approval_chain",
            False,
            f"{len(empty_hashes)} approval record(s) have an empty draft_hash",
        )

    # The load-bearing check: at least one approved entry's draft_hash matches the
    # report_hash, proving the approval applies to THIS report.
    linked = any(a.draft_hash == bundle.report_hash for a in approved_entries)
    if not linked:
        return CheckResult(
            "approval_chain",
            False,
            "No 'approved' entry's draft_hash matches report_hash — "
            "the approval record does not apply to this report",
        )

    return CheckResult("approval_chain", True)


# ── Top-level verify ──────────────────────────────────────────────────────────────


def verify(bundle: BundleManifest) -> VerifyResult:
    """Run all checks. Returns a VerifyResult with per-check detail."""
    checks = [
        CheckResult("schema_validity", True),  # we already parsed it
        _check_bundle_integrity(bundle),
        _check_report_integrity(bundle),
        _check_evidence_integrity(bundle),
        _check_citation_resolution(bundle),
        _check_claim_evidence_linkage(bundle),
        _check_approval_chain(bundle),
    ]

    notes: list[str] = []
    if not bundle.trace_available:
        notes.append(
            "Trace unavailable: this bundle was produced by a host "
            "without durable event logging."
        )
    elif not bundle.trace:
        notes.append("Trace is empty (no agent events recorded for this session).")

    passed = all(c.passed for c in checks)
    return VerifyResult(passed=passed, checks=checks, notes=notes)


def verify_file(path: str | Path) -> VerifyResult:
    """Load a .bundle.json and verify it. Schema parse failure is a check failure."""
    p = Path(path)
    try:
        data = json.loads(p.read_text("utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        return VerifyResult(
            passed=False,
            checks=[CheckResult("schema_validity", False, f"Cannot read bundle: {e}")],
        )

    try:
        bundle = BundleManifest.model_validate(data)
    except Exception as e:  # noqa: BLE001
        return VerifyResult(
            passed=False,
            checks=[CheckResult("schema_validity", False, f"Schema validation failed: {e}")],
        )

    if bundle.bundle_version != 1:
        return VerifyResult(
            passed=False,
            checks=[
                CheckResult(
                    "schema_validity",
                    False,
                    f"Unsupported bundle_version {bundle.bundle_version} (this verifier supports version 1)",
                )
            ],
        )

    return verify(bundle)


# ── Human-readable output ─────────────────────────────────────────────────────────


def format_text(result: VerifyResult) -> str:
    lines: list[str] = []
    for c in result.checks:
        mark = "✓" if c.passed else "✗"
        lines.append(f"  {mark} {c.name}")
        if c.detail:
            for d in c.detail.splitlines():
                lines.append(f"    {d}")
    for note in result.notes:
        lines.append(f"  ℹ {note}")
    verdict = "PASS" if result.passed else "FAIL"
    lines.insert(0, f"Bundle verification: {verdict}")
    return "\n".join(lines)


def format_json(result: VerifyResult) -> str:
    return json.dumps(
        {
            "passed": result.passed,
            "checks": [
                {"name": c.name, "passed": c.passed, "detail": c.detail or None}
                for c in result.checks
            ],
            "notes": result.notes,
        },
        indent=2,
    )


# ── CLI entry point ───────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print("Usage: python -m research_engine.verify_bundle <path.bundle.json> [--format json]")
        return 0

    path = args[0]
    fmt = "json" if "--format" in args and "json" in args else "text"

    result = verify_file(path)
    output = format_json(result) if fmt == "json" else format_text(result)
    print(output)
    return 0 if result.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
