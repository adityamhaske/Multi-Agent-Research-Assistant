"""
Every snippet from a source is retained (docs/12 M5, defect D3).

Found while investigating why the real-model citation-support rate sat at 0.41. The
synthesizer kept only the *first* snippet per URL, but one page routinely backs several
distinct facts and the same source is cited for ~8 different claims per report — so a
citation chip could display verbatim text that had nothing to do with the sentence it was
attached to, and the eval's judge was scoring that retention bug rather than the model's
citation quality.

This is the product's central promise: hover a citation, read the text that backs *this*
claim. These tests pin it.
"""

from __future__ import annotations

import pytest

from app.schemas.research import SourceSchema
from research_engine.graph import synthesizer_node
from research_engine.schemas import Source


def _evidence(url: str, snippet: str, title: str = "T") -> dict:
    return {"source_url": url, "source_title": title, "snippet": snippet, "key_fact": "k"}


async def _sources_for(evidence: list[dict]) -> list[dict]:
    state = {
        "session_id": "s",
        "original_query": "q",
        "evidence": evidence,
        "cost_usd": 0.0,
        "tokens_input": 0,
        "tokens_output": 0,
    }
    return (await synthesizer_node(state))["sources"]


@pytest.mark.asyncio
async def test_every_distinct_snippet_from_one_source_is_kept():
    """The regression: the second and third facts from a page used to be discarded."""
    sources = await _sources_for(
        [
            _evidence("https://a.com", "Postgres won DBMS of the Year five times."),
            _evidence("https://a.com", "JSONB uses a decomposed binary format with GIN."),
            _evidence("https://a.com", "MVCC means readers never block writers."),
        ]
    )

    assert len(sources) == 1, "one URL is still one numbered source"
    assert len(sources[0]["snippets"]) == 3
    assert "JSONB" in sources[0]["snippets"][1]
    assert "MVCC" in sources[0]["snippets"][2]


@pytest.mark.asyncio
async def test_first_snippet_is_still_exposed_for_backward_compatibility():
    sources = await _sources_for(
        [
            _evidence("https://a.com", "First fact."),
            _evidence("https://a.com", "Second fact."),
        ]
    )

    assert sources[0]["snippet"] == "First fact."
    assert sources[0]["snippets"][0] == "First fact."


@pytest.mark.asyncio
async def test_duplicate_snippets_are_not_repeated():
    sources = await _sources_for(
        [
            _evidence("https://a.com", "The same quote."),
            _evidence("https://a.com", "The same quote."),
        ]
    )
    assert sources[0]["snippets"] == ["The same quote."]


@pytest.mark.asyncio
async def test_distinct_urls_stay_distinct_numbered_sources():
    sources = await _sources_for(
        [
            _evidence("https://a.com", "Fact A"),
            _evidence("https://b.com", "Fact B"),
        ]
    )
    assert [s["index"] for s in sources] == [1, 2]
    assert sources[0]["snippets"] == ["Fact A"]
    assert sources[1]["snippets"] == ["Fact B"]


@pytest.mark.asyncio
async def test_evidence_without_a_snippet_does_not_create_an_empty_quote():
    """An empty snippet must not render as an empty quotation in the UI."""
    sources = await _sources_for(
        [
            _evidence("https://a.com", ""),
            _evidence("https://a.com", "A real quote."),
        ]
    )

    assert sources[0]["snippets"] == ["A real quote."]
    assert sources[0]["snippet"] == "A real quote."


@pytest.mark.asyncio
async def test_evidence_without_a_url_is_skipped():
    sources = await _sources_for([_evidence("", "orphan"), _evidence("https://a.com", "kept")])
    assert len(sources) == 1
    assert sources[0]["url"] == "https://a.com"


def test_source_schema_defaults_to_an_empty_snippet_list():
    """Old `sessions.sources` rows carry no `snippets` key and must still validate.

    NOTE the name is misleading and was load-bearing in a real defect: this constructs the
    *engine* `Source`, not the API's `SourceSchema`. See the two tests below.
    """
    legacy = Source(index=1, url="https://a.com", title="A", snippet="only one")
    assert legacy.snippets == []


def test_api_source_schema_carries_every_field_the_engine_produces():
    """The drift that silently undid M5 defect D3 on both hosts.

    `SourceSchema` is the API's copy of `Source` and is what `SessionDetail.sources` is
    typed as — on the server *and* in the desktop sidecar. It omitted `snippets`, so
    Pydantic filtered the field out en route to a browser that reads it
    (`frontend/lib/citations.tsx:141`), and every citation hovercard fell back to one
    quote for the ~8 claims that cite a page. The fix was shipped, tested, and
    documented; only this copy never got it.

    Compare field *sets* rather than naming one field, so the next field added to the
    engine model cannot be silently dropped here either.
    """
    missing = set(Source.model_fields) - set(SourceSchema.model_fields)
    assert not missing, (
        f"SourceSchema is missing {sorted(missing)}: the API would drop these on the way "
        f"to the browser (AGENTS.md — two hosts, one contract)"
    )


def test_api_source_schema_round_trips_every_snippet():
    source = Source(
        index=1,
        url="https://a.com",
        title="A",
        snippet="first",
        snippets=["first", "second", "third"],
    )
    assert SourceSchema.model_validate(source.model_dump()).snippets == [
        "first",
        "second",
        "third",
    ]
