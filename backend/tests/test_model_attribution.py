"""
Truthful per-agent model attribution (docs/07 §2, researcher-workspace-overhaul plan
Phase 1, requirement 1).

`session.model_routing` was already resolved and snapshotted before this phase
(`app/workers/pipeline_runner.py::_run_config_for`) — it was simply never surfaced:
never emitted into the live activity log, never declared on the API response model
that reaches the browser, and never persisted at all on the desktop host. These tests
pin all three, plus the "unmeasured, not zero" trap: a session with no persisted
routing must render as unresolved, never as a guessed default.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from langchain_core.messages import AIMessage

from app.schemas.research import SessionDetail
from research_engine import events as ev
from research_engine.graph import build_graph, critic_node, synthesizer_node
from research_engine.llm_factory import served_model_id
from research_engine.runconfig import RunConfig, reset_run_config, set_run_config
from research_engine.runner import initial_state

# A routing that differs per role — the only way to prove "renders per role" rather
# than one constant string copy-pasted under every agent's name.
_DISTINCT_ROUTING = {
    "planner": "anthropic:claude-opus-5",
    "executor": "google:gemini-2.5-flash",
    "critic": "openai:gpt-5",
    "synthesizer": "anthropic:claude-sonnet-5",
    "chat": "google:gemini-2.5-flash",
}


def _config():
    return {"configurable": {"thread_id": "test-session"}}


async def _run_with_distinct_routing():
    """Run the golden pipeline under `_DISTINCT_ROUTING`, collecting every emitted event."""
    from langgraph.checkpoint.memory import MemorySaver

    collected = []

    async def collector(session_id, event):
        collected.append(event)

    token = set_run_config(RunConfig(llm_mode="fake", models=dict(_DISTINCT_ROUTING)))
    emitter_token = ev.set_emitter(collector)
    try:
        graph = build_graph(MemorySaver())
        await graph.ainvoke(
            initial_state(
                session_id="test-session", user_id="test-user", query="q" * 20, depth="balanced"
            ),
            _config(),
        )
    finally:
        ev.reset_emitter(emitter_token)
        reset_run_config(token)
    return collected


def _first_event(events: list[dict], agent: str) -> dict:
    for e in events:
        if e.get("agent") == agent:
            return e
    raise AssertionError(f"no event emitted for agent={agent!r}")


def _last_event(events: list[dict], agent: str) -> dict:
    for e in reversed(events):
        if e.get("agent") == agent:
            return e
    raise AssertionError(f"no event emitted for agent={agent!r}")


# ─── graph.py: disclosure in the live event stream ─────────────────────────────────


@pytest.mark.asyncio
async def test_planner_discloses_the_full_per_role_routing_at_plan_time():
    """Requirement 1: the run discloses provider:model per role at plan time, not just
    in the finished report — the planner's very first event, before any task exists."""
    events = await _run_with_distinct_routing()
    first = _first_event(events, "planner")
    assert first["detail"]["models"] == _DISTINCT_ROUTING


@pytest.mark.asyncio
async def test_each_node_stamps_the_route_it_actually_dialled():
    """A routing that differs per role renders per role — not a default repeated under
    every agent's name."""
    events = await _run_with_distinct_routing()
    for agent in ("planner", "executor", "critic", "synthesizer"):
        detail = _first_event(events, agent)["detail"]
        assert detail["model"] == _DISTINCT_ROUTING[agent], (
            f"{agent} should stamp its own dialled route, got {detail.get('model')!r}"
        )

    # And they are genuinely distinct, not four events that happen to match by accident.
    stamped = {
        a: _first_event(events, a)["detail"]["model"] for a in _DISTINCT_ROUTING if a != "chat"
    }
    assert len(set(stamped.values())) == len(stamped), f"routes were not distinct: {stamped}"


# ─── llm_factory.py: the served model, when a provider discloses one ───────────────


def test_served_model_id_reads_the_providers_disclosed_id():
    """A router alias (AGENTS.md, "auto/* are not pinned models") can resolve to a
    different model per call — this is how a caller learns what actually answered."""
    openai_style = AIMessage(content="hi", response_metadata={"model_name": "gpt-5-2025-08-07"})
    assert served_model_id(openai_style) == "gpt-5-2025-08-07"

    anthropic_style = AIMessage(content="hi", response_metadata={"model": "claude-opus-5-20250929"})
    assert served_model_id(anthropic_style) == "claude-opus-5-20250929"


def test_served_model_id_is_none_when_the_provider_discloses_nothing():
    """Never fabricate a served model — absence must stay absence (AGENTS.md, "never
    fake, never swallow"). Fake-mode responses carry no `response_metadata` at all."""
    assert served_model_id(AIMessage(content="hi")) is None
    assert served_model_id(AIMessage(content="hi", response_metadata={})) is None


@pytest.mark.asyncio
async def test_critic_verdict_event_carries_the_route_it_dialled(monkeypatch):
    """Direct node-level check mirroring the existing `test_critic_failclosed.py` style:
    the critic's kickoff event names its own model, independent of the whole graph."""
    from research_engine import graph as graph_mod

    async def fake_structured(role, messages, schema):
        from research_engine.schemas import CriticVerdict

        return CriticVerdict(passed=True, confidence=0.9), 0.0, 0, 0

    monkeypatch.setattr(graph_mod, "_structured", fake_structured)

    collected = []

    async def collector(session_id, event):
        collected.append(event)

    token = set_run_config(RunConfig(llm_mode="fake", models=dict(_DISTINCT_ROUTING)))
    emitter_token = ev.set_emitter(collector)
    try:
        await critic_node(
            {
                "session_id": "s",
                "tasks": [{"id": 1, "query": "q"}],
                "evidence": [{"task_id": 1, "source_url": "https://x", "snippet": "s"}],
                "verdicts": {},
                "retries": {},
                "cost_usd": 0.0,
                "tokens_input": 0,
                "tokens_output": 0,
            }
        )
    finally:
        ev.reset_emitter(emitter_token)
        reset_run_config(token)

    assert _first_event(collected, "critic")["detail"]["model"] == _DISTINCT_ROUTING["critic"]


@pytest.mark.asyncio
async def test_synthesizer_event_carries_the_route_it_dialled():
    """`synthesizer_node` currently emits its kickoff event with no `detail` at all."""
    collected = []

    async def collector(session_id, event):
        collected.append(event)

    token = set_run_config(RunConfig(llm_mode="fake", models=dict(_DISTINCT_ROUTING)))
    emitter_token = ev.set_emitter(collector)
    try:
        await synthesizer_node(
            {
                "session_id": "s",
                "original_query": "q",
                "evidence": [],
                "cost_usd": 0.0,
                "tokens_input": 0,
                "tokens_output": 0,
            }
        )
    finally:
        ev.reset_emitter(emitter_token)
        reset_run_config(token)

    assert (
        _first_event(collected, "synthesizer")["detail"]["model"]
        == _DISTINCT_ROUTING["synthesizer"]
    )


@pytest.mark.asyncio
async def test_synthesizer_completion_event_surfaces_the_served_model(monkeypatch):
    """When a provider discloses what actually served the request, the synthesizer's
    completion event carries it separately from the configured route — this is the
    mechanism that keeps a router alias from being displayed as if it were pinned."""
    from research_engine import graph as graph_mod

    class _StubModel:
        async def ainvoke(self, messages):
            return AIMessage(
                content="# Report\n\nSome finding [1].",
                response_metadata={"model": "claude-opus-5-20250929"},
                usage_metadata={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
            )

    monkeypatch.setattr(graph_mod, "get_llm", lambda role: _StubModel())

    collected = []

    async def collector(session_id, event):
        collected.append(event)

    emitter_token = ev.set_emitter(collector)
    try:
        await synthesizer_node(
            {
                "session_id": "s",
                "original_query": "q",
                "evidence": [],
                "cost_usd": 0.0,
                "tokens_input": 0,
                "tokens_output": 0,
            }
        )
    finally:
        ev.reset_emitter(emitter_token)

    assert _last_event(collected, "synthesizer")["detail"]["served_model"] == (
        "claude-opus-5-20250929"
    )


# ─── app/schemas/research.py: the third home of the contract ───────────────────────


def _base_session_kwargs(**overrides) -> dict:
    now = datetime.now(UTC)
    base = dict(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        status="COMPLETED",
        prompt="q" * 15,
        research_depth="balanced",
        total_cost_usd=0.0,
        total_tokens_input=0,
        total_tokens_output=0,
        created_at=now,
        updated_at=now,
    )
    base.update(overrides)
    return base


def test_session_detail_declares_model_routing():
    """`SessionDetail` must declare the field, or Pydantic silently drops it on the way
    from the ORM row to the browser — the exact bug `SourceSchema.snippets` already
    documents (AGENTS.md, "two hosts, one contract"). `session.model_routing` has been
    resolved and persisted since before this phase; only this schema never exposed it."""
    assert "model_routing" in SessionDetail.model_fields


def test_session_detail_round_trips_a_per_role_routing():
    detail = SessionDetail.model_validate(_base_session_kwargs(model_routing=_DISTINCT_ROUTING))
    assert detail.model_routing == _DISTINCT_ROUTING


def test_unresolved_routing_renders_as_none_not_a_default():
    """The unmeasured-vs-zero rule (AGENTS.md): a run that failed before the planner —
    or predates this field — must render "not resolved", never a guessed default."""
    detail = SessionDetail.model_validate(_base_session_kwargs())
    assert detail.model_routing is None
