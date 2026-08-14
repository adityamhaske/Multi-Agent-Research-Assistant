"""
Contradiction detection (docs/12 M11): the observable trust feature.

Two sources asserting incompatible things is checkable without a truth model — so it
is the one trust feature that can be *demonstrated* rather than asserted. The detector
runs once per research run over the finished evidence, between the critic and the
synthesizer; whatever it finds is surfaced verbatim in a first-class report block and
at the review gate. **It never resolves a conflict** — adjudication is the human's job.

Division of labor:

- This module is pure: grouping, prompt-input shaping, output validation, and the
  deterministic block renderer. All of it is unit-tested without a model.
- The LLM call itself lives in `graph.contradiction_detector_node`, which reuses the
  graph's `_structured` fail-closed helper. An unavailable detector surfaces *nothing*
  (and says so in the agent log) — inventing conflicts would be worse than missing them.

Fail-closed details that matter:

- A pair naming a source URL that is not in the evidence is dropped. A prompt-injected
  snippet cannot thereby launder a fake source into the report's conflict block.
- Input snippets are wrapped in `<untrusted_web_content>` exactly like the executor sees
  them (docs/06 §4) — the detector is one more reader of untrusted text.
- The block the synthesizer appends is rendered HERE, deterministically, from the
  validated pairs. The LLM never authors it, so it can neither omit nor "resolve" it.
"""

from __future__ import annotations

import re

from research_engine.schemas import ContradictionPair

# Prompt-size caps. Cost is a design constraint (docs/01): one bounded detector call per
# run, never per-pair calls that scale quadratically with source count.
MAX_SOURCES = 12
MAX_SNIPPETS_PER_SOURCE = 4
MAX_SNIPPET_CHARS = 500

# Matches the report's reference-list heading, same family as evals.metrics uses, so the
# conflict block can be inserted before it regardless of which synonym the model wrote.
_SOURCES_HEADING_RE = re.compile(r"^#{1,6}\s*(sources|references|citations|bibliography)\b", re.I)


def group_snippets_by_source(evidence: list[dict]) -> dict[str, list[str]]:
    """Evidence → ordered {source_url: [distinct snippets]}, capped for the detector.

    Order is first-appearance order, the same convention the synthesizer uses for
    citation numbering, so detector input and report sources stay aligned.
    """
    by_source: dict[str, list[str]] = {}
    for e in evidence:
        url = (e.get("source_url") or "").strip()
        snippet = (e.get("snippet") or "").strip()
        if not url or not snippet:
            continue
        bucket = by_source.setdefault(url, [])
        if len(bucket) >= MAX_SNIPPETS_PER_SOURCE:
            continue
        trimmed = snippet[:MAX_SNIPPET_CHARS]
        if trimmed not in bucket:
            bucket.append(trimmed)
    # Keep only the first MAX_SOURCES sources — the detector's budget is fixed.
    return dict(list(by_source.items())[:MAX_SOURCES])


def build_detector_input(by_source: dict[str, list[str]]) -> str:
    """The human-message body the detector sees: sources with their verbatim snippets."""
    blocks: list[str] = ["Sources and their verbatim snippets:"]
    for url, snippets in by_source.items():
        lines = [f"Source: {url}", "<untrusted_web_content>"]
        lines.extend(f'- "{s}"' for s in snippets)
        lines.append("</untrusted_web_content>")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def normalize_pairs(
    pairs: list[ContradictionPair], known_urls: set[str]
) -> list[ContradictionPair]:
    """Best-effort field-shift repair for weaker models (docs/12 M11).

    deepseek-r1:14b correctly identifies contradictions but mis-fills the structured
    fields: it puts URLs into snippet_* and "Source: <url>" into source_*. This narrow
    normalization fixes the two observed patterns:

    1. Strip a leading "Source: " prefix from source_a / source_b.
    2. If source_* is still not a known URL but the corresponding snippet_* IS, swap them.

    The result is still fed to validate_pairs, so no hallucinated URL can sneak through.
    """
    out: list[ContradictionPair] = []
    for p in pairs:
        d = p.model_dump()
        for side in ("a", "b"):
            src_key, snip_key = f"source_{side}", f"snippet_{side}"
            # Strip "Source: " prefix (case-insensitive).
            src = d[src_key].strip()
            if src.lower().startswith("source:"):
                src = src[len("source:") :].strip()
            d[src_key] = src
            # If source is not a known URL but snippet is, swap them.
            if d[src_key] not in known_urls and d[snip_key].strip() in known_urls:
                d[src_key], d[snip_key] = d[snip_key].strip(), d[src_key]
        out.append(ContradictionPair(**d))
    return out


def validate_pairs(pairs: list[ContradictionPair], by_source: dict[str, list[str]]) -> list[dict]:
    """Detector output → report-ready dicts, with everything untrustworthy dropped.

    - Both URLs must be sources the detector was actually shown (no hallucinated or
      injected sources).
    - A source cannot contradict itself here: same-URL pairs are dropped.
    - Duplicate pairs (same two URLs, same claims either way around) collapse to one.
    """
    known = set(by_source)
    seen_keys: set[tuple] = set()
    out: list[dict] = []
    for p in pairs:
        if p.source_a not in known or p.source_b not in known or p.source_a == p.source_b:
            continue
        key = (frozenset((p.source_a, p.source_b)), frozenset((p.claim_a, p.claim_b)))
        if key in seen_keys:
            continue
        seen_keys.add(key)
        out.append(p.model_dump())
    return out


def render_block(contradictions: list[dict], index_of: dict[str, int]) -> str:
    """The deterministic Markdown block appended to the report.

    `index_of` maps source URL → the synthesizer's [n] citation number, so each side of
    a conflict points at the exact entry in the report's source list. The wording is
    load-bearing: it states that the report does NOT resolve the conflict.
    """
    lines = [
        "## Conflicting evidence",
        "",
        "The sources below make claims that cannot both be true. This report does **not**",
        "resolve these conflicts — they are surfaced as-is for the reviewer to adjudicate.",
        "",
    ]
    for i, c in enumerate(contradictions, start=1):
        a = index_of.get(c["source_a"], 0)
        b = index_of.get(c["source_b"], 0)
        nature = (c.get("nature") or "the two claims are incompatible as stated").strip()
        lines.append(f"{i}. [{a}] claims that {c['claim_a']} — [{b}] claims that {c['claim_b']}.")
        lines.append(f"   Nature of disagreement: {nature}")
        if c.get("snippet_a") and c.get("snippet_b"):
            lines.append(f'   Verbatim: "{c["snippet_a"]}" vs "{c["snippet_b"]}"')
        lines.append("")
    return "\n".join(lines).rstrip()


def insert_block(draft: str, block: str) -> str:
    """Place the conflict block before the report's reference list (after everything else).

    A conflict buried below the Sources heading would be invisible in practice; a block
    prepended would shove the executive summary down. Before Sources, after Limitations,
    is where a first-class finding lives. Reports without a recognizable sources heading
    get the block appended.
    """
    lines = draft.splitlines()
    for i, raw in enumerate(lines):
        if _SOURCES_HEADING_RE.match(raw.strip()):
            return "\n".join(lines[:i] + ["", block, ""] + lines[i:])
    return f"{draft.rstrip()}\n\n{block}"
