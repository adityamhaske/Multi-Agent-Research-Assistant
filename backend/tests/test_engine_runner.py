"""
Engine runner + ports (docs/12 M6 step 3, docs/13 §4).

`research_engine.runner` is the orchestration the desktop build will call with a SQLite
saver and in-process adapters, so it is exercised here with `MemorySaver` and fake models
— no DB, no Redis, no network, no keys. The golden journeys in `test_pipeline.py` cover
the graph; these cover the layer above it and the ports underneath.
"""

from __future__ import annotations

import uuid

import pytest
from langgraph.checkpoint.memory import MemorySaver

from app import adapters
from research_engine import events
from research_engine.cache import NullCache, get_cache, reset_cache, set_cache
from research_engine.ports import Cache, EventSink
from research_engine.runconfig import RunConfig, get_run_config
from research_engine.runner import RunOutcome, resume, run

QUERY = "What is the state of AI research assistants in 2026?"


def _saver_and_id(name: str) -> tuple[MemorySaver, str]:
    """A fresh saver per test so threads never collide across tests."""
    return MemorySaver(), f"runner-{name}"


# ── The three outcomes ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_run_stops_at_the_gate():
    saver, sid = _saver_and_id("gate")
    outcome = await run(checkpointer=saver, session_id=sid, user_id="u", query=QUERY)

    assert isinstance(outcome, RunOutcome)
    assert outcome.status == "awaiting_approval"
    assert outcome.draft_report and "# " in outcome.draft_report
    assert outcome.sources
    assert outcome.final_report is None, "nothing is final until a human approves"
    # An interrupt is not a failure.
    assert outcome.error is None
    # Elapsed is only recorded on a completed run, matching what the server persists.
    assert outcome.elapsed_seconds is None
    assert outcome.report == outcome.draft_report


@pytest.mark.asyncio
async def test_approval_completes_from_the_checkpoint():
    saver, sid = _saver_and_id("approve")
    await run(checkpointer=saver, session_id=sid, user_id="u", query=QUERY)

    outcome = await resume(checkpointer=saver, session_id=sid, approved=True)

    assert outcome.status == "completed"
    assert outcome.final_report
    assert outcome.elapsed_seconds is not None
    assert outcome.report == outcome.final_report


@pytest.mark.asyncio
async def test_rework_returns_to_the_gate_and_counts():
    saver, sid = _saver_and_id("rework")
    await run(checkpointer=saver, session_id=sid, user_id="u", query=QUERY)

    reworked = await resume(
        checkpointer=saver, session_id=sid, approved=False, feedback="More on limitations."
    )
    assert reworked.status == "awaiting_approval"
    assert reworked.rework_count == 1

    done = await resume(checkpointer=saver, session_id=sid, approved=True)
    assert done.status == "completed"
    assert done.rework_count == 1


@pytest.mark.asyncio
async def test_totals_are_carried_through_and_rounded():
    saver, sid = _saver_and_id("totals")
    outcome = await run(checkpointer=saver, session_id=sid, user_id="u", query=QUERY)

    assert outcome.tokens_input > 0 and outcome.tokens_output > 0
    assert outcome.cost_usd > 0
    # Six places is what the server column stores; more would silently truncate there.
    assert outcome.cost_usd == round(outcome.cost_usd, 6)


# ── Ports ──────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_event_sink_receives_every_agent():
    collected: list[dict] = []

    async def sink(session_id: str, event: dict) -> None:
        collected.append(event)

    saver, sid = _saver_and_id("sink")
    await run(checkpointer=saver, session_id=sid, user_id="u", query=QUERY, event_sink=sink)

    agents = {e["agent"] for e in collected}
    assert {"planner", "executor", "critic", "synthesizer"} <= agents


@pytest.mark.asyncio
async def test_run_config_override_is_scoped_to_the_run():
    """A per-run config must not leak into the process default (docs/12 M8 depends on this)."""
    before = get_run_config()
    saver, sid = _saver_and_id("cfg")

    override = RunConfig(llm_mode="fake", max_critic_loops=1)
    await run(checkpointer=saver, session_id=sid, user_id="u", query=QUERY, run_config=override)

    assert get_run_config() is before


@pytest.mark.asyncio
async def test_ports_do_not_leak_after_a_run():
    """Every ContextVar the runner installs is unwound, or the next run inherits it."""
    collected: list[dict] = []

    async def sink(session_id: str, event: dict) -> None:
        collected.append(event)

    saver, sid = _saver_and_id("leak")
    await run(
        checkpointer=saver,
        session_id=sid,
        user_id="u",
        query=QUERY,
        event_sink=sink,
        cache=NullCache(),
        provider_keys={"google": "run-scoped-key"},
    )

    assert collected, "sanity: the sink was actually installed during the run"
    seen = len(collected)

    # The emitter is back to the default no-op, so this goes nowhere.
    await events.emit(sid, "agent_log", agent="planner", message="after the run")
    assert len(collected) == seen

    assert isinstance(get_cache(), NullCache)


@pytest.mark.asyncio
async def test_null_cache_is_the_default_and_is_installable():
    assert isinstance(get_cache(), NullCache)
    assert await get_cache().get("anything") is None

    class Recording:
        def __init__(self) -> None:
            self.reads: list[str] = []

        async def get(self, key: str) -> str | None:
            self.reads.append(key)
            return None

        async def set(self, key: str, value: str, ttl: int) -> None:
            return None

    recorder = Recording()
    token = set_cache(recorder)
    try:
        assert await get_cache().get("k") is None
        assert recorder.reads == ["k"]
    finally:
        reset_cache(token)

    assert isinstance(get_cache(), NullCache)


def test_server_adapters_satisfy_the_ports():
    """The host's implementations structurally match what the engine declares."""
    assert isinstance(adapters.RedisCache(), Cache)
    sink = adapters.agent_log_sink(db=None, session_id=str(uuid.uuid4()))
    assert isinstance(sink, EventSink)
