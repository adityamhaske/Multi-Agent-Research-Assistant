"""Unit tests for the eval metrics (docs/08 §5) — the numbers in a committed eval run
are only trustworthy if the metric functions are tested."""

from evals import metrics

FAKE_REPORT = (
    "# Fixture Report\n\n## Executive Summary\nDeterministic summary [1].\n\n"
    "## Key Findings\n- A citable fact [1]\n- A corroborating fact [2]\n\n"
    "## Detailed Analysis\nAnalysis grounded in evidence [1][2].\n\n"
    "## Limitations\nFixture data only.\n\n"
    "## Sources\n[1] https://example.com/fixture/1\n[2] https://example.com/fixture/2\n"
)
FAKE_SOURCES = [
    {"index": 1, "url": "https://example.com/fixture/1", "title": "S1", "snippet": "a"},
    {"index": 2, "url": "https://example.com/fixture/2", "title": "S2", "snippet": "b"},
]


def test_extract_citations_preserves_order_and_duplicates():
    assert metrics.extract_citations("a [1] b [2] c [1]") == [1, 2, 1]


def test_citation_stats_all_resolve():
    stats = metrics.citation_stats(FAKE_REPORT, FAKE_SOURCES)
    assert stats["total_citations"] == 5  # 1 + 1 + 1 + 2 (in [1][2])
    assert stats["unresolved_citations"] == 0
    assert stats["resolution_rate"] == 1.0


def test_citation_stats_flags_unresolved():
    stats = metrics.citation_stats("Claim [1] and [9].", FAKE_SOURCES)
    assert stats["total_citations"] == 2
    assert stats["unresolved_citations"] == 1  # [9] has no source
    assert stats["resolution_rate"] == 0.5


def test_resolution_rate_is_none_without_citations():
    assert metrics.citation_stats("No citations here.", FAKE_SOURCES)["resolution_rate"] is None


def test_uncited_claim_count_counts_only_the_limitations_line():
    # Every line carries a citation except "Fixture data only." (Sources section excluded).
    assert metrics.uncited_claim_count(FAKE_REPORT) == 1


def test_uncited_claim_ignores_headings_and_short_lines():
    text = "# Title\n\nok\n\nThis is a substantial uncited claim about the world.\n"
    assert metrics.uncited_claim_count(text) == 1  # heading + "ok" ignored


def test_sources_after_heading_are_not_claims():
    text = (
        "A real cited claim about the topic [1].\n\n## References\nSome uncited reference line.\n"
    )
    assert metrics.uncited_claim_count(text) == 0


def test_report_metrics_shape():
    m = metrics.report_metrics(FAKE_REPORT, FAKE_SOURCES)
    assert m["source_count"] == 2
    assert m["uncited_claim_count"] == 1
    assert m["resolution_rate"] == 1.0
    assert m["word_count"] > 0
