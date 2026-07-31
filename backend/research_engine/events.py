"""
Pipeline event emission indirection (docs/02 §5, docs/05 §4).

Graph nodes call `emit(...)`; the actual sink is a ContextVar-held async callable.
The worker sets it to a sink that (1) inserts an agent_logs row for durable SSE
replay and (2) publishes to Redis for live fan-out. In tests it defaults to a
collector or no-op, so the graph runs with no DB/Redis.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from contextvars import ContextVar

Emitter = Callable[[str, dict], Awaitable[None]]


async def _noop(session_id: str, event: dict) -> None:  # pragma: no cover - trivial
    return None


_emitter: ContextVar[Emitter] = ContextVar("pipeline_emitter", default=_noop)


def set_emitter(fn: Emitter):
    """Install an emitter for the current context. Returns the ContextVar token."""
    return _emitter.set(fn)


def reset_emitter(token) -> None:
    _emitter.reset(token)


async def emit(
    session_id: str,
    event_type: str,
    *,
    agent: str | None = None,
    message: str | None = None,
    detail: dict | None = None,
    data: dict | None = None,
) -> None:
    event = {
        "type": event_type,
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "agent": agent,
        "message": message,
        "detail": detail,
        "data": data,
    }
    await _emitter.get()(session_id, event)
