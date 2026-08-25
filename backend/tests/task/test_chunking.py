"""
Report chunking for project memory (docs/14 §4).

Chunking is where retrieval quality is won or lost, and it is the one part of memory that
needs no database, no key and no model to test — so it is tested hard here rather than
inferred from end-to-end behaviour later.

Two properties are load-bearing beyond "it splits text":

- **Determinism**, because re-ingesting a report must collide with the existing
  `(source_session_id, chunk_index)` rows instead of duplicating them.
- **The size ceiling**, because every chunk is an embedding call and eight of them ride
  in every chat prompt. A chunker that quietly overshoots turns the budget ceiling in
  docs/12 into a guess.
"""

from __future__ import annotations

from research_engine.chunking import MIN_CHARS, TARGET_CHARS, chunk_report

REPORT = """# Solar Capacity 2025

Global solar capacity grew 32 percent in 2025 [1]. That is the fastest year on record,
and the growth was driven overwhelmingly by China [2]. Analysts had forecast 18 percent,
so the size of the miss matters for grid planning rather than being a rounding error.

## Limitations

The underlying dataset stops at Q3 [3]. Fourth-quarter figures are extrapolated from the
first three quarters and have not been independently audited, which is the single largest
caveat on everything above.
"""


def test_empty_input_produces_no_chunks():
    for empty in ("", "   ", "\n\n\n"):
        assert chunk_report(empty) == []


def test_short_report_is_one_chunk():
    chunks = chunk_report("# Title\n\nOne short finding.")
    assert len(chunks) == 1
    assert "One short finding" in chunks[0]


def test_headings_only_document_yields_nothing():
    """A chunk of pure headings would match a topical query and then say nothing."""
    assert chunk_report("# A\n\n## B\n\n### C") == []


def test_chunking_is_deterministic():
    """Re-ingestion relies on this: same report in, same chunks out, same indexes."""
    assert chunk_report(REPORT * 4) == chunk_report(REPORT * 4)


def test_no_chunk_exceeds_the_target_size():
    """Including the heading and overlap a continuation chunk prepends."""
    for text in (REPORT * 6, "word " * 3000, "x" * 5000, "## H\n\n" + "para " * 900):
        assert all(len(chunk) <= TARGET_CHARS for chunk in chunk_report(text))


def test_oversized_single_sentence_still_splits():
    """A table row or URL list with no sentence boundary must not become one huge chunk."""
    chunks = chunk_report("y" * 4000)
    assert len(chunks) > 1
    assert all(len(chunk) <= TARGET_CHARS for chunk in chunks)


def test_citation_markers_survive():
    """The chat citation chain resolves through these back to the report's sources."""
    joined = "\n".join(chunk_report(REPORT))
    assert "[1]" in joined
    assert "[3]" in joined


def test_headings_are_carried_into_continuation_chunks():
    """A chunk lifted out of a section keeps saying which section it came from."""
    body = "## Limitations\n\n" + "The dataset stops at Q3. " * 120
    chunks = chunk_report(body)
    assert len(chunks) > 1
    assert all(chunk.startswith("## Limitations") for chunk in chunks)


def test_sections_do_not_shard_into_tiny_chunks():
    """Many short sections pack together — each chunk is an embedding, and spend."""
    text = "".join(f"## Section {i}\n\nA short finding about topic {i}.\n\n" for i in range(12))
    chunks = chunk_report(text)
    assert len(chunks) == 1, f"expected one packed chunk, got {[len(c) for c in chunks]}"


def test_no_runt_chunk_at_the_end():
    """A trailing scrap is merged back rather than stored as its own hit."""
    chunks = chunk_report(REPORT * 3)
    if len(chunks) > 1:
        assert len(chunks[-1]) >= MIN_CHARS


def test_overlap_keeps_a_straddling_claim_whole():
    """A sentence at a boundary appears complete in at least one chunk."""
    claim = "The audit found no material misstatement in the Q3 figures."
    text = "filler sentence here. " * 60 + claim + " more filler. " * 60
    chunks = chunk_report(text)
    assert any(claim in chunk for chunk in chunks)
