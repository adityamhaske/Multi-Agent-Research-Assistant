"""
User preferences and their RunConfig wiring (docs/07 §2, Phase 3).

Every preference defaults to today's behaviour — these tests pin that, plus the three
concrete knobs this phase actually wires into the engine: retrieval_k (web_search's
default result count), min_sources_per_task (a critic-side floor, 0 = none today), and
snippet_max_chars (a pre-validation truncation, never looser than the schema's own cap).
"""

from __future__ import annotations

import pytest

from app.schemas.auth import UserPreferences
from app.workers.pipeline_runner import _preference_overrides
from research_engine.runconfig import RunConfig


def test_runconfig_defaults_reproduce_todays_behaviour():
    cfg = RunConfig()
    assert cfg.retrieval_k == 5  # web_search's old hardcoded default
    assert cfg.min_sources_per_task == 0  # no floor today
    assert cfg.snippet_max_chars == 500  # EvidenceChunk.snippet's existing max_length
    assert cfg.outline_template is None
    assert cfg.topic_seeds == ()
    assert cfg.prompt_overrides == {}


def test_preference_overrides_only_include_set_fields():
    class _FakeUser:
        preferences = {
            "retrieval_k": 8,
            "tavily_api_key": "tvly-test",
            "brave_api_key": "BSA-test",
        }

    assert _preference_overrides(_FakeUser()) == {
        "retrieval_k": 8,
        "tavily_api_key": "tvly-test",
        "brave_api_key": "BSA-test",
    }


def test_preference_overrides_empty_for_a_user_with_none_set():
    class _FakeUser:
        preferences = None

    assert _preference_overrides(_FakeUser()) == {}


def test_preference_overrides_empty_for_no_user():
    assert _preference_overrides(None) == {}


def test_user_preferences_rejects_out_of_range_values():
    with pytest.raises(ValueError):
        UserPreferences(retrieval_k=0)  # ge=1
    with pytest.raises(ValueError):
        UserPreferences(snippet_max_chars=999)  # le=500, the schema's own ceiling


@pytest.mark.asyncio
async def test_web_search_falls_back_to_the_configured_retrieval_k(monkeypatch):
    from research_engine import tools
    from research_engine.runconfig import reset_run_config, set_run_config

    seen = {}

    async def fake_search(query, max_results):
        seen["max_results"] = max_results
        return []

    monkeypatch.setattr(tools, "search", fake_search)
    token = set_run_config(RunConfig(retrieval_k=9))
    try:
        await tools.web_search.ainvoke({"query": "q"})
    finally:
        reset_run_config(token)

    assert seen["max_results"] == 9


@pytest.mark.asyncio
async def test_web_search_honors_an_explicit_count_over_the_configured_default(monkeypatch):
    from research_engine import tools

    seen = {}

    async def fake_search(query, max_results):
        seen["max_results"] = max_results
        return []

    monkeypatch.setattr(tools, "search", fake_search)
    await tools.web_search.ainvoke({"query": "q", "max_results": 2})

    assert seen["max_results"] == 2


@pytest.mark.asyncio
async def test_critic_fails_closed_below_the_configured_source_floor():
    from research_engine import graph as graph_mod
    from research_engine.runconfig import reset_run_config, set_run_config

    token = set_run_config(RunConfig(min_sources_per_task=3))
    try:
        key, verdict, cost, i, o = await graph_mod._criticize_one(
            {
                "evidence": [
                    {"task_id": 1, "source_url": "https://a", "snippet": "s"},
                ]
            },
            {"id": 1, "query": "q"},
        )
    finally:
        reset_run_config(token)

    assert verdict.passed is False
    assert "3 required" in verdict.reasons[0]
    assert cost == 0.0  # failed before any model call


@pytest.mark.asyncio
async def test_critic_does_not_gate_on_source_count_when_the_floor_is_zero(monkeypatch):
    """0 = no floor (today's behaviour) — the model still gets to grade thin evidence."""
    from research_engine import graph as graph_mod
    from research_engine.schemas import CriticVerdict

    async def fake_structured(role, messages, schema):
        return CriticVerdict(passed=True, confidence=0.9), 0.01, 5, 5

    monkeypatch.setattr(graph_mod, "_structured", fake_structured)

    key, verdict, cost, i, o = await graph_mod._criticize_one(
        {"evidence": []}, {"id": 1, "query": "q"}
    )

    assert verdict.passed is True
    assert cost == 0.01  # the model was actually called
