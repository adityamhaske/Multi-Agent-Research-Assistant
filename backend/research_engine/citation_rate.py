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

The citation pattern and the sources-heading boundary are **not defined here** — they come
from `research_engine.claims`, which is also what the graph's fidelity pass and the eval
judge use. Two copies of "where does the body end" is how the published number and the
displayed number come to disagree about the same report.
"""

from __future__ import annotations

from research_engine.claims import body_before_sources, extract_citations

__all__ = ["body_before_sources", "cited_indices", "resolution_rate"]


def cited_indices(text: str) -> list[int]:
    """Every cited index in the body, in order, duplicates kept.

    A thin alias for `claims.extract_citations`, kept because callers and docs refer to
    this name and because "which indices does this report cite" reads better here than in
    a module about claims.
    """
    return extract_citations(text)


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
