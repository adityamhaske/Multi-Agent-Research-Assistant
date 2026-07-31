"""
The engine's ports (docs/13 §4, docs/12 M6 step 3).

Protocols only — every implementation lives in a host. The server supplies Postgres/
Redis-backed versions (`app/adapters.py`); the desktop build (docs/12 M9) supplies
SQLite and in-process ones. `research_engine` depends on these shapes and nothing else,
which is what lets one graph run in both places.

Two ports, not the four the first draft of docs/13 listed. The two that were dropped
were interfaces where data was sufficient:

- **KeyProvider** — provider keys are resolved by the host *before* a run (the server
  decrypts them from `users.api_key_encrypted`) and handed over as a plain
  `{provider: key}` mapping. Wrapping that in a callable would add a lookup indirection
  the engine never exercises, so `runner.run(provider_keys=…)` takes the data instead.
- **RunLock** — guarding against two workers running the same session is host
  scheduling, not pipeline behaviour: the server needs a Redis token lock because
  Celery can redeliver, and a single-process desktop app needs at most an
  `asyncio.Lock`. It stays in the host, wrapped around the runner call.

Checkpointing needs no port either — LangGraph's saver interface *is* the port
(`AsyncPostgresSaver` on the server, `AsyncSqliteSaver` locally). The host constructs
and `setup()`s the saver, then passes it in; schema creation is a host concern.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class EventSink(Protocol):
    """Receives one pipeline event. Installed via `events.set_emitter`.

    The server implementation writes an `agent_logs` row (durable SSE replay) and then
    publishes to Redis (live fan-out); a desktop one pushes onto an in-process queue.
    """

    async def __call__(self, session_id: str, event: dict) -> None: ...


@runtime_checkable
class Cache(Protocol):
    """Best-effort key/value cache for search results. Installed via `cache.set_cache`.

    Implementations may fail or no-op freely: `retrievers.search` treats every cache
    operation as advisory and never lets one break a search.
    """

    async def get(self, key: str) -> str | None: ...

    async def set(self, key: str, value: str, ttl: int) -> None: ...
