from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from app.config import settings

if TYPE_CHECKING:
    import redis.asyncio as aioredis

logger = structlog.get_logger()

_redis_pool: aioredis.Redis | None = None


async def init_redis_pool() -> None:
    """Open the shared pool. Importing `redis` here, not at module scope, is load-bearing.

    The desktop sidecar reaches this module at request time — its V2 routes import their
    handlers from `app.api.v1.v2_runs`, which declares `Depends(get_redis)` for the
    server's stream. The desktop mounts no such route and never calls this function, but
    the import still had to resolve, and `research-sidecar.spec` excludes `redis` on
    purpose: the desktop speaks SQLite only and has no Redis to speak to. A module-level
    import therefore cost the packaged app every V2 route with a `ModuleNotFoundError`,
    while running fine from a source checkout where the package is installed.
    """
    global _redis_pool

    import redis.asyncio as aioredis

    _redis_pool = await aioredis.from_url(
        settings.redis_url,
        encoding="utf-8",
        decode_responses=True,
        max_connections=50,
    )
    # Test connection
    await _redis_pool.ping()
    logger.info("redis_init", message="Redis connection pool initialized")


async def close_redis_pool() -> None:
    global _redis_pool
    if _redis_pool:
        await _redis_pool.aclose()
        logger.info("redis_close", message="Redis connection pool closed")


def get_redis() -> aioredis.Redis:
    """FastAPI dependency — returns the shared Redis connection pool."""
    if _redis_pool is None:
        raise RuntimeError("Redis pool not initialized. Call init_redis_pool() first.")
    return _redis_pool


async def publish_event(session_id: str, event: dict) -> None:
    """Publish a JSON event to a session's SSE channel."""
    import json

    redis = get_redis()
    channel = f"session:{session_id}:events"
    await redis.publish(channel, json.dumps(event))


# Compare-and-delete so a worker only releases a lock it still owns (docs/02 §6).
_RELEASE_LUA = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
  return redis.call('DEL', KEYS[1])
end
return 0
"""


async def acquire_session_lock(session_id: str, token: str, ttl: int) -> bool:
    """Acquire a session lock with a unique token. TTL must exceed the task timeout."""
    redis = get_redis()
    return bool(await redis.set(f"lock:session:{session_id}", token, ex=ttl, nx=True))


async def release_session_lock(session_id: str, token: str) -> None:
    """Release the lock only if we still hold it (token match)."""
    redis = get_redis()
    await redis.eval(_RELEASE_LUA, 1, f"lock:session:{session_id}", token)
