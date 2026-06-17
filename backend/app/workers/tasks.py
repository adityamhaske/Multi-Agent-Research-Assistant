"""
Celery tasks for running the LangGraph agent pipeline in the background.
"""
import asyncio
import json
import time
from typing import Optional
import structlog

from app.workers.celery_app import celery_app
from app.config import settings

logger = structlog.get_logger()


@celery_app.task(bind=True, max_retries=2, default_retry_delay=10, name="run_agent_pipeline")
def run_agent_pipeline(
    self,
    session_id: str,
    user_id: str,
    resume: bool = False,
    approved: Optional[bool] = None,
    feedback: Optional[str] = None,
):
    """
    Main Celery task: runs the LangGraph agent pipeline for a research session.

    Args:
        session_id: UUID string of the session to process.
        user_id: UUID string of the owning user.
        resume: If True, resume from the HITL checkpoint.
        approved: User's approval decision (True=approve, False=rework). Only used when resume=True.
        feedback: User's rework feedback text. Only used when resume=True and approved=False.
    """
    log = logger.bind(session_id=session_id, user_id=user_id, resume=resume)
    log.info("celery_task_started")

    try:
        asyncio.run(
            _run_pipeline_async(
                session_id=session_id,
                user_id=user_id,
                resume=resume,
                approved=approved,
                feedback=feedback,
            )
        )
        log.info("celery_task_completed")
    except Exception as exc:
        log.error("celery_task_failed", error=str(exc), exc_info=True)
        try:
            # Attempt retry
            raise self.retry(exc=exc)
        except self.MaxRetriesExceededError:
            # All retries exhausted — mark session as FAILED
            asyncio.run(_mark_session_failed(session_id, str(exc)))


async def _run_pipeline_async(
    session_id: str,
    user_id: str,
    resume: bool,
    approved: Optional[bool],
    feedback: Optional[str],
) -> None:
    """Async implementation of the agent pipeline run."""
    from app.db.base import AsyncSessionLocal, engine
    from app.db.redis import init_redis_pool, close_redis_pool, publish_event, acquire_session_lock, release_session_lock
    from app.models.session import Session, SessionStatus
    from sqlalchemy import select

    # Init connections for this task's event loop
    await init_redis_pool()

    try:
        # Acquire distributed lock so only one worker processes this session at a time
        acquired = await acquire_session_lock(session_id)
        if not acquired:
            logger.warning("session_lock_failed", session_id=session_id, reason="Already locked by another worker")
            return

        try:
            async with AsyncSessionLocal() as db:
                # Load session
                result = await db.execute(select(Session).where(Session.id == session_id))
                session = result.scalar_one_or_none()
                if not session:
                    logger.error("session_not_found", session_id=session_id)
                    return

            # Build initial state
            if not resume:
                initial_state = {
                    "session_id": session_id,
                    "user_id": user_id,
                    "original_query": session.prompt,
                    "research_depth": session.research_depth,
                    "selected_sources": session.selected_sources,
                    "tasks": [],
                    "current_task_index": 0,
                    "raw_context": [],
                    "critic_feedback": None,
                    "critic_loop_count": 0,
                    "synthesized_draft": None,
                    "human_feedback": None,
                    "final_report": None,
                    "total_tokens_input": 0,
                    "total_tokens_output": 0,
                    "total_cost_usd": 0.0,
                    "start_time": time.time(),
                    "error": None,
                    "error_node": None,
                }
                # Update status to RUNNING
                session.status = SessionStatus.RUNNING
                await db.commit()
            else:
                # Resuming from HITL checkpoint
                initial_state = session.checkpoint_data or {}
                initial_state["human_feedback"] = feedback if not approved else None
                initial_state["approved"] = approved
                session.status = SessionStatus.RUNNING
                await db.commit()

            # Publish "running" status event
            await publish_event(session_id, {
                "type": "agent_log",
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "data": {
                    "agent_name": "system",
                    "action": "Pipeline started" if not resume else "Resuming from HITL checkpoint",
                    "result": None,
                }
            })

            # Import and run graph
            from app.agent.graph import run_graph
            await run_graph(initial_state, db, session)

        finally:
            await release_session_lock(session_id)
    finally:
        await close_redis_pool()
        await engine.dispose()


async def _mark_session_failed(session_id: str, error: str) -> None:
    """Mark a session as FAILED after all retries are exhausted."""
    from app.db.base import AsyncSessionLocal, engine
    from app.db.redis import init_redis_pool, close_redis_pool, publish_event
    from app.models.session import Session, SessionStatus
    from sqlalchemy import select

    await init_redis_pool()
    try:
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(Session).where(Session.id == session_id))
            session = result.scalar_one_or_none()
            if session:
                session.status = SessionStatus.FAILED
                session.error_message = error[:500]  # Truncate to fit column
                await db.commit()

        await publish_event(session_id, {
            "type": "FAILED",
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "data": {"error": error},
        })
    finally:
        await close_redis_pool()
        await engine.dispose()
