"""
What checking a selected-files report does when a run limit or a provider gives out (AC-43).

internal/rfcs/V3.1-corpus-scope.md §9.9. `test_grounding_repair` pins the pre-flight cost
refusal and the separate cost record. This pins what happens once checking has started:
- a cost limit crossed between the calls of one paragraph;
- a cost limit crossed during a repair;
- the input-token limit on a route with no price;
- a 429 retried until the retries run out.

Each must end unmeasured with its cause named, and never with validated text the gate
would accept.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage

from research_engine import grounding, grounding_repair, llm_factory
from research_engine.runconfig import RunConfig, reset_run_config, set_run_config
from tests.dataflow.test_grounding_repair import RepairingJudge, _ground
from tests.dataflow.test_grounding_validator import _sources

#: The first sentence is supported and the second is not, so checking it takes several
#: calls (decompose, verify, relevance) and then a repair.
DRAFT = "## Findings\nEnrolment rose 12% in 2021 [1]. Enrolment fell 5% in 2022 [1].\n"
SNIPPET = "Enrolment rose 12% in 2021 across the district."


@pytest.fixture
def judge(monkeypatch):
    """The competent repairing judge from `test_grounding_repair`, on real-mode checking."""
    holder = {"judge": RepairingJudge()}
    monkeypatch.setattr(grounding, "get_llm", lambda role: holder["judge"])
    monkeypatch.setattr(grounding, "RETRY_BACKOFF_SECONDS", 0)
    token = set_run_config(RunConfig(llm_mode="real"))
    yield holder
    reset_run_config(token)


def _cost_per_call(monkeypatch, cost) -> None:
    """Price each validation call with `cost(judge_calls)`, and skip the pre-flight estimate
    so the limit is met during checking rather than refused before it."""
    monkeypatch.setattr(grounding, "_estimate", lambda sentences: 0.0)
    monkeypatch.setattr(grounding, "estimate_cost", cost)


def _assert_unmeasured_by_budget(result) -> None:
    assert result.report["status"] == "unmeasured"
    assert result.failure.startswith("grounding_unmeasured: budget_exhausted"), result.failure
    assert "ceiling reached" in result.failure, "the breach is named, with its numbers"
    assert result.report["validated_text_sha256"] is None, "nothing the gate would accept"


async def test_a_cost_limit_crossed_mid_paragraph_stops_checking_there(judge, monkeypatch):
    # $0.60 a call against a $1.00 limit: the second call crosses it, before verification
    # of the paragraph is finished and before any repair is asked for.
    _cost_per_call(monkeypatch, lambda response, role: 0.6)
    token = set_run_config(RunConfig(llm_mode="real", max_cost_per_session_usd=1.0))
    try:
        result = await _ground(DRAFT, _sources(SNIPPET))
    finally:
        reset_run_config(token)

    _assert_unmeasured_by_budget(result)
    assert "repair" not in judge["judge"].calls
    assert len(judge["judge"].calls) == 2, "no call was made past the limit"


async def test_a_cost_limit_crossed_during_a_repair_names_the_cause(judge, monkeypatch):
    # $0.40 a call: the three checking calls fit under $1.00 (the third starts at $0.80) and
    # leave $1.20 spent, so the call the repair asks for is the one refused.
    _cost_per_call(monkeypatch, lambda response, role: 0.4)
    entered = []
    real_rewrite = grounding_repair._rewrite

    async def recording_rewrite(*args, **kwargs):
        entered.append(True)
        return await real_rewrite(*args, **kwargs)

    monkeypatch.setattr(grounding_repair, "_rewrite", recording_rewrite)
    token = set_run_config(RunConfig(llm_mode="real", max_cost_per_session_usd=1.0))
    try:
        result = await _ground(DRAFT, _sources(SNIPPET))
    finally:
        reset_run_config(token)

    assert entered, "the limit was met inside the repair, not during checking"
    assert "repair" not in judge["judge"].calls, "the repair's own call was refused"
    _assert_unmeasured_by_budget(result)


class _HeavyJudge(RepairingJudge):
    """Reports 3,000 input tokens a call, as a long snippet batch would."""

    @staticmethod
    def _msg(content):
        return AIMessage(
            content=content,
            usage_metadata={"input_tokens": 3_000, "output_tokens": 20, "total_tokens": 3_020},
        )


async def test_an_unpriced_route_is_held_by_its_token_limit(judge, monkeypatch):
    """On an unpriced route every call costs $0.00, so a cost limit can never trip there
    (AGENTS.md: MAX_COST_PER_SESSION_USD is a no-op on such routes). The token limit must."""
    _cost_per_call(monkeypatch, lambda response, role: 0.0)
    judge["judge"] = _HeavyJudge()
    # Pre-flight estimates 4,500 tokens for this draft, so a 5,000 limit lets checking
    # start; two 3,000-token calls then cross it.
    token = set_run_config(
        RunConfig(llm_mode="real", max_cost_per_session_usd=1.0, max_input_tokens=5_000)
    )
    try:
        result = await _ground(DRAFT, _sources(SNIPPET))
    finally:
        reset_run_config(token)

    assert result.cost_usd == 0.0, "nothing was priced, so only the token limit could stop it"
    _assert_unmeasured_by_budget(result)
    assert "input-token ceiling reached during validation: 6,000 of 5,000" in result.failure
    assert len(judge["judge"].calls) == 2


async def test_a_token_limit_too_small_for_the_check_is_refused_before_spending(judge, monkeypatch):
    _cost_per_call(monkeypatch, lambda response, role: 0.0)
    token = set_run_config(RunConfig(llm_mode="real", max_input_tokens=1_000))
    try:
        result = await _ground(DRAFT, _sources(SNIPPET))
    finally:
        reset_run_config(token)

    assert result.failure.startswith("budget_insufficient")
    assert "input tokens" in result.failure
    assert judge["judge"].calls == [], "nothing was spent on a check that could not finish"


async def test_a_429_retried_until_exhausted_is_rate_limited_not_unsupported(judge):
    class _RateLimited(Exception):
        status_code = 429

    judge["judge"] = RepairingJudge(fail=_RateLimited("slow down"))
    result = await _ground(DRAFT, _sources(SNIPPET))

    assert result.report["status"] == "unmeasured"
    assert result.failure == "grounding_unmeasured: rate_limited", result.failure
    assert result.report["validated_text_sha256"] is None
    # The first attempt plus MAX_RETRIES of the first call, and then it stopped.
    assert len(judge["judge"].calls) == 1 + grounding.MAX_RETRIES
    assert result.report["validation_cost"]["retries"] == grounding.MAX_RETRIES


def test_an_unpriced_model_costs_nothing_per_call():
    """The premise of the token-limit case: `estimate_cost` returns 0.0 for a route the
    catalog does not price, and `validate_pricing` lets such routes through."""
    response = SimpleNamespace(usage_metadata={"input_tokens": 1_000, "output_tokens": 1_000})
    routing = {**RunConfig().models, "critic": "custom:any/model"}
    token = set_run_config(RunConfig(llm_mode="real", models=routing))
    try:
        assert llm_factory.estimate_cost(response, "critic") == 0.0
    finally:
        reset_run_config(token)
