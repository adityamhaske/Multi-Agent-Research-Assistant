"""
Async engine that runs/resumes the LangGraph pipeline for a session
(docs/02 §2/§6, docs/04). Celery tasks are thin wrappers over this.

Design guarantees:
- One DB session scope for the whole run (no detached-object writes).
- Token-based Redis lock with TTL > task timeout; released only by its owner.
- LangGraph AsyncPostgresSaver checkpointing keyed by thread_id=session_id, so
  approval/rework resumes from the gate — never re-runs the pipeline.
- Every node event is persisted to agent_logs (durable SSE replay) then published
  to Redis (live fan-out).
"""

from __future__ import annotations

import time
import uuid

import structlog
from langgraph.types import Command
from sqlalchemy import select

from app.agent import events, llm_factory
from app.agent.graph import build_graph
from app.config import settings
from app.db.base import AsyncSessionLocal, engine
from app.db.redis import (
    acquire_session_lock,
    close_redis_pool,
    init_redis_pool,
    publish_event,
    release_session_lock,
)
from app.models.agent_log import AgentLog
from app.models.session import Session, SessionStatus
from app.models.user import User
from app.services import crypto

logger = structlog.get_logger()


def _checkpointer_dsn() -> str:
    # LangGraph's Postgres saver uses psycopg (sync-style DSN), not asyncpg.
    return settings.database_url.replace("postgresql+asyncpg://", "postgresql://")


def _make_sink(db, session_id: str):
    """Emitter that writes an agent_logs row then publishes to Redis (with the row id)."""

    async def sink(sid: str, event: dict) -> None:
        row = AgentLog(
            session_id=uuid.UUID(session_id),
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


async def _user_provider_keys(db, user_id: str) -> dict[str, str]:
    """Decrypt this user's BYOK provider key, if they've set one.

    Returns {provider: key} or {} to fall back to the server's key. A key that
    can't be decrypted (signing secret rotated) is treated as absent and logged
    once — the run continues on the server key rather than failing outright.
    """
    user = (
        await db.execute(select(User).where(User.id == uuid.UUID(user_id)))
    ).scalar_one_or_none()
    if user is None or not user.api_key_encrypted or not user.api_key_provider:
        return {}
    plaintext = crypto.decrypt(user.api_key_encrypted)
    if not plaintext:
        logger.warning("byok_key_undecryptable", user_id=user_id, provider=user.api_key_provider)
        return {}
    return {user.api_key_provider: plaintext}


async def _run(session_id: str, user_id: str, *, resume_cmd: Command | None) -> None:
    lock_token = uuid.uuid4().hex
    await init_redis_pool()
    try:
        if not await acquire_session_lock(
            session_id, lock_token, ttl=settings.celery_task_timeout_seconds + 60
        ):
            logger.warning("session_lock_busy", session_id=session_id)
            return

        try:
            async with AsyncSessionLocal() as db:
                session = (
                    await db.execute(select(Session).where(Session.id == uuid.UUID(session_id)))
                ).scalar_one_or_none()
                if session is None:
                    logger.error("session_not_found", session_id=session_id)
                    return

                session.status = SessionStatus.RUNNING
                await db.commit()

                # BYOK: install this user's own provider key for the run, scoped to
                # this context so concurrent runs never see each other's key. Falls
                # back to the server key when the user hasn't set one.
                user_keys = await _user_provider_keys(db, user_id)
                keys_token = llm_factory.set_user_keys(user_keys)
                token = events.set_emitter(_make_sink(db, session_id))
                try:
                    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

                    async with AsyncPostgresSaver.from_conn_string(_checkpointer_dsn()) as saver:
                        await saver.setup()
                        graph = build_graph(saver)
                        config = {"configurable": {"thread_id": session_id}}

                        if resume_cmd is None:
                            initial = {
                                "session_id": session_id,
                                "user_id": user_id,
                                "original_query": session.prompt,
                                "research_depth": session.research_depth,
                                "evidence": [],
                                "critic_retries": 0,
                                "rework_count": 0,
                                "cost_usd": 0.0,
                                "tokens_input": 0,
                                "tokens_output": 0,
                                "started_at": time.time(),
                            }
                            result = await graph.ainvoke(initial, config)
                        else:
                            result = await graph.ainvoke(resume_cmd, config)

                        # Async checkpointer → must use the async state getter; the
                        # sync get_state() raises from the main async thread.
                        state = (await graph.aget_state(config)).values
                        await _persist_outcome(db, session, session_id, result, state)
                finally:
                    events.reset_emitter(token)
                    llm_factory.reset_user_keys(keys_token)
        finally:
            await release_session_lock(session_id, lock_token)
    finally:
        await close_redis_pool()
        await engine.dispose()


async def _persist_outcome(
    db, session: Session, session_id: str, result: dict, state: dict
) -> None:
    session.total_cost_usd = round(state.get("cost_usd", 0.0), 6)
    session.total_tokens_input = state.get("tokens_input", 0)
    session.total_tokens_output = state.get("tokens_output", 0)
    session.rework_count = state.get("rework_count", 0)

    if "__interrupt__" in result:
        # Paused at the HITL gate.
        session.status = SessionStatus.AWAITING_APPROVAL
        session.draft_report = state.get("draft_report")
        session.sources = state.get("sources", [])
        await db.commit()
        await events.emit(
            session_id,
            "HITL_READY",
            data={
                "word_count": len((state.get("draft_report") or "").split()),
                "source_count": len(state.get("sources", [])),
                "cost_usd": round(state.get("cost_usd", 0.0), 4),
            },
        )
        return

    if state.get("error"):
        session.status = SessionStatus.FAILED
        session.error_message = str(state["error"])[:500]
        session.sources = state.get("sources", [])
        await db.commit()
        await events.emit(session_id, "FAILED", data={"reason": session.error_message})
        return

    # Approved → finalized.
    session.status = SessionStatus.COMPLETED
    session.final_report = state.get("final_report") or state.get("draft_report")
    session.sources = state.get("sources", [])
    session.elapsed_seconds = round(time.time() - state.get("started_at", time.time()), 2)
    await db.commit()
    await events.emit(
        session_id,
        "COMPLETED",
        data={
            "elapsed_s": float(session.elapsed_seconds or 0),
            "cost_usd": round(state.get("cost_usd", 0.0), 4),
        },
    )


async def run_pipeline(session_id: str, user_id: str) -> None:
    await _run(session_id, user_id, resume_cmd=None)


async def resume_pipeline(
    session_id: str, user_id: str, approved: bool, feedback: str | None
) -> None:
    await _run(
        session_id, user_id, resume_cmd=Command(resume={"approved": approved, "feedback": feedback})
    )
