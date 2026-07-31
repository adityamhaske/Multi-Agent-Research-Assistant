"""
Search-cache indirection (docs/13 §4, docs/12 M6 step 3).

`retrievers.search` used to reach into `app.db.redis` directly — the last import that
tied the engine to the server's data plane. It now goes through a `Cache` port held in a
`ContextVar`, exactly like the event emitter in `events.py`.

The default is a null cache, so an un-hosted engine (tests, the desktop build before its
SQLite cache exists, a bare CLI run) works with no cache at all — which is already how
the retriever chain behaved when Redis was absent, since every cache touch there is
best-effort.
"""

from __future__ import annotations

from contextvars import ContextVar

from research_engine.ports import Cache


class NullCache:
    """Caches nothing. The default, so no host is required."""

    async def get(self, key: str) -> str | None:  # noqa: ARG002 - protocol shape
        return None

    async def set(self, key: str, value: str, ttl: int) -> None:  # noqa: ARG002
        return None


_NULL: Cache = NullCache()

_cache: ContextVar[Cache] = ContextVar("engine_cache", default=_NULL)


def set_cache(cache: Cache):
    """Install a cache for the current context. Returns a token for `reset_cache`."""
    return _cache.set(cache)


def reset_cache(token) -> None:
    _cache.reset(token)


def get_cache() -> Cache:
    return _cache.get()
