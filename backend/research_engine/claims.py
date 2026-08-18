"""
Claim and citation extraction — the canonical implementation (docs/08 §5, docs/12 M5).

Three callers need to agree on *what a claim is* and *what counts as a citation*, because
they measure and act on the same sentences:

- `graph._verify_citation_fidelity` strips markers from claims their evidence does not back
- `evals.metrics` / `evals.harness` judge those same claims and publish a support rate
- `bundle.assemble` records them in the artifact a third party verifies

Two implementations of one definition is how the number a benchmark publishes and the
claims the pipeline acted on drift apart. This module is the single definition.

**It lives in the engine, not in `evals/`.** `research_engine/` must run inside a desktop
app with no eval harness installed, and `bundle.py` needs claim extraction — so the import
used to run engine → evals, which made the "standalone" engine package un-shippable
without `evals/` and contradicted `graph.py`'s own docstring. The dependency now points
the other way: `evals.metrics` re-exports from here. Nothing in this module imports
anything but `re`, which is what keeps `verify_bundle` runnable on a bare machine.

Everything here is pure and stdlib-only. Eval-specific aggregation (`METRICS_VERSION`,
`report_metrics`, `citation_stats`) stays in `evals.metrics`, because those are properties
of a measurement run rather than of a claim.
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
# The Limitations section is where the model is INSTRUCTED to write what the evidence
# does not cover — meta-prose about the evidence, sourced or not. Its sentences are not
# factual claims, so they are excluded from claim extraction exactly like Sources.
LIMITATIONS_HEADING_RE = re.compile(r"^#{1,6}\s*limitations?\b", re.I)
# The Conflicting evidence block (docs/12 M11) is rendered deterministically by the
# engine, not authored by the synthesizer: it QUOTES the incompatible claims from both
# sides. Its sentences are meta-prose about the evidence — judging them as factual
# claims would measure the block's existence, not research quality — so they are
# excluded from claim extraction exactly like Limitations.
CONFLICTS_HEADING_RE = re.compile(r"^#{1,6}\s*conflicting evidence\b", re.I)
LIST_MARKER_RE = re.compile(r"^(?:[-*+]\s+|\d+[.)]\s+)")
# Sentence boundary: terminator + whitespace, not preceded by a common abbreviation or a
# bare initial. Deliberately conservative — over-splitting a claim is worse than
# under-splitting it, because each fragment then gets judged against too little evidence.
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z(\[])")
ABBREV_TAIL_RE = re.compile(r"\b(?:e\.g|i\.e|vs|etc|Dr|Mr|Ms|Inc|Ltd|Fig|No|approx|cf)\.$", re.I)

#: A sentence shorter than this, or containing no letters, is a fragment rather than a
#: claim. Named because the graph's fidelity pass applies the same floor and the two must
#: not drift.
MIN_CLAIM_CHARS = 15


def body_before_sources(text: str) -> str:
    """The report body up to (excluding) the sources/references section.

    The numbered entries in a reference list are not claims. Counting them would push
    every report's rate toward 1.0 regardless of what the prose actually cited.
    """
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


def split_sentences(text: str) -> list[str]:
    """Split a block of prose into sentences, rejoining common abbreviation false splits."""
    parts = SENTENCE_SPLIT_RE.split(text)
    if len(parts) < 2:
        return [text]
    merged: list[str] = [parts[0]]
    for part in parts[1:]:
        # "…supported by Dr. Smith" must not become two sentences.
        if ABBREV_TAIL_RE.search(merged[-1]):
            merged[-1] = f"{merged[-1]} {part}"
        else:
            merged.append(part)
    return merged


def is_claim_sentence(sentence: str) -> bool:
    """Whether a split fragment is long enough and wordy enough to assert anything."""
    return len(sentence) >= MIN_CLAIM_CHARS and bool(re.search(r"[A-Za-z]", sentence))


def claim_lines(text: str) -> list[str]:
    """Individually assertable claims from the report body, one per sentence.

    Sentences, not raw lines. The synthesizer emits each paragraph as a single unwrapped
    line, so a line-per-claim split made a four-sentence paragraph one "claim" carrying
    the union of its citations — and the citation-support judge then had to rule on all
    four assertions against all four sources at once, scoring a NO if any part was
    unsupported by any snippet. That conflation was measured depressing the support rate
    independently of the actual research quality (docs/12 M5).

    Headings, list markers, and trivially short fragments are still excluded. So is the
    Limitations section: it is where the synthesizer is told to write what the evidence
    does NOT cover, and those hedging sentences are not factual claims the snippets must
    support — judging them measured report honesty as citation failure (docs/12 M5).
    """
    out: list[str] = []
    skipping = False
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        if SOURCES_HEADING_RE.match(line):
            break  # sources/references section is references, not claims
        if HEADING_RE.match(line):
            skipping = bool(LIMITATIONS_HEADING_RE.match(line)) or bool(
                CONFLICTS_HEADING_RE.match(line)
            )
            continue
        if skipping:
            continue
        content = LIST_MARKER_RE.sub("", line)
        for sentence in split_sentences(content):
            sentence = sentence.strip()
            if not is_claim_sentence(sentence):
                continue
            out.append(sentence)
    return out
