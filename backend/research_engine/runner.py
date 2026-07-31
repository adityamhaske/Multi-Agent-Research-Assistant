"""
Host-independent pipeline orchestration (docs/13 §4–§5, docs/12 M6 step 3).

`app/workers/pipeline_runner.py` used to do six things at once: take a Redis lock, open a
SQLAlchemy session, build a Postgres checkpointer, install the run's context, drive the
graph, and write the result back to ORM models. Only *one* of those — installing context
and driving the graph — is pipeline behaviour. The rest is the server host.

This module is that one thing. It takes a ready checkpointer and the ports it needs,
runs or resumes the graph, and returns a `RunOutcome` describing what happened. It never
touches a database, a queue, or an ORM model, so the same code path serves the Celery
worker (Postgres saver, Redis cache, `agent_logs` sink) and the desktop sidecar (SQLite
saver, SQLite cache, in-process sink).

What deliberately stays in the host:

- **Constructing and `setup()`-ing the checkpointer.** Schema creation is a host concern;
  the engine receives a saver that is ready to use.
- **The run lock.** Guarding against double execution is scheduling, not pipeline
  behaviour — see `ports.py`.
- **Persisting the outcome, and emitting lifecycle events.** The host commits its own
  session row and only then emits HITL_READY / COMPLETED / FAILED (via
  `events.make_event`), which preserves today's guarantee that a client acting on a
  terminal event never reads a stale status.
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Literal

from langgraph.types import Command

from research_engine import events, llm_factory
from research_engine.cache import reset_cache, set_cache
from research_engine.graph import build_graph
from research_engine.ports import Cache, EventSink
from research_engine.runconfig import RunConfig, reset_run_config, set_run_config

RunStatus = Literal["awaiting_approval", "completed", "failed"]

# Matches the column width the server truncates error messages to.
_MAX_ERROR_CHARS = 500


@dataclass(frozen=True)
class RunOutcome:
    """What one graph invocation produced. Plain data — no ORM, no host types."""

    status: RunStatus
    draft_report: str | None = None
    final_report: str | None = None
    sources: list[dict] = field(default_factory=list)
    cost_usd: float = 0.0
    tokens_input: int = 0
    tokens_output: int = 0
    rework_count: int = 0
    elapsed_seconds: float | None = None
    error: str | None = None

    @property
    def report(self) -> str | None:
        """The best available report text: finalized if approved, else the draft."""
        return self.final_report or self.draft_report


@contextmanager
def _installed(
    run_config: RunConfig | None,
    provider_keys: dict[str, str] | None,
    event_sink: EventSink | None,
    cache: Cache | None,
):
    """Install the run's context, then unwind it in reverse order.

    Each of these is a ContextVar, so concurrent runs in one worker process stay
    isolated from each other — that is what makes per-session model routing (docs/12 M8)
    and per-user BYOK keys safe under concurrency.
    """
    undo: list[tuple] = []
    try:
        if run_config is not None:
            undo.append((reset_run_config, set_run_config(run_config)))
        if provider_keys is not None:
            undo.append((llm_factory.reset_user_keys, llm_factory.set_user_keys(provider_keys)))
        if event_sink is not None:
            undo.append((events.reset_emitter, events.set_emitter(event_sink)))
        if cache is not None:
            undo.append((reset_cache, set_cache(cache)))
        yield
    finally:
        for reset, token in reversed(undo):
            reset(token)


def initial_state(*, session_id: str, user_id: str, query: str, depth: str = "balanced") -> dict:
    """The graph's starting state for a fresh run."""
    return {
        "session_id": session_id,
        "user_id": user_id,
        "original_query": query,
        "research_depth": depth,
        "evidence": [],
        "verdicts": {},
        "retries": {},
        "research_round": 0,
        "rework_count": 0,
        "cost_usd": 0.0,
        "tokens_input": 0,
        "tokens_output": 0,
        "started_at": time.time(),
    }


def _outcome(result: dict, state: dict) -> RunOutcome:
    """Map final graph state onto a RunOutcome.

    Ordering matters: an interrupt is checked before `error`, because a run that paused
    at the gate is awaiting a human, not failed.
    """
    totals = {
        "sources": state.get("sources") or [],
        "cost_usd": round(state.get("cost_usd", 0.0), 6),
        "tokens_input": state.get("tokens_input", 0),
        "tokens_output": state.get("tokens_output", 0),
        "rework_count": state.get("rework_count", 0),
    }

    if "__interrupt__" in result:
        return RunOutcome(
            status="awaiting_approval", draft_report=state.get("draft_report"), **totals
        )

    if state.get("error"):
        return RunOutcome(status="failed", error=str(state["error"])[:_MAX_ERROR_CHARS], **totals)

    return RunOutcome(
        status="completed",
        draft_report=state.get("draft_report"),
        final_report=state.get("final_report") or state.get("draft_report"),
        elapsed_seconds=round(time.time() - state.get("started_at", time.time()), 2),
        **totals,
    )


async def _drive(
    *,
    checkpointer,
    session_id: str,
    payload,
    run_config: RunConfig | None,
    provider_keys: dict[str, str] | None,
    event_sink: EventSink | None,
    cache: Cache | None,
) -> RunOutcome:
    config = {"configurable": {"thread_id": session_id}}
    with _installed(run_config, provider_keys, event_sink, cache):
        graph = build_graph(checkpointer)
        result = await graph.ainvoke(payload, config)
        # An async checkpointer requires the async state getter; the sync `get_state()`
        # raises when called from the running loop.
        state = (await graph.aget_state(config)).values
    return _outcome(result, state)


async def run(
    *,
    checkpointer,
    session_id: str,
    user_id: str,
    query: str,
    depth: str = "balanced",
    run_config: RunConfig | None = None,
    provider_keys: dict[str, str] | None = None,
    event_sink: EventSink | None = None,
    cache: Cache | None = None,
) -> RunOutcome:
    """Run a fresh research session up to its first stop (the review gate, or failure)."""
    return await _drive(
        checkpointer=checkpointer,
        session_id=session_id,
        payload=initial_state(session_id=session_id, user_id=user_id, query=query, depth=depth),
        run_config=run_config,
        provider_keys=provider_keys,
        event_sink=event_sink,
        cache=cache,
    )


async def resume(
    *,
    checkpointer,
    session_id: str,
    approved: bool,
    feedback: str | None = None,
    run_config: RunConfig | None = None,
    provider_keys: dict[str, str] | None = None,
    event_sink: EventSink | None = None,
    cache: Cache | None = None,
) -> RunOutcome:
    """Resume a session paused at the gate. Enters at the checkpoint — never replans."""
    return await _drive(
        checkpointer=checkpointer,
        session_id=session_id,
        payload=Command(resume={"approved": approved, "feedback": feedback}),
        run_config=run_config,
        provider_keys=provider_keys,
        event_sink=event_sink,
        cache=cache,
    )
