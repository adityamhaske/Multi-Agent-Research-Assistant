"""
How much of a report's citation apparatus actually resolves (docs/07 §2, Phase 7).

The product's central claim is that every `[n]` is falsifiable. This turns that into one
number per report so it is scannable across a list, not only checkable inside one.

**The return type is `float | None` and the `None` is the point.** `None` means *not
measured*: the report made no citable claims at all. `0.0` means every marker it did make
points at nothing. Those are opposite findings, and rendering the first as the second is
the failure AGENTS.md opens the repo with — an unmeasured value printed as a zero.

Lives here rather than in `evals/` because `app/` must not import the eval harness (see
`graph.py`'s inlined uncited-count and the note explaining why). `evals.metrics.
citation_stats` now delegates here, so the number a benchmark publishes and the number
the UI displays cannot drift apart.
"""

from __future__ import annotations

import re

#: `[1]`, `[1, 3]`, `[1][3]`. A grouped marker contributes each of its numbers, so it is
#: counted and resolution-checked identically to separate markers.
_CITE_RE = re.compile(r"\[(\d+(?:\s*,\s*\d+)*)\]")
# Must stay identical to `evals.metrics.SOURCES_HEADING_RE`, which this replaces as the
# shared implementation — a heading that ends the body here and not there would make the
# published number and the displayed number disagree on the same report.
_SOURCES_HEADING_RE = re.compile(r"^#{1,6}\s*(sources|references|citations|bibliography)\b", re.I)


def body_before_sources(text: str) -> str:
    """The report body up to (excluding) its sources section.

    The numbered entries in a reference list are not claims. Counting them would push
    every report's rate toward 1.0 regardless of what the prose actually cited.
    """
    lines = (text or "").splitlines()
    for i, raw in enumerate(lines):
        if _SOURCES_HEADING_RE.match(raw.strip()):
            return "\n".join(lines[:i])
    return text or ""


def cited_indices(text: str) -> list[int]:
    """Every cited index in the body, in order, duplicates kept."""
    out: list[int] = []
    for m in _CITE_RE.finditer(text or ""):
        out.extend(int(part) for part in m.group(1).split(","))
    return out


def resolution_rate(report: str, sources: list[dict] | None) -> float | None:
    """Fraction of in-text markers that point at a real source, or `None` if unmeasured.

    `None` when the body carries no markers at all. Not 0.0: see the module docstring.
    """
    cites = cited_indices(body_before_sources(report))
    if not cites:
        return None
    valid = {
        s.get("index")
        for s in (sources or [])
        if isinstance(s, dict) and isinstance(s.get("index"), int)
    }
    resolved = sum(1 for n in cites if n in valid)
    return round(resolved / len(cites), 4)
