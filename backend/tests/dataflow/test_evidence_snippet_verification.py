"""A citation snippet must be text we actually saw, not text a model produced.

`submit_evidence` arguments are model-authored end to end — `source_url`, `source_title`
and `snippet` alike (graph.py) — and engine code overwrites exactly one field afterwards,
`task_id`. Nothing checked that the quotation existed in the page that was fetched.

Confirmed live on 2026-08-16: a real-model run rendered

    "For overlap heatmaps prefer Morisita-Horn (abundance-weighted, depth-robust) over
     Jaccard (presence/absence, depth-biased), and normalize depth first."

as a verbatim snippet from PMC3543521 ("Methods for diversity and overlap analysis in
T-cell receptor populations"). The paper contains no such sentence. The citation resolved
to a real URL and rendered clean — strictly worse than the ⚠ chip an unresolved marker
gets, because nothing signalled it.
"""

from __future__ import annotations

from research_engine.graph import record_tool_output, verify_evidence_snippets

PAGE = (
    "The Morisita-Horn index (MHI) was used to assess clonal similarity between "
    "repertoires. This index shows the overall clonal overlap between 2 repertoires, "
    "weighted by clonal frequency, ranging from 0 (no overlap) to 1 (complete overlap)."
)
URL = "https://a.example/paper"


def _chunk(snippet: str, url: str = URL) -> dict:
    return {"source_url": url, "source_title": "T", "snippet": snippet, "key_fact": "k"}


def _seen_page(url: str = URL, text: str = PAGE) -> dict[str, str]:
    seen: dict[str, str] = {}
    record_tool_output(seen, "read_webpage", {"url": url, "text": text, "error": None})
    return seen


def test_a_snippet_present_in_the_fetched_page_survives():
    chunk = _chunk("weighted by clonal frequency, ranging from 0 (no overlap)")
    assert verify_evidence_snippets([chunk], _seen_page()) == []
    assert chunk["snippet"].startswith("weighted by clonal frequency")
    assert "snippet_unverified" not in chunk


def test_a_fabricated_snippet_is_blanked_and_reported():
    """The regression: plausible prose, real URL, never in the source."""
    chunk = _chunk(
        "For overlap heatmaps prefer Morisita-Horn (abundance-weighted, depth-robust) "
        "over Jaccard (presence/absence, depth-biased), and normalize depth first."
    )
    fabricated = verify_evidence_snippets([chunk], _seen_page())

    assert fabricated == [chunk]
    assert chunk["snippet"] == "", "an invented quote must not reach the renderer"
    assert chunk["snippet_unverified"] is True
    # The rest of the chunk is left intact — the URL and key_fact may still be sound.
    assert chunk["source_url"] == URL


def test_a_snippet_attributed_to_a_url_we_never_fetched_is_blanked():
    chunk = _chunk(PAGE[:60], url="https://never-fetched.example/x")
    assert verify_evidence_snippets([chunk], _seen_page()) == [chunk]
    assert chunk["snippet"] == ""


def test_rewrapped_lines_and_straightened_quotes_still_verify():
    """Faithful quoting that re-wraps or straightens punctuation is not fabrication."""
    seen = _seen_page(text="He said “clonal overlap” between\n   2   repertoires.")
    chunk = _chunk('He said "clonal overlap" between 2 repertoires.')
    assert verify_evidence_snippets([chunk], seen) == []
    assert chunk["snippet"]


def test_a_search_result_snippet_counts_as_seen_text():
    """Evidence may be quoted from a search hit rather than a fetched page."""
    seen: dict[str, str] = {}
    record_tool_output(
        seen, "web_search", [{"title": "T", "url": URL, "snippet": "ranging from 0 to 1"}]
    )
    assert verify_evidence_snippets([_chunk("ranging from 0 to 1")], seen) == []


def test_trailing_slash_and_case_do_not_cause_a_false_positive():
    seen = _seen_page(url="https://A.Example/Paper/")
    assert verify_evidence_snippets([_chunk(PAGE[:40], url=URL)], seen) == []


def test_an_empty_snippet_is_left_alone():
    """Absent evidence is already handled downstream; do not flag it as fabricated."""
    chunk = _chunk("")
    assert verify_evidence_snippets([chunk], _seen_page()) == []
    assert "snippet_unverified" not in chunk


def test_a_tool_error_string_records_nothing_and_fails_closed():
    """A failed fetch yields a string, not a dict. Nothing was seen, so nothing verifies."""
    seen: dict[str, str] = {}
    record_tool_output(seen, "read_webpage", "tool error: boom")
    assert seen == {}
    chunk = _chunk("anything at all")
    assert verify_evidence_snippets([chunk], seen) == [chunk]
    assert chunk["snippet"] == ""
