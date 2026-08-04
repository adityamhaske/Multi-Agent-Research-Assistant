"""
Pure report-quality metrics (docs/08 §5). No I/O, no models — unit-tested so the
numbers in a committed eval run are trustworthy and diffable over time.

The LLM-judged *citation support rate* (does a cited snippet actually support the
claim) lives in the harness because it needs a model; everything here is structural
and deterministic.
"""

from __future__ import annotations

import re

# Matches a citation marker and captures its numbers, including *grouped* markers.
#
# The synthesizer routinely writes `[1, 3]` or `[1, 2, 3, 4, 6]` when a sentence draws on
# several sources. A single-number-only pattern silently treated those as prose: they
# counted as neither cited nor unresolved, so a report could be 42% invisible to this
# module while still reporting a perfect resolution rate (measured on a real run —
# docs/12 M5). `extract_citations` flattens a group into its individual indices, so
# `[1, 3]` counts as two citations, exactly as `[1][3]` would.
CITE_RE = re.compile(r"\[(\d+(?:\s*,\s*\d+)*)\]")
HEADING_RE = re.compile(r"^#{1,6}\s")
SOURCES_HEADING_RE = re.compile(r"^#{1,6}\s*(sources|references|citations|bibliography)\b", re.I)
_LIST_MARKER_RE = re.compile(r"^(?:[-*+]\s+|\d+[.)]\s+)")
# Sentence boundary: terminator + whitespace, not preceded by a common abbreviation or a
# bare initial. Deliberately conservative — over-splitting a claim is worse than
# under-splitting it, because each fragment then gets judged against too little evidence.
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z(\[])")
_ABBREV_TAIL_RE = re.compile(r"\b(?:e\.g|i\.e|vs|etc|Dr|Mr|Ms|Inc|Ltd|Fig|No|approx|cf)\.$", re.I)


def body_before_sources(text: str) -> str:
    """The report body up to (excluding) the sources/references section. Metrics count
    in-text citations, not the numbered entries in the reference list."""
    lines = (text or "").splitlines()
    for i, raw in enumerate(lines):
        if SOURCES_HEADING_RE.match(raw.strip()):
            return "\n".join(lines[:i])
    return text or ""


def extract_citations(text: str) -> list[int]:
    """Every cited source index, in order, duplicates kept.

    A grouped marker contributes each of its numbers: `[1, 3]` yields `[1, 3]`, so it is
    counted and resolution-checked identically to `[1][3]`.
    """
    out: list[int] = []
    for m in CITE_RE.finditer(text or ""):
        out.extend(int(part) for part in m.group(1).split(","))
    return out


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


def split_sentences(text: str) -> list[str]:
    """Split a block of prose into sentences, rejoining common abbreviation false splits."""
    parts = _SENTENCE_SPLIT_RE.split(text)
    if len(parts) < 2:
        return [text]
    merged: list[str] = [parts[0]]
    for part in parts[1:]:
        # "…supported by Dr. Smith" must not become two sentences.
        if _ABBREV_TAIL_RE.search(merged[-1]):
            merged[-1] = f"{merged[-1]} {part}"
        else:
            merged.append(part)
    return merged


def claim_lines(text: str) -> list[str]:
    """Individually assertable claims from the report body, one per sentence.

    Sentences, not raw lines. The synthesizer emits each paragraph as a single unwrapped
    line, so a line-per-claim split made a four-sentence paragraph one "claim" carrying
    the union of its citations — and the citation-support judge then had to rule on all
    four assertions against all four sources at once, scoring a NO if any part was
    unsupported by any snippet. That conflation was measured depressing the support rate
    independently of the actual research quality (docs/12 M5).

    Headings, list markers, and trivially short fragments are still excluded.
    """
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
        for sentence in split_sentences(content):
            sentence = sentence.strip()
            if len(sentence) < 15 or not re.search(r"[A-Za-z]", sentence):
                continue
            out.append(sentence)
    return out


def uncited_claim_count(text: str) -> int:
    """Assertive lines carrying no [n] citation — a proxy for unsupported claims."""
    return sum(1 for c in claim_lines(text) if not CITE_RE.search(c))


# Bumped whenever a metric's *definition* changes, so two committed runs are never
# silently compared across incompatible definitions. Recorded in every results file.
#
#   1 — original: citations matched `[n]` only; claims were raw lines.
#   2 — grouped markers `[1, 3]` counted as separate citations; claims split on sentences
#       (docs/12 M5, defect D1). Both enlarge the denominator, so a v2 number is NOT
#       comparable to a v1 number.
METRICS_VERSION = 2


def report_metrics(text: str, sources: list[dict]) -> dict:
    """Structural quality for one report."""
    stats = citation_stats(text, sources)
    return {
        "word_count": len((text or "").split()),
        "source_count": len(sources or []),
        **stats,
        "uncited_claim_count": uncited_claim_count(text),
    }
