"""Regression: the critic fails closed on invalid output (docs/08 §3, docs/11 §1)."""

import time

import pytest

from research_engine import graph as graph_mod
from research_engine.schemas import CriticVerdict


@pytest.mark.asyncio
async def test_critic_fails_closed_on_unparseable_output(monkeypatch):
    # Force the structured call to fail to parse (parsed=None).
    async def fake_structured(role, messages, schema):
        return None, 0.0, 0, 0

    monkeypatch.setattr(graph_mod, "_structured", fake_structured)

    state = {
        "session_id": "s",
        "tasks": [{"id": 1, "query": "q", "status": "running"}],
        "evidence": [{"task_id": 1, "source_url": "https://x", "key_fact": "f", "snippet": "s"}],
        "verdicts": {},
        "retries": {},
        "cost_usd": 0.0,
        "tokens_input": 0,
        "tokens_output": 0,
    }
    out = await graph_mod.critic_node(state)

    verdict = CriticVerdict(**out["verdicts"]["1"])
    assert verdict.passed is False  # fail closed, never default-to-pass
    assert out["retries"]["1"] == 1


@pytest.mark.asyncio
async def test_critic_fails_closed_for_every_task_in_a_parallel_round(monkeypatch):
    """One unparseable verdict must not be allowed to pass its neighbours either."""

    async def fake_structured(role, messages, schema):
        return None, 0.0, 0, 0

    monkeypatch.setattr(graph_mod, "_structured", fake_structured)

    state = {
        "session_id": "s",
        "tasks": [{"id": 1, "query": "a"}, {"id": 2, "query": "b"}, {"id": 3, "query": "c"}],
        "evidence": [],
        "verdicts": {},
        "retries": {},
        "cost_usd": 0.0,
        "tokens_input": 0,
        "tokens_output": 0,
    }
    out = await graph_mod.critic_node(state)

    assert set(out["verdicts"]) == {"1", "2", "3"}
    assert all(not v["passed"] for v in out["verdicts"].values())
    assert out["retries"] == {"1": 1, "2": 1, "3": 1}


def test_confidence_percentage_is_normalized_not_rejected():
    """Regression: a model returning confidence as 0–100 (e.g. Ollama qwen2.5 emitting
    60) must be coerced to a 0–1 probability, not crash the run with a ValidationError.
    """
    assert CriticVerdict(passed=True, confidence=60).confidence == 0.6
    assert CriticVerdict(passed=True, confidence=0.6).confidence == 0.6
    assert CriticVerdict(passed=True, confidence=150).confidence == 1.0  # clamped
    assert CriticVerdict(passed=True, confidence=-5).confidence == 0.0  # clamped
    assert CriticVerdict(passed=True, confidence="high").confidence == 0.5  # neutral default


def test_over_budget_routes_to_failer():
    state = {
        "cost_usd": 999.0,
        "tokens_input": 0,
        "started_at": 0.0,
        "tasks": [{"id": 1}],
        "verdicts": {"1": {"passed": True}},
        "retries": {},
    }
    assert graph_mod.route_after_critic(state) == "failer"


def test_routing_retries_only_while_a_task_has_retries_left():
    """A task that keeps failing eventually stops the loop instead of spinning."""
    base = {
        "cost_usd": 0.0,
        "tokens_input": 0,
        "started_at": time.time(),
        "tasks": [{"id": 1}, {"id": 2}],
        "verdicts": {"1": {"passed": True}, "2": {"passed": False}},
    }

    # Task 2 failed once — max_critic_loops defaults to 2, so it gets another round.
    assert graph_mod.route_after_critic({**base, "retries": {"2": 1}}) == "executor"

    # Out of retries: the run moves to contradiction detection, then synthesis, with
    # whatever task 2 managed to gather.
    assert graph_mod.route_after_critic({**base, "retries": {"2": 2}}) == "contradiction_detector"


def test_routing_detects_then_synthesizes_when_every_task_passed():
    state = {
        "cost_usd": 0.0,
        "tokens_input": 0,
        "started_at": time.time(),
        "tasks": [{"id": 1}, {"id": 2}],
        "verdicts": {"1": {"passed": True}, "2": {"passed": True}},
        "retries": {},
    }
    assert graph_mod.route_after_critic(state) == "contradiction_detector"
