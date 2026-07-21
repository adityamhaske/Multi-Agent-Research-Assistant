import redis.asyncio as aioredis
import structlog

from app.config import settings

logger = structlog.get_logger()

_redis_pool: aioredis.Redis | None = None


async def init_redis_pool() -> None:
    global _redis_pool
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


async def acquire_session_lock(session_id: str, timeout: int = 30) -> bool:
    """Acquire a distributed lock for a session. Returns True if acquired."""
    redis = get_redis()
    lock_key = f"lock:session:{session_id}"
    return await redis.set(lock_key, "1", ex=timeout, nx=True)


async def release_session_lock(session_id: str) -> None:
    """Release the distributed lock for a session."""
    redis = get_redis()
    lock_key = f"lock:session:{session_id}"
    await redis.delete(lock_key)
