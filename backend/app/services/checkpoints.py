"""
LangGraph checkpoint cleanup.

The checkpointer owns its own tables, keyed by `thread_id` (= our session id), with no
foreign key back to `sessions`. So deleting a session row does not remove its graph
state — and that state holds the full agent history, including fetched page content.
Leaving it behind would make "delete this session" a half-truth, so the API calls this
after a successful delete.
"""

from __future__ import annotations

import structlog

from app.config import settings

logger = structlog.get_logger()


def _dsn() -> str:
    # LangGraph's Postgres saver speaks psycopg, not asyncpg.
    return settings.database_url.replace("postgresql+asyncpg://", "postgresql://")


async def delete_thread(thread_id: str) -> None:
    """Drop all checkpoint state for one session. Raises on failure; caller logs."""
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

    async with AsyncPostgresSaver.from_conn_string(_dsn()) as saver:
        await saver.adelete_thread(thread_id)
    logger.info("checkpoints_deleted", thread_id=thread_id)
