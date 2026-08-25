"""
Grouped citation markers (docs/12 M5).

Found by the first real-model eval, not by a passing test — which is the point of running
one. The synthesizer writes `[1, 3]` when a sentence rests on several sources (ordinary
academic style, and the prompt never forbade it), and the single-number-only pattern in
both this module and the frontend renderer silently treated those as prose.

The consequence was worse than a wrong metric. In the UI a grouped citation rendered as
inert text: no chip, no link, and **no ⚠ unverified chip either**. A citation could fail
to resolve and the product would never admit it — the exact opposite of the guarantee the
project is built on. On the measured report, 42% of all citation references were inside
grouped brackets and invisible to both parsers, while `resolution_rate` still read 1.0.

The strings below are taken verbatim from that run.
"""

from __future__ import annotations

from evals import metrics

# Real sentences from the eval-2026-07-31 postgres-vs-mysql report.
REAL_GROUPED = (
    "PostgreSQL offers superior advanced features, robust data integrity, and enhanced "
    "scalability, making it ideal for complex, data-intensive, and future-proof "
    "applications [1, 3]."
)
REAL_LONG_GROUP = (
    "Its growing ecosystem, strong support for SQL standards, ACID compliance across all "
    "configurations, and advanced capabilities like JSONB for NoSQL workloads, DDL "
    "transactions, and MVCC provide significant advantages for SaaS development "
    "[1, 2, 3, 4, 6]."
)


# ── Extraction ─────────────────────────────────────────────────────────────────────


def test_grouped_marker_yields_every_index():
    assert metrics.extract_citations(REAL_GROUPED) == [1, 3]


def test_long_group_yields_every_index():
    assert metrics.extract_citations(REAL_LONG_GROUP) == [1, 2, 3, 4, 6]


def test_grouped_and_separate_markers_are_equivalent():
    """`[1, 3]` and `[1][3]` must count identically — the whole point of the fix."""
    assert metrics.extract_citations("a claim [1, 3]") == metrics.extract_citations(
        "a claim [1][3]"
    )


def test_spacing_variants_all_parse():
    for text in ("[1,3]", "[1, 3]", "[1 , 3]", "[1,  3]"):
        assert metrics.extract_citations(text) == [1, 3], text


def test_single_markers_still_work():
    assert metrics.extract_citations("one [1] two [2] three [3]") == [1, 2, 3]


def test_non_citation_brackets_are_ignored():
    assert metrics.extract_citations("[TODO] and [see below] and []") == []


# ── Resolution: the failure that used to hide ──────────────────────────────────────


def test_unresolved_index_inside_a_group_is_now_counted_as_unresolved():
    """Previously invisible: a bad index inside a group produced no ⚠ and no metric hit."""
    sources = [{"index": 1}, {"index": 3}]
    stats = metrics.citation_stats("A claim [1, 3, 99].", sources)

    assert stats["total_citations"] == 3
    assert stats["unresolved_citations"] == 1
    assert stats["resolution_rate"] == round(2 / 3, 4)


def test_a_report_of_only_grouped_citations_is_no_longer_scored_as_uncited():
    sources = [{"index": 1}, {"index": 2}]
    report = f"# T\n\n{REAL_GROUPED}\n\n## Sources\n[1] x\n[2] y\n"

    assert metrics.uncited_claim_count(report) == 0
    assert metrics.citation_stats(report, sources)["total_citations"] == 2


# ── Sentence-level claims ──────────────────────────────────────────────────────────


def test_a_paragraph_becomes_one_claim_per_sentence():
    """A four-sentence paragraph used to be judged as a single all-or-nothing claim."""
    paragraph = (
        "PostgreSQL ranked 2nd in the DB-Engines Ranking [2]. "
        "It has won DBMS of the Year five times [3]. "
        "Its usage rate now surpasses MySQL's [2]. "
        "By 2025 its popularity had nearly matched MySQL's [16]."
    )
    claims = metrics.claim_lines(paragraph)

    assert len(claims) == 4
    assert metrics.extract_citations(claims[0]) == [2]
    assert metrics.extract_citations(claims[3]) == [16]


def test_abbreviations_do_not_split_a_sentence():
    text = "Managed options exist, e.g. Supabase and Neon, which auto-scale [4]."
    assert len(metrics.claim_lines(text)) == 1


def test_decimal_numbers_do_not_split_a_sentence():
    text = "Performance differs by at most 30.5 percent across these workloads [1]."
    assert len(metrics.claim_lines(text)) == 1


def test_headings_and_source_list_are_still_excluded():
    report = (
        "# Title\n\n"
        "## Executive Summary\n\n"
        "A real claim about databases [1].\n\n"
        "## Sources\n"
        "[1] https://example.com\n"
        "[2] https://example.org\n"
    )
    claims = metrics.claim_lines(report)

    assert len(claims) == 1
    assert "real claim" in claims[0]


def test_citations_in_the_sources_list_are_not_counted_as_in_text():
    report = "Body claim [1, 2].\n\n## Sources\n[1] a\n[2] b\n[3] c\n"
    assert metrics.citation_stats(report, [{"index": 1}, {"index": 2}])["total_citations"] == 2


# ── The prompt no longer permits the shape ─────────────────────────────────────────


def test_synthesizer_prompt_forbids_grouped_markers():
    """Defence in depth: parsers tolerate groups, but the prompt asks for separate ones."""
    from research_engine import prompts

    assert "[1][3]" in prompts.SYNTHESIZER_PROMPT_V2
    assert "NOT [1, 3]" in prompts.SYNTHESIZER_PROMPT_V2


# ── Export path (the third instance of the same bug) ───────────────────────────────


def test_export_superscripts_each_number_in_a_grouped_marker():
    """Exported .md/.pdf must chip grouped citations the same way the UI does."""
    from app.services import export

    html_out = export.render_html(REAL_GROUPED, [{"index": 1}, {"index": 3}])

    assert "<sup>[1]</sup><sup>[3]</sup>" in html_out
    assert "[1, 3]" not in html_out, "grouped marker should not survive unstyled"


def test_export_still_superscripts_a_single_marker():
    from app.services import export

    html_out = export.render_html("A claim [2].", [{"index": 2}])
    assert "<sup>[2]</sup>" in html_out
