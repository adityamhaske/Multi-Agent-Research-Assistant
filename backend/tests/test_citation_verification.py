"""Regression: citation fidelity is verified before a draft reaches the gate (docs/12 M5).

Two defects in one run (eval-2026-08-12) pinned these:

1. A cited claim the judge marked unsupported (postgres-vs-mysql at 0.5256 support)
   reached the user unchanged. The synthesizer writes from the executor's key_fact, which
   can drift past its verbatim snippet — and the eval judge rules on snippets. So the
   graph now checks every cited claim against the snippets of its own cited sources with
   the SAME ruling method the eval judge uses, and strips the markers from any claim that
   fails — never silently editing a claim into appearing uncited.

2. Eight of ten queries died with "planner: could not produce a valid task list" while
   the real cause was a 429 RESOURCE_EXHAUSTED on the provider key. `with_structured_output`
   RAISES on provider errors, `_structured` swallowed the exception, and the planner read
   the None as an unparseable plan. Provider/API errors must surface with the provider's
   own message, and a quota exhaustion must not burn a pointless retry.
"""

import pytest

from research_engine import graph as graph_mod
from research_engine.schemas import PlannerOutput

SOURCES = [
    {
        "index": 1,
        "url": "https://a",
        "title": "A",
        "snippet": "Solar grew 50%",
        "snippets": ["Solar grew 50%"],
    },
    {
        "index": 2,
        "url": "https://b",
        "title": "B",
        "snippet": "Wind was flat",
        "snippets": ["Wind was flat"],
    },
]

DRAFT = (
    "# Report\n\n## Key Findings\n"
    "Solar grew 50% [1]. Batteries doubled in capacity [2].\n\n"
    "## Sources\n[1] https://a\n[2] https://b\n"
)


@pytest.mark.asyncio
async def test_unsupported_claim_loses_its_citation(monkeypatch):
    """A claim its cited snippets do not support must not keep citing them."""

    async def verdicts(claim_evidence):
        # Second claim is judged NO by the verifier, exactly as the eval judge would.
        return [True, False], 0.0, 0, 0

    monkeypatch.setattr(graph_mod, "_verifier_verdicts", verdicts)

    result, cost, i, o = await graph_mod._verify_citation_fidelity("s", DRAFT, SOURCES)

    assert "Solar grew 50% [1]." in result  # supported claim untouched
    assert "Batteries doubled in capacity [2]" not in result.replace(" [2]", "")
    assert "[2]" not in result.split("## Sources")[0], "stripped from the body"
    assert "(citation could not be verified)" in result
    assert cost == 0.0 and i == 0 and o == 0  # fake-mode verdicts cost nothing


@pytest.mark.asyncio
async def test_supported_claims_pass_through_unchanged(monkeypatch):
    async def verdicts(claim_evidence):
        assert len(claim_evidence) == 2
        # Every claim is shown the snippets of ITS OWN cited sources only.
        assert "Solar grew 50%" in claim_evidence[0][1]
        assert "Wind was flat" in claim_evidence[1][1]
        return [True, True], 0.0, 0, 0

    monkeypatch.setattr(graph_mod, "_verifier_verdicts", verdicts)

    result, *_ = await graph_mod._verify_citation_fidelity("s", DRAFT, SOURCES)
    assert result == DRAFT


@pytest.mark.asyncio
async def test_verifier_failure_never_strips_citations(monkeypatch):
    """Fail closed for the USER: a verifier error keeps every citation in place
    (the ⚠ chip and the eval judge then rule on them), never silently drops them."""

    async def verdicts(claim_evidence):
        raise RuntimeError("verifier unreachable")

    monkeypatch.setattr(graph_mod, "_verifier_verdicts", verdicts)

    result, *_ = await graph_mod._verify_citation_fidelity("s", DRAFT, SOURCES)
    assert result == DRAFT


@pytest.mark.asyncio
async def test_planner_reports_provider_errors_not_parse_failures(monkeypatch):
    """A 429 from the provider must read as a provider error, not 'invalid task list'."""

    async def raising(role, messages, schema):
        raise RuntimeError(
            "429 RESOURCE_EXHAUSTED. Your project has exceeded its monthly spending cap."
        )

    monkeypatch.setattr(graph_mod, "_structured", raising)

    out = await graph_mod.planner_node(
        {
            "session_id": "s",
            "original_query": "q",
            "cost_usd": 0.0,
            "tokens_input": 0,
            "tokens_output": 0,
        }
    )
    assert out["error"].startswith("planner: provider error")
    assert "spending cap" in out["error"]


@pytest.mark.asyncio
async def test_planner_does_not_retry_a_dead_quota(monkeypatch):
    """Retrying an exhausted monthly cap burns nothing but time — one call only."""
    calls = 0

    async def raising(role, messages, schema):
        nonlocal calls
        calls += 1
        raise RuntimeError(
            "429 RESOURCE_EXHAUSTED. Your project has exceeded its monthly spending cap."
        )

    monkeypatch.setattr(graph_mod, "_structured", raising)

    await graph_mod.planner_node(
        {
            "session_id": "s",
            "original_query": "q",
            "cost_usd": 0.0,
            "tokens_input": 0,
            "tokens_output": 0,
        }
    )
    assert calls == 1


@pytest.mark.asyncio
async def test_planner_still_retries_a_plain_parse_failure(monkeypatch):
    """Unparseable-but-cheap failures keep their one retry (unchanged behaviour)."""
    calls = 0

    async def none_twice(role, messages, schema):
        nonlocal calls
        calls += 1
        return None, 0.0, 0, 0

    monkeypatch.setattr(graph_mod, "_structured", none_twice)

    out = await graph_mod.planner_node(
        {
            "session_id": "s",
            "original_query": "q",
            "cost_usd": 0.0,
            "tokens_input": 0,
            "tokens_output": 0,
        }
    )
    assert calls == 2
    assert out["error"] == "planner: could not produce a valid task list"


@pytest.mark.asyncio
async def test_number_absent_from_snippets_is_stripped_without_asking_the_model(monkeypatch):
    """A figure the cited snippets do not contain can never be supported — strip it
    deterministically, without consulting the (local 7B) verifier at all. Measured:
    the verifier rubber-stamped invented figures the judge then ruled NO on."""

    async def verdicts(claim_evidence):
        # The invented-number claim must never reach the model.
        assert all("99%" not in c for c, _ in claim_evidence)
        return [True] * len(claim_evidence), 0.0, 0, 0

    monkeypatch.setattr(graph_mod, "_verifier_verdicts", verdicts)

    draft = (
        "Solar grew 50% [1]. Adoption reached 99% of households last year [1].\n"
        "## Sources\n[1] https://a\n"
    )
    sources = [
        {
            "index": 1,
            "url": "https://a",
            "title": "A",
            "snippet": "Solar grew 50%",
            "snippets": ["Solar grew 50%"],
        },
    ]
    result, *_ = await graph_mod._verify_citation_fidelity("s", draft, sources)
    assert "Solar grew 50% [1]." in result
    stripped_claim = result.split("Adoption")[1].split("\n")[0]
    assert "[1]" not in stripped_claim.split("*(")[0]
    assert "(citation could not be verified)" in stripped_claim


def test_short_number_is_not_grounded_by_a_longer_one():
    """'5' must not be backed by '50%' — word-bounded matching only."""
    assert graph_mod._numbers_grounded("grew 5% [1].", "- Solar grew 50%") is False
    assert graph_mod._numbers_grounded("grew 50% [1].", "- Solar grew 50%") is True


@pytest.mark.asyncio
async def test_deictic_cited_sentence_is_stripped_deterministically(monkeypatch):
    """'This is detailed in Article 55 [4].' is judged by the harness as a STANDALONE
    claim, where the anaphor has no referent and reads unsupported. Strip the marker
    no matter what the verifier says; the prompt forbids the construction upstream."""

    async def verdicts(claim_evidence):
        return [True] * len(claim_evidence), 0.0, 0, 0

    monkeypatch.setattr(graph_mod, "_verifier_verdicts", verdicts)

    draft = (
        "Providers must document serious incidents under the AI Act [1]. "
        "This is detailed in Article 55 of the AI Act [1].\n## Sources\n[1] https://a\n"
    )
    sources = [
        {
            "index": 1,
            "url": "https://a",
            "title": "A",
            "snippet": "Providers must assess risks and report serious incidents (Article 55 AI Act).",
            "snippets": [
                "Providers must assess risks and report serious incidents (Article 55 AI Act)."
            ],
        },
    ]
    result, *_ = await graph_mod._verify_citation_fidelity("s", draft, sources)
    body = result.split("## Sources")[0]
    # The note ends with a terminator so the judge's sentence split never merges it
    # into the NEXT sentence (measured corrupting a supported claim in run #3).
    assert (
        "This is detailed in Article 55 of the AI Act *(citation could not be verified)*." in body
    )
    assert "document serious incidents under the AI Act [1]." in body


@pytest.mark.asyncio
async def test_bold_labelled_sentence_is_stripped_deterministically(monkeypatch):
    """'**Label**: fact [n].' is judged as a whole, label included — and no snippet
    contains the label, so the sentence as written always exceeds its evidence."""

    async def verdicts(claim_evidence):
        return [True] * len(claim_evidence), 0.0, 0, 0

    monkeypatch.setattr(graph_mod, "_verifier_verdicts", verdicts)

    draft = (
        "**Cost**: Prices fell sharply across the sector [1].\n"
        "Solar grew 50% [1].\n## Sources\n[1] https://a\n"
    )
    sources = [
        {
            "index": 1,
            "url": "https://a",
            "title": "A",
            "snippet": "Solar grew 50%",
            "snippets": ["Solar grew 50%"],
        },
    ]
    result, *_ = await graph_mod._verify_citation_fidelity("s", draft, sources)
    body = result.split("## Sources")[0]
    assert (
        "**Cost**: Prices fell sharply across the sector *(citation could not be verified)*."
        in body
    )
    assert "Solar grew 50% [1]." in body


def test_claim_split_matches_the_eval_judge():
    """The verifier must rule on the same claims the eval judge does: abbreviation tails
    ("Dr. Smith", "e.g.") must not split, and a lowercase continuation is not a new
    sentence. A split mismatch made the verifier approve fragments the judge then ruled
    on as one merged claim (measured on the first Ollama run, docs/12 M5)."""
    draft = (
        "Solar grew per Dr. Smith [1]. Wind output fell 3% after the freeze "
        "[2]. e.g. capacity factors dropped that year [1].\n"
    )
    claims = graph_mod._cited_claims(draft)
    assert claims == [
        "Solar grew per Dr. Smith [1].",
        "Wind output fell 3% after the freeze [2]. e.g. capacity factors dropped that year [1].",
    ]


def test_planner_output_schema_still_valid():
    """Sanity: the schema the planner is judged against is unchanged."""
    parsed = PlannerOutput.model_validate(
        {"tasks": [{"id": 1, "query": "one"}, {"id": 2, "query": "two"}]}
    )
    assert len(parsed.tasks) == 2
