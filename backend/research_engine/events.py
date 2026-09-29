"""
Pipeline event emission indirection (docs/02 §5, docs/05 §4).

Graph nodes call `emit(...)`; the actual sink is a ContextVar-held async callable.
The worker sets it to a sink that (1) inserts an agent_logs row for durable SSE
replay and (2) publishes to Redis for live fan-out. In tests it defaults to a
collector or no-op, so the graph runs with no DB/Redis.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from contextvars import ContextVar

import structlog

logger = structlog.get_logger()

Emitter = Callable[[str, dict], Awaitable[None]]


async def _noop(session_id: str, event: dict) -> None:  # pragma: no cover - trivial
    return None


_emitter: ContextVar[Emitter] = ContextVar("pipeline_emitter", default=_noop)


def set_emitter(fn: Emitter):
    """Install an emitter for the current context. Returns the ContextVar token."""
    return _emitter.set(fn)


def reset_emitter(token) -> None:
    _emitter.reset(token)


def make_event(
    event_type: str,
    *,
    agent: str | None = None,
    message: str | None = None,
    detail: dict | None = None,
    data: dict | None = None,
) -> dict:
    """Build an event envelope without sending it.

    Exposed so a host can emit *lifecycle* events (HITL_READY / COMPLETED / FAILED)
    through its own sink at a moment of its choosing. The server host emits them only
    after committing the session row, so a client that receives COMPLETED and
    immediately re-fetches never sees a stale RUNNING status. Pipeline events from
    graph nodes go through `emit` and the installed emitter instead.
    """
    return {
        "type": event_type,
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "agent": agent,
        "message": message,
        "detail": detail,
        "data": data,
    }


async def emit(
    session_id: str,
    event_type: str,
    *,
    agent: str | None = None,
    message: str | None = None,
    detail: dict | None = None,
    data: dict | None = None,
) -> None:
    event = make_event(event_type, agent=agent, message=message, detail=detail, data=data)
    await _write_through_cancellation(_emitter.get()(session_id, event))


async def _write_through_cancellation(write: Awaitable[None]) -> None:
    """Let a sink write already under way land before a cancellation takes effect.

    A node's fan-out cancels the siblings of a failed task (`concurrency.gather_or_cancel`),
    and a sibling is often inside `emit`. Cancelling there interrupts the host's commit
    halfway — measured to leak the pooled connection on aiosqlite (desktop) and to drop it
    on asyncpg — and leaves the event maybe-durable. A write takes milliseconds, so the
    cancellation waits for it and is then honoured; no *new* write starts after it.
    """
    task = asyncio.ensure_future(write)
    try:
        await asyncio.shield(task)
    except asyncio.CancelledError:
        # A second cancellation during the wait is absorbed the same way; the write lands.
        while not task.done():
            try:
                await asyncio.wait([task])
            except asyncio.CancelledError:
                pass
        if not task.cancelled() and task.exception() is not None:
            logger.warning(
                "event_write_failed_during_cancellation",
                error=f"{type(task.exception()).__name__}: {task.exception()}",
            )
        raise
