"""
Claim-extraction parity (M0A).

`graph._verify_citation_fidelity` strips citation markers from claims their own evidence
does not back. `evals.harness.judge_citation_support` then measures how well that worked.
If the two disagree about *what a claim is*, the measurement stops measuring the guard —
the judge rules on sentences the pass never saw, or on fragments of them.

`graph.py` has carried a comment asserting the two "MUST mirror" each other since docs/12
M5. Nothing checked it, and the two implementations were separate copies of four regexes
plus a hand-inlined sentence splitter. These tests are that check.

They pin three things:

1. **Identity** — `evals.metrics` and `graph` use the *same objects* from
   `research_engine.claims`, so a copy-paste back into either file fails here.
2. **Agreement** — over a corpus of report shapes, the cited claims the graph acts on are
   exactly the cited claims the judge rules on.
3. **The deliberate divergences** — two scanning differences remain on purpose. Pinned so
   that they stay deliberate and a third one cannot appear unnoticed.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from evals import metrics
from research_engine import claims, graph, verify_bundle

# ── Fixture reports ───────────────────────────────────────────────────────────────
#
# Each exercises a splitting rule that has actually mattered: multi-sentence paragraphs
# (docs/12 M5 D1), abbreviation false-splits, list markers, grouped markers, the
# Limitations exclusion (D5), short fragments, and uncited prose.

# Paragraphs are deliberately UNWRAPPED. Both scans work line by line, and the synthesizer
# emits each paragraph as a single long line (see `claims.claim_lines`' docstring), so a
# hard-wrapped fixture would exercise a shape the pipeline never produces. `_HARD_WRAPPED`
# below pins what happens when one appears anyway.
_PLAIN = """\
# Findings

Postgres logical replication adds measurable write overhead [1]. The published figure is around eight percent [2]. This is not a universal result.

## Detail

- Replication slots retain WAL until consumed [3].
- Throughput fell by 8.1% under the pgbench workload [1, 3].
"""

_ABBREVIATIONS = """\
# Findings

The benchmark was run by Dr. Smith at Acme Inc. and showed no regression [1]. Other suites, e.g. TPC-C, were not attempted [2].
"""

#: A paragraph broken across source lines. Each line is scanned independently, so the
#: sentence spanning the break becomes two fragments. Pinned because it is a real property
#: of both scans, and because the two must agree about it — which is what matters here.
_HARD_WRAPPED = """\
# Findings

Postgres logical replication adds measurable write overhead [1]. The published figure is
around eight percent [2].
"""

_WITH_LIMITATIONS = """\
# Findings

Cold-start latency improved by 40% after the change [1].

## Limitations

No production workload was measured [1]. The sample covered a single region.

## Sources

1. https://example.org/a
2. https://example.org/b
"""

_UNCITED_AND_SHORT = """\
# Findings

Yes.

Short one.

This sentence is long enough to be a claim but carries no citation marker at all.

This sentence is long enough to be a claim and does carry one [2].
"""

_GROUPED = """\
# Findings

Three independent measurements agree on the direction of the effect [1, 2, 4]. A fourth
disagrees [3].
"""

#: Reports whose scanning falls entirely inside the two implementations' shared domain —
#: no bare `Sources` line, no engine-rendered conflict block. These must agree exactly.
SHARED_DOMAIN_REPORTS = [
    _PLAIN,
    _ABBREVIATIONS,
    _HARD_WRAPPED,
    _WITH_LIMITATIONS,
    _UNCITED_AND_SHORT,
    _GROUPED,
]


def _judge_cited_claims(report: str) -> list[str]:
    """What the eval judge rules on: cited claims only.

    Mirrors `harness.judge_citation_support`'s own filter
    (`[c for c in metrics.claim_lines(report) if metrics.CITE_RE.search(c)]`) so this test
    compares the graph against what is actually measured, not against a near neighbour.
    """
    return [c for c in metrics.claim_lines(report) if metrics.CITE_RE.search(c)]


# ── 1. Identity of the shared primitives ──────────────────────────────────────────


def test_evals_metrics_reexports_the_engine_primitives():
    """Not "equal patterns" — the same objects. Equality would pass for a fresh copy."""
    assert metrics.CITE_RE is claims.CITE_RE
    assert metrics.SOURCES_HEADING_RE is claims.SOURCES_HEADING_RE
    assert metrics.HEADING_RE is claims.HEADING_RE
    assert metrics.LIMITATIONS_HEADING_RE is claims.LIMITATIONS_HEADING_RE
    assert metrics.CONFLICTS_HEADING_RE is claims.CONFLICTS_HEADING_RE
    assert metrics.claim_lines is claims.claim_lines
    assert metrics.split_sentences is claims.split_sentences
    assert metrics.extract_citations is claims.extract_citations
    assert metrics.body_before_sources is claims.body_before_sources


def test_graph_fidelity_pass_uses_the_engine_primitives():
    assert graph._VSPLIT_RE is claims.SENTENCE_SPLIT_RE
    assert graph._VABBREV_TAIL_RE is claims.ABBREV_TAIL_RE
    assert graph._VLIST_MARKER_RE is claims.LIST_MARKER_RE
    assert graph._VLIMITATIONS_HEADING_RE is claims.LIMITATIONS_HEADING_RE


def test_citation_rate_uses_the_engine_primitives():
    from research_engine import citation_rate

    assert citation_rate.body_before_sources is claims.body_before_sources
    assert citation_rate.cited_indices("a [1] b [2, 3]") == claims.extract_citations(
        "a [1] b [2, 3]"
    )


# ── 2. Agreement over report shapes ───────────────────────────────────────────────


def test_graph_and_judge_agree_on_cited_claims():
    """The property the `MUST mirror` comment has always asserted, now checked."""
    for report in SHARED_DOMAIN_REPORTS:
        assert graph._cited_claims(report) == _judge_cited_claims(report), (
            "graph._cited_claims and evals.metrics.claim_lines disagree on this report; "
            "the fidelity pass would act on different sentences than the judge measures"
        )


def test_agreement_survives_a_report_with_no_claims_at_all():
    for empty in ("", "\n\n", "# Heading only\n"):
        assert graph._cited_claims(empty) == _judge_cited_claims(empty) == []


def test_multi_sentence_paragraph_is_split_not_merged():
    """docs/12 M5 D1: one paragraph is several claims, judged separately."""
    got = graph._cited_claims(_PLAIN)
    assert "Postgres logical replication adds measurable write overhead [1]." in got
    assert "The published figure is around eight percent [2]." in got


def test_abbreviations_do_not_split_a_claim():
    got = graph._cited_claims(_ABBREVIATIONS)
    assert got == [
        "The benchmark was run by Dr. Smith at Acme Inc. and showed no regression [1].",
        "Other suites, e.g. TPC-C, were not attempted [2].",
    ]


def test_hard_wrapped_sentence_fragments_the_same_way_in_both():
    """A paragraph broken across lines fragments — but identically on both sides.

    Parity is what matters, not the fragmenting: the judge scores whatever the fidelity
    pass acted on. Pinned so a "fix" to one scan's line handling cannot land alone.
    """
    assert graph._cited_claims(_HARD_WRAPPED) == _judge_cited_claims(_HARD_WRAPPED)
    assert graph._cited_claims(_HARD_WRAPPED) == [
        "Postgres logical replication adds measurable write overhead [1].",
        "around eight percent [2].",
    ]


def test_limitations_section_is_excluded_by_both():
    assert not any("No production workload" in c for c in graph._cited_claims(_WITH_LIMITATIONS))
    assert not any("No production workload" in c for c in _judge_cited_claims(_WITH_LIMITATIONS))


def test_sources_section_is_excluded_by_both():
    """The bibliography is references, not claims — its digits are URLs and years."""
    assert not any("example.org" in c for c in graph._cited_claims(_WITH_LIMITATIONS))
    assert not any("example.org" in c for c in _judge_cited_claims(_WITH_LIMITATIONS))


# ── 3. The deliberate divergences ─────────────────────────────────────────────────


def test_divergence_bare_sources_line_ends_the_body_only_for_the_graph():
    """`_VSOURCES_RE` allows zero `#`; `claims.SOURCES_HEADING_RE` requires one.

    Deliberate, and deliberately NOT unified: widening the shared pattern would change
    what the judge counts as a claim, which is a metrics-definition change and would need
    a `METRICS_VERSION` bump to be disclosed honestly. Pinned so it stays a decision.
    """
    report = "# Findings\n\nA long enough sentence to count as a claim [1].\n\nSources\n\n1. https://example.org/a-page-with-2024-in-it\n"
    assert graph._cited_claims(report) == ["A long enough sentence to count as a claim [1]."]
    # The judge does not stop at the bare line, so the bibliography entry reaches it.
    assert any("example.org" in c for c in metrics.claim_lines(report))


def test_prose_opening_with_a_sources_word_is_a_claim_to_both():
    """Was a pinned divergence; issue #48 fixed it, so the two now agree.

    `_VSOURCES_RE` used to allow zero `#`, which made it match any sentence merely
    *starting* with one of the boundary words. The fidelity pass then treated that
    sentence as the bibliography and stopped, so it and every later claim were never
    checked — and an unchecked claim keeps its citation markers whether or not its
    snippets back them. The report rendered *more* verified than it was, which is the
    inversion this project exists to refuse.

    Each word is exercised: one occurrence anywhere used to disable the rest of the scan,
    so a fix that only handled "Sources" would leave the same hole behind the other three.
    """
    for word in ("Sources", "References", "Citations", "Bibliography"):
        sentence = f"{word} of error were considered carefully in this analysis [1]."
        report = f"# Findings\n\n{sentence}\n"
        assert graph._cited_claims(report) == [sentence], word
        assert _judge_cited_claims(report) == [sentence], word


def test_a_sources_heading_with_trailing_words_still_ends_the_body_for_both():
    """The fix narrows only the bare-label branch; the heading branch stays open-ended.

    Requiring the *whole line* to be the label — the other candidate fix — would have
    closed the prose hole while opening a new divergence here, since the judge's
    `#{1,6}\\s*(word)\\b` is unanchored and would still end the body at this heading.
    """
    report = (
        "# Findings\n\nA long enough sentence to count as a claim [1].\n\n"
        "## Sources and References\n\n1. https://example.org/a-page-with-2024-in-it\n"
    )
    expected = ["A long enough sentence to count as a claim [1]."]
    assert graph._cited_claims(report) == expected
    assert _judge_cited_claims(report) == expected


def test_divergence_conflicts_block_is_moot_in_production_ordering():
    """The judge skips the conflict block; the fidelity pass has no rule for it.

    That is safe only because `synthesizer_node` appends the block *after*
    `_verify_citation_fidelity` has run. This test pins the ordering the safety depends
    on, by reading the source — if someone moves the append above the check, the block's
    quoted claims would start getting their markers stripped.
    """
    source = Path(graph.__file__).read_text(encoding="utf-8")
    verify_at = source.index("draft, vcost, vi, vo = await _verify_citation_fidelity(")
    insert_at = source.index("draft = contradictions.insert_block(draft, block)")
    assert verify_at < insert_at, (
        "the conflicting-evidence block is now inserted before the citation-fidelity "
        "pass; the block's quoted claims will be judged as the synthesizer's own"
    )


def test_conflicts_block_is_excluded_by_the_judge():
    report = """\
# Findings

A long enough sentence to count as a claim [1].

## Conflicting evidence

1. One side says the figure is 8% [1]. The other says 20% [2].
"""
    assert not any("The other says" in c for c in metrics.claim_lines(report))


# ── 4. The verifier's portable copies ─────────────────────────────────────────────


def test_verifier_regex_copies_match_the_canonical_patterns():
    """`verify_bundle` keeps local copies so it runs on stdlib + pydantic alone.

    That is a deliberate portability choice (see its module docstring), so the copies are
    allowed — but they must not drift, or a bundle would verify against a different
    definition of "citation" than the one that produced it.
    """
    assert verify_bundle._CITE_RE.pattern == claims.CITE_RE.pattern
    assert verify_bundle._CITE_RE.flags == claims.CITE_RE.flags
    assert verify_bundle._SOURCES_HEADING_RE.pattern == claims.SOURCES_HEADING_RE.pattern
    assert verify_bundle._SOURCES_HEADING_RE.flags == claims.SOURCES_HEADING_RE.flags


def test_verifier_body_split_matches_the_canonical_one():
    for report in SHARED_DOMAIN_REPORTS:
        assert verify_bundle._body_before_sources(report) == claims.body_before_sources(report)


# ── 5. The canonical module stays portable ────────────────────────────────────────


def test_claims_module_imports_nothing_but_stdlib():
    """What keeps `verify_bundle`'s "bare machine with Python + pydantic" promise true.

    `bundle.py` imports `claims`, and `verify_bundle` imports `bundle`. If `claims` grew a
    dependency on pydantic, httpx or the eval harness, that promise would quietly become
    false — which is exactly what the old `evals.metrics` import did to it.
    """
    tree = ast.parse(Path(claims.__file__).read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            imported.add(node.module.split(".")[0])
    assert imported <= {"re", "__future__"}, f"claims.py grew a dependency: {sorted(imported)}"


def test_claim_pattern_flattens_grouped_markers():
    """Guards the one regex behaviour a report's resolution rate depends on."""
    assert claims.extract_citations("a [1, 3] b [4]") == [1, 3, 4]
    assert claims.extract_citations("[1][3]") == [1, 3]
    assert claims.extract_citations("no markers here") == []


def test_min_claim_floor_is_shared():
    """Both scans drop the same fragments; the floor is one constant, not two literals."""
    short = "Yes [1]."
    assert not claims.is_claim_sentence(short)
    assert len(short) < claims.MIN_CLAIM_CHARS
    assert re.search(r"[A-Za-z]", short)
