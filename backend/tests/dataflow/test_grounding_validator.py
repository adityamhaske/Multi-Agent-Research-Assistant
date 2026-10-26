"""
The claim-level grounding validator (internal/rfcs/V3.1-corpus-scope.md §9; AC-28–AC-40).

Real validator code throughout. The model is a deterministic *competent* judge — it splits
compound sentences, and rules a claim supported only when its words are in the snippets —
so what these tests prove is the validator's own logic: unit parsing, the structural checks
on a decomposition, citation validation, the quantity rules, accounting, and the unmeasured
causes. None of those is stubbed. Whether a real model judges well is a separate question,
measured by the grounding benchmark (§17), not here.
"""

from __future__ import annotations

import re

import pytest
from langchain_core.messages import AIMessage

from research_engine import grounding, prompts
from research_engine.runconfig import RunConfig, reset_run_config, set_run_config

_STOP = {"the", "and", "with", "that", "this", "from", "were", "was", "are", "for", "into", "per"}


def _words(text: str) -> set[str]:
    text = re.sub(r"\[\d+(?:\s*,\s*\d+)*\]", " ", text.lower())
    return {w for w in re.findall(r"[a-z]+", text) if len(w) >= 4 and w not in _STOP}


class Judge:
    """A competent scripted model. `fail` makes every call raise; `garble` returns junk."""

    def __init__(self, *, fail: Exception | None = None, garble: bool = False, decompose=None):
        self.fail, self.garble, self.decompose_override = fail, garble, decompose
        self.calls: list[str] = []

    async def ainvoke(self, messages):
        system, human = messages[0].content, messages[1].content
        purpose = next(
            name
            for name, constant in (
                ("decompose", prompts.CLAIM_DECOMPOSE_PROMPT),
                ("verify", prompts.CLAIM_VERIFY_PROMPT),
                ("relevance", prompts.CITATION_RELEVANCE_PROMPT),
                ("inference", prompts.INFERENCE_VERIFY_PROMPT),
            )
            if constant in system
        )
        self.calls.append(purpose)
        if self.fail is not None:
            raise self.fail
        if self.garble:
            return self._msg("I think they are all fine, honestly.")
        return self._msg(getattr(self, purpose)(human))

    @staticmethod
    def _msg(content: str) -> AIMessage:
        return AIMessage(
            content=content,
            usage_metadata={"input_tokens": 100, "output_tokens": 20, "total_tokens": 120},
        )

    def decompose(self, human: str) -> str:
        import json

        items = []
        for number, sentence in re.findall(r"Sentence (\d+): (.*)", human):
            if self.decompose_override is not None:
                items.append({"sentence": int(number), "claims": self.decompose_override(sentence)})
                continue
            cites = sorted(
                {
                    int(p)
                    for m in re.findall(r"\[(\d+(?:\s*,\s*\d+)*)\]", sentence)
                    for p in m.split(",")
                }
            )
            claims, start = [], 0
            for m in list(re.finditer(r" and |; ", sentence)) + [None]:
                end = m.start() if m else len(sentence)
                clause = sentence[start:end]
                claims.append(
                    {
                        "text": clause.strip(),
                        "span": [start, end],
                        "cites": cites,
                        "calculation": None,
                    }
                )
                start = m.end() if m else end
            # A gap left by the separator (" and ") contains no factual token, so the
            # decomposition still covers everything that matters.
            items.append({"sentence": int(number), "claims": claims})
        return json.dumps(items)

    def verify(self, human: str) -> str:
        lines = []
        for n, claim, evidence in re.findall(
            r"Claim (\d+): (.*?)\nEvidence \d+:\n(.*?)(?=\n\nClaim \d+:|\Z)", human, re.S
        ):
            need, have = _words(claim), _words(evidence)
            lines.append(f"Claim {n}: {'SUPPORTED' if need <= have else 'NOT_SUPPORTED'}")
        return "\n".join(lines)

    def relevance(self, human: str) -> str:
        lines = []
        for n, claim, snippet in re.findall(
            r"Pair (\d+): Claim: (.*?)\nSnippet:\n(.*?)(?=\n\nPair \d+:|\Z)", human, re.S
        ):
            need = _words(claim)
            share = len(need & _words(snippet)) / max(1, len(need))
            lines.append(f"Pair {n}: {'YES' if share >= 0.5 else 'NO'}")
        return "\n".join(lines)

    def inference(self, human: str) -> str:
        lines = []
        for n, claim, rest in re.findall(
            r"Claim (\d+): (.*?)\nFindings:\n(.*?)(?=\n\nClaim \d+:|\Z)", human, re.S
        ):
            ok = _words(claim) <= _words(rest)
            lines.append(f"Claim {n}: {'SUPPORTED' if ok else 'NOT_SUPPORTED'}")
        return "\n".join(lines)


@pytest.fixture
def judge(monkeypatch):
    holder = {"judge": Judge()}
    monkeypatch.setattr(grounding, "get_llm", lambda role: holder["judge"])
    monkeypatch.setattr(grounding, "RETRY_BACKOFF_SECONDS", 0)
    token = set_run_config(RunConfig(llm_mode="real"))
    yield holder
    reset_run_config(token)


def _sources(*snippets: str) -> list[dict]:
    return [
        {"index": i, "url": f"corpus://doc-{i}#chars=0-10", "snippets": [s], "snippet": s}
        for i, s in enumerate(snippets, start=1)
    ]


async def _validate(draft: str, sources: list[dict], *, admissible=lambda url: True, budget=None):
    return await grounding.validate(
        draft,
        sources,
        question="How did enrolment change?",
        admissible=admissible,
        budget=budget or grounding.Budget(spent_usd=0.0, tokens_in=0, started_at=None),
    )


def _by_text(result) -> dict[str, grounding.Claim]:
    return {c.text: c for c in result.claims}


# ── AC-28: a compound sentence with one invented clause ───────────────────────────


async def test_a_supported_clause_cannot_carry_an_invented_one(judge):
    result = await _validate(
        "## Findings\nEnrolment rose 12% in 2021 [1] and fell 5% in 2022.\n",
        _sources("Enrolment rose 12% in 2021 across the district."),
    )
    claims = _by_text(result)
    assert claims["Enrolment rose 12% in 2021 [1]"].state == grounding.SUPPORTED
    invented = claims["fell 5% in 2022."]
    assert invented.state == grounding.NOT_SUPPORTED
    assert invented.cause == "number_not_in_snippet"
    assert result.counts()["claims_rejected"] == 1


# ── AC-29, AC-30, AC-31: citations judged one by one ──────────────────────────────


async def test_a_relevant_document_that_does_not_state_the_claim_does_not_support_it(judge):
    result = await _validate(
        "Solar panels convert half of incoming sunlight [1].\n",
        _sources("Solar panels are installed on rooftops across the country."),
    )
    (claim,) = result.claims
    assert claim.state == grounding.NOT_SUPPORTED and claim.cause == "not_supported"


async def test_of_two_citations_the_one_that_supports_nothing_is_dropped(judge):
    result = await _validate(
        "Silicon cells absorb photons [1, 2].\n",
        _sources("Silicon cells absorb photons readily.", "Tidal barrages hold back seawater."),
    )
    (claim,) = result.claims
    assert claim.state == grounding.SUPPORTED
    assert claim.non_supporting_cites == [2]
    assert result.counts()["non_supporting_citations"] == 1


async def test_a_claim_needing_two_sources_together_is_supported_and_keeps_both(judge):
    result = await _validate(
        "Silicon cells absorb photons releasing electrons [1, 2].\n",
        _sources("Silicon cells absorb photons.", "Absorbed photons end up releasing electrons."),
    )
    (claim,) = result.claims
    assert claim.state == grounding.SUPPORTED
    assert claim.non_supporting_cites == []


# ── AC-32: uncited, and citations that resolve to nothing admissible ──────────────


async def test_an_uncited_claim_is_rejected(judge):
    result = await _validate("The market grew strongly over the decade.\n", _sources("x"))
    (claim,) = result.claims
    assert claim.cause == "uncited"


async def test_a_citation_outside_the_selection_is_invalid_not_support(judge):
    result = await _validate(
        "Silicon cells absorb photons [1].\n",
        _sources("Silicon cells absorb photons."),
        admissible=lambda url: False,
    )
    (claim,) = result.claims
    assert claim.invalid_cites == [1] and claim.cause == "uncited"
    assert result.counts()["invalid_citations"] == 1


# ── AC-33, AC-38: where claims hide ───────────────────────────────────────────────


async def test_a_world_fact_in_limitations_and_a_numbered_heading_are_claims(judge):
    draft = (
        "## Growth in 2021\n"
        "Enrolment rose 12% in 2021 [1].\n\n"
        "## What your files don't cover\n"
        "The selected files do not discuss rural districts.\n"
        "Nationally the market grew 40% in 2020.\n"
    )
    result = await _validate(draft, _sources("Enrolment rose 12% in 2021."))
    claims = _by_text(result)
    assert claims["Growth in 2021"].cause == "uncited", "a heading with a number is checked"
    assert claims["Nationally the market grew 40% in 2020."].cause == "uncited"
    assert "The selected files do not discuss rural districts." not in claims, (
        "a statement about the selection is not a claim about the world"
    )


async def test_tables_captions_quotes_and_bullets_are_all_checked(judge):
    draft = (
        "- Enrolment rose 12% in 2021 [1].\n"
        "  - Graduation rose 30% in 2021.\n\n"
        "| District | Change |\n|---|---|\n| North | rose 60% |\n\n"
        "*Figure 1: Spending tripled after 2019.*\n"
        "> The board called it a triumph.\n"
    )
    result = await _validate(draft, _sources("Enrolment rose 12% in 2021."))
    rejected = {c.text for c in result.claims if c.state != grounding.SUPPORTED}
    assert "Graduation rose 30% in 2021." in rejected
    assert any("North" in t for t in rejected), "a table cell is a claim"
    assert any("Spending tripled" in t for t in rejected), "a caption is a claim"
    assert any("triumph" in t for t in rejected), "a block quote is a claim"


async def test_content_no_rule_recognises_is_unmeasured_never_skipped(judge):
    result = await _validate(
        "Enrolment rose 12% in 2021 [1].\n<div>Spending tripled.</div>\n",
        _sources("Enrolment rose 12% in 2021."),
    )
    assert result.unparsed_lines == [2]
    assert result.counts()["unmeasured_by_cause"]["unparsed_content"] == 1


async def test_a_decomposition_that_leaves_a_number_uncovered_is_refused(judge):
    def misses_the_parenthetical(sentence):
        cut = sentence.index("(")
        return [{"text": sentence[:cut], "span": [0, cut], "cites": [1], "calculation": None}]

    judge["judge"] = Judge(decompose=misses_the_parenthetical)
    result = await _validate(
        "Enrolment rose sharply [1] (by 40% in 2019).\n", _sources("Enrolment rose sharply.")
    )
    (claim,) = result.claims
    assert claim.state == grounding.UNMEASURED and claim.cause == "decomposition_invalid"


# ── AC-40: right number, wrong subject ────────────────────────────────────────────


async def test_the_mechanical_check_is_not_treated_as_sufficient(judge):
    result = await _validate("Ohio rose 12% in 2021 [1].\n", _sources("Texas rose 12% in 2021."))
    (claim,) = result.claims
    assert claim.cause == "not_supported", "the number matched; the subject did not"


# ── AC-35: unmeasured, with its cause ─────────────────────────────────────────────


class _ServerError(Exception):
    status_code = 503


class _RateLimited(Exception):
    status_code = 429


@pytest.mark.parametrize(
    ("failure", "cause"),
    [
        (_ServerError("down"), "provider_outage"),
        (_RateLimited("slow"), "rate_limited"),
        (TimeoutError("late"), "timeout"),
    ],
)
async def test_a_checker_that_cannot_run_leaves_claims_unmeasured_with_the_cause(
    judge, failure, cause
):
    judge["judge"] = Judge(fail=failure)
    result = await _validate("Enrolment rose 12% in 2021 [1].\n", _sources("Enrolment rose 12%."))
    (claim,) = result.claims
    assert claim.state == grounding.UNMEASURED and claim.cause == cause
    assert result.counts()["claims_supported"] == 0
    assert result.retries == grounding.MAX_RETRIES, "transient causes are retried, then given up"


async def test_a_malformed_answer_is_unmeasured_not_supported(judge):
    judge["judge"] = Judge(garble=True)
    result = await _validate("Enrolment rose 12% in 2021 [1].\n", _sources("Enrolment rose 12%."))
    (claim,) = result.claims
    assert claim.state == grounding.UNMEASURED and claim.cause == "malformed_response"


async def test_a_crossed_budget_leaves_claims_unmeasured_and_names_the_limit(judge):
    token = set_run_config(RunConfig(llm_mode="real", max_cost_per_session_usd=1.0))
    try:
        budget = grounding.Budget(spent_usd=1.0, tokens_in=0, started_at=None)
        result = await _validate(
            "Enrolment rose 12% in 2021 [1].\n", _sources("Enrolment rose 12%."), budget=budget
        )
        assert budget.breach().startswith("cost ceiling reached during validation")
    finally:
        reset_run_config(token)
    (claim,) = result.claims
    assert claim.cause == "budget_exhausted"
    assert judge["judge"].calls == [], "no model call is made past the limit"


async def test_conclusions_are_checked_against_the_findings(judge):
    draft = (
        "## Findings\nEnrolment rose 12% in 2021 [1].\n\n"
        "## Conclusion\nEnrolment rose because tuition fell [1].\n"
    )
    result = await _validate(draft, _sources("Enrolment rose 12% in 2021."))
    claims = _by_text(result)
    assert claims["Enrolment rose because tuition fell [1]."].cause == "inference_rejected"
    assert "inference" in judge["judge"].calls
