"""
Pipeline tests (docs/08 §2 golden E2E 1–3 at the graph level, plus §3 regressions).

These run the compiled LangGraph with fake models + MemorySaver — no DB, no Redis,
no network, no API keys. They encode the product's core promise and would have
caught the July 2026 fatal bugs.
"""

import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from research_engine.events import emit
from research_engine.graph import build_graph
from research_engine.runner import initial_state


def _initial_state(query="What is the state of AI research assistants in 2026?"):
    return initial_state(
        session_id="test-session", user_id="test-user", query=query, depth="balanced"
    )


def _config():
    return {"configurable": {"thread_id": "test-session"}}


@pytest.mark.asyncio
async def test_pipeline_reaches_gate_with_evidence_and_sources():
    """Golden 1: pipeline runs to the HITL interrupt with a draft + real sources."""
    graph = build_graph(MemorySaver())
    result = await graph.ainvoke(_initial_state(), _config())

    assert "__interrupt__" in result, "pipeline should pause at the HITL gate"
    interrupt = result["__interrupt__"][0].value
    assert interrupt["type"] == "HITL_READY"
    assert interrupt["source_count"] >= 1

    state = graph.get_state(_config()).values
    assert state["draft_report"] and "# " in state["draft_report"]
    assert len(state["sources"]) >= 1
    assert not state.get("final_report")  # not finalized until approval


@pytest.mark.asyncio
async def test_executor_actually_gathers_evidence():
    """Regression: the executor produces evidence chunks (tools/loop actually run)."""
    graph = build_graph(MemorySaver())
    await graph.ainvoke(_initial_state(), _config())
    state = graph.get_state(_config()).values
    assert len(state["evidence"]) >= 1
    assert all(e.get("source_url") for e in state["evidence"])


@pytest.mark.asyncio
async def test_approval_finalizes_without_replanning():
    """Golden 2: approving resumes from the gate to COMPLETED — not from the planner."""
    graph = build_graph(MemorySaver())
    await graph.ainvoke(_initial_state(), _config())
    tasks_before = graph.get_state(_config()).values["tasks"]

    result = await graph.ainvoke(Command(resume={"approved": True, "feedback": None}), _config())

    assert result["final_report"], "approval must produce a final report"
    assert result["approved"] is True
    # Resume entered at the gate: task list is unchanged (planner did not re-run).
    assert graph.get_state(_config()).values["tasks"] == tasks_before


@pytest.mark.asyncio
async def test_rework_re_synthesizes_then_finalizes():
    """Golden 3: reject → re-synthesize with feedback → gate again → approve → done."""
    graph = build_graph(MemorySaver())
    await graph.ainvoke(_initial_state(), _config())

    reworked = await graph.ainvoke(
        Command(resume={"approved": False, "feedback": "Add more detail on limitations."}),
        _config(),
    )
    assert "__interrupt__" in reworked, "rework should pause at the gate again"
    assert graph.get_state(_config()).values["rework_count"] == 1

    done = await graph.ainvoke(Command(resume={"approved": True, "feedback": None}), _config())
    assert done["final_report"]


@pytest.mark.asyncio
async def test_events_are_emitted_for_each_agent():
    """The live feed has content: each agent emits at least one event."""
    collected = []

    async def collector(session_id, event):
        collected.append(event)

    from research_engine import events as ev

    token = ev.set_emitter(collector)
    try:
        graph = build_graph(MemorySaver())
        await graph.ainvoke(_initial_state(), _config())
    finally:
        ev.reset_emitter(token)

    agents = {e["agent"] for e in collected}
    assert {"planner", "executor", "critic", "synthesizer"} <= agents


@pytest.mark.asyncio
async def test_emit_is_noop_without_a_sink():
    """emit() is safe with no configured sink (default no-op)."""
    await emit("s", "agent_log", agent="planner", message="hi")
