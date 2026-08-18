"""
Pure report-quality metrics (docs/08 §5). No I/O, no models — unit-tested so the
numbers in a committed eval run are trustworthy and diffable over time.

The LLM-judged *citation support rate* (does a cited snippet actually support the
claim) lives in the harness because it needs a model; everything here is structural
and deterministic.

**Claim and citation extraction is not defined here.** It lives in
`research_engine.claims`, and this module re-exports it. The engine's citation-fidelity
pass acts on the same sentences this module judges, so a second definition here would let
the pipeline and its own measurement rule on different claims. The re-exports below are
the *same objects*, not copies — `tests/test_claim_extraction_parity.py` asserts that by
identity, so a future copy-paste back into this file fails the suite.
"""

from __future__ import annotations

import re

from research_engine.claims import (
    CITE_RE,
    CONFLICTS_HEADING_RE,
    HEADING_RE,
    LIMITATIONS_HEADING_RE,
    SOURCES_HEADING_RE,
    body_before_sources,
    claim_lines,
    extract_citations,
    split_sentences,
)

# Re-exported for callers that import them from here (the harness, the benchmark, and
# any contributor following the docs). Named explicitly so a linter cannot decide they
# are unused imports and delete the module's public surface.
__all__ = [
    "CITE_RE",
    "CONFLICTS_HEADING_RE",
    "HEADING_RE",
    "LIMITATIONS_HEADING_RE",
    "METRICS_VERSION",
    "SOURCES_HEADING_RE",
    "body_before_sources",
    "citation_stats",
    "claim_lines",
    "contradictions_surfaced",
    "extract_citations",
    "report_metrics",
    "source_indices",
    "split_sentences",
    "uncited_claim_count",
]


def source_indices(sources: list[dict]) -> set[int]:
    out: set[int] = set()
    for s in sources or []:
        idx = s.get("index") if isinstance(s, dict) else None
        if isinstance(idx, int):
            out.add(idx)
    return out


def citation_stats(text: str, sources: list[dict]) -> dict:
    """Totals + resolution: how many in-text [n] markers point at a real source.

    `resolution_rate` is delegated to `research_engine.citation_rate`, which is also what
    the app writes onto a session. Two implementations of one measurement is how the
    number a benchmark publishes and the number the UI shows drift apart — and the app
    cannot import this module (see `graph.py`'s inlined uncited-count), so the shared
    copy has to live in the engine rather than here.
    """
    from research_engine.citation_rate import resolution_rate

    cites = extract_citations(body_before_sources(text))
    valid = source_indices(sources)
    return {
        "total_citations": len(cites),
        "unresolved_citations": sum(1 for n in cites if n not in valid),
        # None (not 1.0) when there are no citations — an uncited report isn't "perfect".
        "resolution_rate": resolution_rate(text, sources),
    }


def uncited_claim_count(text: str) -> int:
    """Assertive lines carrying no [n] citation — a proxy for unsupported claims."""
    return sum(1 for c in claim_lines(text) if not CITE_RE.search(c))


def contradictions_surfaced(text: str) -> int:
    """How many conflicting-claim pairs the report surfaces (docs/12 M11).

    Counts numbered items under the engine-rendered "Conflicting evidence" heading, up
    to the next heading. Purely structural: it measures what the run SURFACED, which is
    the honest baseline metric — whether the conflicts were real is what the curated
    fixture eval (evals/contradiction_eval.py) measures against a model.
    """
    lines = (text or "").splitlines()
    inside = False
    count = 0
    for raw in lines:
        line = raw.strip()
        if HEADING_RE.match(line):
            inside = bool(CONFLICTS_HEADING_RE.match(line))
            continue
        if inside and re.match(r"^\d+[.)]\s", line):
            count += 1
    return count


# Bumped whenever a metric's *definition* changes, so two committed runs are never
# silently compared across incompatible definitions. Recorded in every results file.
#
#   1 — original: citations matched `[n]` only; claims were raw lines.
#   2 — grouped markers `[1, 3]` counted as separate citations; claims split on sentences
#       (docs/12 M5, defect D1). Both enlarge the denominator, so a v2 number is NOT
#       comparable to a v1 number.
#   3 — Limitations sentences excluded from claims (D5): they are hedging, not factual
#       claims. A v3 support rate is not comparable to v2.
#   4 — Conflicting-evidence block excluded from claims (docs/12 M11): it quotes both
#       sides of a conflict and is engine-rendered, not authored claims. Adds the
#       contradictions_surfaced metric.
METRICS_VERSION = 4


def report_metrics(text: str, sources: list[dict]) -> dict:
    """Structural quality for one report."""
    stats = citation_stats(text, sources)
    return {
        "word_count": len((text or "").split()),
        "source_count": len(sources or []),
        **stats,
        "uncited_claim_count": uncited_claim_count(text),
        "contradictions_surfaced": contradictions_surfaced(text),
    }
