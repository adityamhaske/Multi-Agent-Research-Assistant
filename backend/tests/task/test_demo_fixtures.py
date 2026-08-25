"""The seeded demo must demonstrate the product's claim, not merely gesture at it.

The desktop app opens on a demo session before any key exists (docs/17 §6.1), so this
report is the first — and for some users the only — evidence they see that citations
here resolve to something real. It previously reused `fakes.py`, the *test* fixtures:
"A citable fact [1]" citing "Fixture Source 1" at example.com. That reads as broken
software, and it stakes the product's headline claim on placeholder data.

These tests hold the demo to the same bar the product holds a real report to.
"""

from __future__ import annotations

import re

from research_engine import demo_fixtures
from research_engine.graph import _cited_claims, _numbers_grounded


def _sources_by_index() -> dict[int, dict]:
    return {s["index"]: s for s in demo_fixtures.DEMO_SOURCES}


def test_every_demo_claim_is_grounded_in_the_snippets_it_cites():
    """Each cited claim must pass the SAME grounding check the graph applies to a real
    draft (`_numbers_grounded`). A demo that fails its own verifier would render the
    unverified note on first launch — the exact failure this seed exists to disprove."""
    by_index = _sources_by_index()

    claims = _cited_claims(demo_fixtures.DEMO_REPORT)
    assert claims, "the demo report has no cited claims to verify"

    for claim in claims:
        cited = {int(n) for n in re.findall(r"\[(\d+)\]", claim)}
        assert cited, f"claim carries no citation marker: {claim!r}"
        assert cited <= set(by_index), f"claim cites a source that does not exist: {claim!r}"
        snippets = " ".join(by_index[i]["snippet"] for i in sorted(cited))
        assert _numbers_grounded(claim, snippets), (
            f"claim has a number absent from its cited snippets: {claim!r}"
        )


def test_demo_sources_are_real_and_carry_verbatim_snippets():
    """Placeholder domains are what made the old demo look fake. A snippet is presented
    to the user as verbatim supporting evidence, so an empty or invented one would be a
    fabricated citation wearing a real URL."""
    assert demo_fixtures.DEMO_SOURCES, "the demo has no sources"

    for source in demo_fixtures.DEMO_SOURCES:
        url, title, snippet = source["url"], source["title"], source["snippet"]
        assert url.startswith("https://"), url
        assert "example.com" not in url and "example.org" not in url, url
        assert "fixture" not in title.lower(), title
        assert len(snippet.strip()) >= 40, f"snippet too thin to support a claim: {title}"


def test_a_demo_run_gets_demo_content_and_a_test_run_still_gets_fixtures():
    """`demo` selects the content; `llm_mode` stays "fake" so every no-network guard in
    the engine keeps firing. Selecting demo content via a new `llm_mode` value would
    fail open — any comparison left as `== "fake"` would send a demo run to a real
    provider. This way the worst case is ugly filler, never a surprise API call."""
    from langchain_core.messages import HumanMessage, SystemMessage

    from research_engine.llm_factory import get_llm
    from research_engine.runconfig import RunConfig, reset_run_config, set_run_config

    messages = [
        SystemMessage(content="You are the Research Synthesizer. Write the report."),
        HumanMessage(content=demo_fixtures.DEMO_QUERY),
    ]

    token = set_run_config(RunConfig(llm_mode="fake", demo=True))
    try:
        demo_out = get_llm("synthesizer").invoke(messages).content
    finally:
        reset_run_config(token)

    token = set_run_config(RunConfig(llm_mode="fake"))
    try:
        test_out = get_llm("synthesizer").invoke(messages).content
    finally:
        reset_run_config(token)

    assert "arxiv.org/abs/2005.11401" in demo_out
    assert "Fixture" not in demo_out
    # The test fixtures must be untouched — 300+ tests assert on their exact output.
    assert "Fixture Report" in test_out


def test_a_demo_search_returns_the_real_sources():
    """The demo's retriever must hand back the same real URLs its report cites, so the
    evidence a user inspects matches the bibliography they were shown."""
    import asyncio

    from research_engine import retrievers
    from research_engine.runconfig import RunConfig, reset_run_config, set_run_config

    token = set_run_config(RunConfig(llm_mode="fake", demo=True))
    try:
        results = asyncio.run(retrievers.search("anything", max_results=2))
    finally:
        reset_run_config(token)

    assert [r["url"] for r in results] == [s["url"] for s in demo_fixtures.DEMO_SOURCES]


def test_demo_report_never_reads_as_a_test_fixture():
    """The report is shown to a stranger as the product's own output. Test-fixture
    vocabulary in it is a tell that the demo was never written for them."""
    lowered = demo_fixtures.DEMO_REPORT.lower()
    for tell in ("fixture", "lorem", "deterministic summary", "a citable fact"):
        assert tell not in lowered, f"demo report still reads as a test fixture: {tell!r}"
