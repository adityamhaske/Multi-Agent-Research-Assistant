"""
The server host's implementations of the engine's ports (docs/13 §4).

`research_engine` declares shapes in `research_engine/ports.py`; this module supplies the
Postgres/Redis-backed versions of them. The desktop host (docs/12 M9) will have its own
counterpart supplying SQLite and in-process equivalents, and the engine will not know the
difference.

Conformance is structural, not by inheritance — `tests/test_engine_runner.py` asserts it
with `isinstance` against the runtime-checkable Protocols.

Kept separate from `app/runtime.py`, which maps settings → RunConfig and nothing else.
"""

from __future__ import annotations

import uuid

from app.db.redis import publish_event
from app.models.agent_log import AgentLog
from research_engine.ports import EventSink


class RedisCache:
    """Search-result cache backed by the shared Redis pool.

    Deliberately not defensive: `retrievers.search` treats every cache operation as
    advisory and swallows failures, which is why an unreachable Redis degrades a run to
    "uncached" instead of failing it.
    """

    async def get(self, key: str) -> str | None:
        from app.db.redis import get_redis

        return await get_redis().get(key)

    async def set(self, key: str, value: str, ttl: int) -> None:
        from app.db.redis import get_redis

        await get_redis().set(key, value, ex=ttl)


def agent_log_sink(db, session_id: str) -> EventSink:
    """Event sink that persists to `agent_logs`, then publishes to Redis.

    The row is written and committed *before* the publish, and the row id is attached to
    the published payload — that is what makes SSE replay with `Last-Event-ID` work
    (docs/05 §4): a client reconnecting mid-run resumes from a durable id rather than
    losing whatever was in flight.

    Bound to a caller-supplied DB session so the whole run shares one session scope; the
    detached-object writes that caused the July 2026 worker bug came from not doing this.
    """
    session_uuid = uuid.UUID(session_id)

    async def sink(sid: str, event: dict) -> None:  # noqa: ARG001 - port shape
        row = AgentLog(
            session_id=session_uuid,
            event_type=event.get("type", "agent_log"),
            agent_name=event.get("agent"),
            payload=event,
        )
        db.add(row)
        await db.flush()
        event["id"] = row.id
        await db.commit()
        await publish_event(session_id, event)

    return sink
