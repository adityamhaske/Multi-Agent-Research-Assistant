"""
Pure report-quality metrics (docs/08 §5). No I/O, no models — unit-tested so the
numbers in a committed eval run are trustworthy and diffable over time.

The LLM-judged *citation support rate* (does a cited snippet actually support the
claim) lives in the harness because it needs a model; everything here is structural
and deterministic.
"""

from __future__ import annotations

import re

CITE_RE = re.compile(r"\[(\d+)\]")
HEADING_RE = re.compile(r"^#{1,6}\s")
SOURCES_HEADING_RE = re.compile(r"^#{1,6}\s*(sources|references|citations|bibliography)\b", re.I)
_LIST_MARKER_RE = re.compile(r"^(?:[-*+]\s+|\d+[.)]\s+)")


def body_before_sources(text: str) -> str:
    """The report body up to (excluding) the sources/references section. Metrics count
    in-text citations, not the numbered entries in the reference list."""
    lines = (text or "").splitlines()
    for i, raw in enumerate(lines):
        if SOURCES_HEADING_RE.match(raw.strip()):
            return "\n".join(lines[:i])
    return text or ""


def extract_citations(text: str) -> list[int]:
    """Every [n] citation marker, in order (duplicates kept)."""
    return [int(m.group(1)) for m in CITE_RE.finditer(text or "")]


def source_indices(sources: list[dict]) -> set[int]:
    out: set[int] = set()
    for s in sources or []:
        idx = s.get("index") if isinstance(s, dict) else None
        if isinstance(idx, int):
            out.add(idx)
    return out


def citation_stats(text: str, sources: list[dict]) -> dict:
    """Totals + resolution: how many in-text [n] markers point at a real source."""
    cites = extract_citations(body_before_sources(text))
    valid = source_indices(sources)
    total = len(cites)
    unresolved = sum(1 for n in cites if n not in valid)
    return {
        "total_citations": total,
        "unresolved_citations": unresolved,
        # None (not 1.0) when there are no citations — an uncited report isn't "perfect".
        "resolution_rate": None if total == 0 else round((total - unresolved) / total, 4),
    }


def claim_lines(text: str) -> list[str]:
    """Content lines that assert something — paragraph/bullet text before the sources
    section, excluding headings and trivially short lines. Used to find uncited claims."""
    out: list[str] = []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        if SOURCES_HEADING_RE.match(line):
            break  # sources/references section is references, not claims
        if HEADING_RE.match(line):
            continue
        content = _LIST_MARKER_RE.sub("", line)
        if len(content) < 15 or not re.search(r"[A-Za-z]", content):
            continue
        out.append(content)
    return out


def uncited_claim_count(text: str) -> int:
    """Assertive lines carrying no [n] citation — a proxy for unsupported claims."""
    return sum(1 for c in claim_lines(text) if not CITE_RE.search(c))


def report_metrics(text: str, sources: list[dict]) -> dict:
    """Structural quality for one report."""
    stats = citation_stats(text, sources)
    return {
        "word_count": len((text or "").split()),
        "source_count": len(sources or []),
        **stats,
        "uncited_claim_count": uncited_claim_count(text),
    }
