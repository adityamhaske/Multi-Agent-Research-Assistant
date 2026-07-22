"""Regression: the critic fails closed on invalid output (docs/08 §3, docs/11 §1)."""

import pytest

from app.agent import graph as graph_mod
from app.agent.schemas import CriticVerdict


@pytest.mark.asyncio
async def test_critic_fails_closed_on_unparseable_output(monkeypatch):
    # Force the structured call to fail to parse (parsed=None).
    async def fake_structured(role, messages, schema):
        return None, 0.0, 0, 0

    monkeypatch.setattr(graph_mod, "_structured", fake_structured)

    state = {
        "session_id": "s",
        "tasks": [{"id": 1, "query": "q", "status": "running"}],
        "current_task_index": 0,
        "evidence": [{"task_id": 1, "source_url": "https://x", "key_fact": "f", "snippet": "s"}],
        "critic_retries": 0,
        "cost_usd": 0.0,
        "tokens_input": 0,
        "tokens_output": 0,
    }
    out = await graph_mod.critic_node(state)
    verdict = CriticVerdict(**out["critic_verdict"])
    assert verdict.passed is False  # fail closed, never default-to-pass
    assert out["critic_retries"] == 1


def test_over_budget_routes_to_failer():
    state = {
        "cost_usd": 999.0,
        "tokens_input": 0,
        "started_at": 0.0,
        "critic_verdict": {"passed": True},
        "current_task_index": 0,
        "tasks": [{"id": 1}],
    }
    assert graph_mod.route_after_critic(state) == "failer"
