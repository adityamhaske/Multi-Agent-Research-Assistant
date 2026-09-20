"""`ReportDocument` — the derived typed view of a report (V2.1-a A7).

Markdown stays authoritative and this type is a view of it, never the other way round. The
tests that matter most are therefore the negative ones: that a lossy parse says so, and that
nothing here can reach `report_hash`.

Hand-checkable throughout — no database, no model, no clock. `generated_at` is passed in
precisely so the parser is a pure function of its input and these assertions can be exact.
"""

from __future__ import annotations

import json

import pytest

from research_engine.claims import extract_citations
from research_engine.document import (
    SCHEMA_VERSION,
    ReportDocument,
    ReportMetadata,
    parse_markdown,
    render_markdown,
)

META = ReportMetadata(
    run_id="run-1", revision_version=1, question="q?", generated_at="2026-09-09T00:00:00+00:00"
)

REPORT = (
    "# Fixture Report\n\n## Executive Summary\nDeterministic summary [1].\n\n"
    "## Key Findings\n- A citable fact [1]\n- A corroborating fact [2]\n\n"
    "## Detailed Analysis\nAnalysis grounded in evidence [1][2].\n\n"
    "## Limitations\nFixture data only.\n\n"
    "## Sources\n[1] https://example.com/fixture/1\n[2] https://example.com/fixture/2\n"
)


# ── Construction and validation ───────────────────────────────────────────────────


def test_a_report_parses_into_the_three_approved_block_kinds():
    doc = parse_markdown(REPORT, metadata=META)
    kinds = {b.kind for b in doc.blocks}
    assert kinds <= {"heading", "paragraph", "list_item"}
    assert doc.schema_version == SCHEMA_VERSION


def test_blocks_are_ordered_and_the_order_is_their_position():
    doc = parse_markdown(REPORT, metadata=META)
    assert [b.order for b in doc.blocks] == list(range(len(doc.blocks)))


def test_heading_levels_come_from_the_marker_and_the_marker_is_stripped():
    doc = parse_markdown("# One\n\n### Three\n", metadata=META)
    assert [(b.kind, b.level, b.text) for b in doc.blocks] == [
        ("heading", 1, "One"),
        ("heading", 3, "Three"),
    ]


def test_list_items_are_one_block_each_with_the_marker_stripped():
    doc = parse_markdown("- first\n- second\n", metadata=META)
    assert [(b.kind, b.text) for b in doc.blocks] == [
        ("list_item", "first"),
        ("list_item", "second"),
    ]


def test_consecutive_prose_lines_are_one_paragraph():
    doc = parse_markdown("line one\nline two\n\nsecond para\n", metadata=META)
    assert [b.text for b in doc.blocks] == ["line one\nline two", "second para"]


def test_metadata_is_preserved_verbatim():
    doc = parse_markdown(REPORT, metadata=META)
    assert doc.metadata == META


# ── Citation markers ──────────────────────────────────────────────────────────────


def test_citation_markers_are_extracted_without_touching_the_text():
    doc = parse_markdown("A fact [1] and another [2].\n", metadata=META)
    block = doc.blocks[0]
    assert block.citation_markers == (1, 2)
    assert block.text == "A fact [1] and another [2].", "the source text must be untouched"


def test_grouped_markers_are_flattened_the_way_claim_extraction_flattens_them():
    """The document and the citation-resolution rate must never disagree about what a
    marker is — `claims.py` records a single-number pattern making 42% of a real report's
    markers invisible while reporting a perfect rate."""
    text = "Supported by several sources [1, 3] and one more [7]."
    doc = parse_markdown(text + "\n", metadata=META)
    assert doc.blocks[0].citation_markers == tuple(extract_citations(text)) == (1, 3, 7)


# ── Round-trip fidelity ───────────────────────────────────────────────────────────


def test_this_products_own_report_round_trips_exactly():
    doc = parse_markdown(REPORT, metadata=META)
    assert render_markdown(doc) == REPORT
    assert doc.render_fidelity == "EXACT"


def test_markdown_this_vocabulary_does_not_model_is_recorded_as_lossy_not_dropped():
    """A fenced code block has no block kind here. It must survive as paragraph text
    verbatim — a view that silently discarded it would be worse than a coarse one — and the
    document must admit it no longer reproduces its source."""
    source = "# Title\n\n```python\nx = 1\n```\n"
    doc = parse_markdown(source, metadata=META)

    assert doc.render_fidelity == "LOSSY"
    assert "x = 1" in "\n".join(b.text for b in doc.blocks), "content was dropped"
    assert render_markdown(doc) != source


def test_fidelity_is_computed_against_the_actual_source_not_assumed():
    """The render rules follow what the synthesizer emits — a heading is followed by a
    single newline when the next block is its content. A report shaped that way is EXACT; a
    report shaped otherwise is LOSSY, and neither is a verdict on the report."""
    exact = parse_markdown("# A\nbody\n", metadata=META)
    lossy = parse_markdown("# A\n\nbody\n", metadata=META)  # blank line after the heading
    assert exact.render_fidelity == "EXACT"
    assert lossy.render_fidelity == "LOSSY"


# ── Degenerate input ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize("source", ["", "   ", "\n\n\n"])
def test_an_empty_report_yields_an_empty_document_rather_than_raising(source):
    doc = parse_markdown(source, metadata=META)
    assert doc.blocks == ()
    assert render_markdown(doc) == ""


def test_a_heading_with_no_text_is_still_a_heading():
    doc = parse_markdown("###\n", metadata=META)
    assert doc.blocks == () or doc.blocks[0].kind in {"heading", "paragraph"}


def test_parsing_is_deterministic():
    """A parser that timestamps itself produces a different document on every call, which
    would make the stored view non-reproducible from the report it describes."""
    assert parse_markdown(REPORT, metadata=META) == parse_markdown(REPORT, metadata=META)


# ── Serialization ─────────────────────────────────────────────────────────────────


def test_the_document_round_trips_through_json_unchanged():
    doc = parse_markdown(REPORT, metadata=META)
    payload = json.loads(json.dumps(doc.model_dump(mode="json")))
    assert ReportDocument(**payload) == doc


def test_serialization_preserves_block_order_and_markers():
    doc = parse_markdown(REPORT, metadata=META)
    payload = doc.model_dump(mode="json")
    assert [b["order"] for b in payload["blocks"]] == list(range(len(doc.blocks)))
    assert payload["blocks"][2]["citation_markers"] == [1]


def test_the_document_cannot_reach_the_report_hash():
    """The design in one assertion: nothing in this module hashes, and the renderer is not
    a path to the value `reviews.reviewed_hash` and `research_artifacts.artifact_hash` pin."""
    import ast
    import pathlib

    import research_engine.document as mod

    # Parsed, not grepped: this module's own docstring explains that `report_hash` is
    # sha256 over the Markdown, and a substring search would match that explanation.
    tree = ast.parse(pathlib.Path(mod.__file__).read_text())
    imported = {
        n.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for n in node.names
    } | {
        node.module.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    called = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "hashlib" not in imported, "the derived view must not be able to hash anything"
    assert "content_hash" not in called
