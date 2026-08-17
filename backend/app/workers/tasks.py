"""
Celery task wrappers over the async pipeline engine (app.workers.pipeline_runner).

The tasks are deliberately thin: they run the async engine and, on unexpected
failure, mark the session FAILED. They do NOT auto-retry the whole pipeline (it is
not idempotent); a crashed run is resumed from the LangGraph checkpoint explicitly.
"""

from __future__ import annotations

import asyncio

import structlog

from app.logconfig import bind_run_context, clear_run_context
from app.workers.celery_app import celery_app

logger = structlog.get_logger()


@celery_app.task(name="run_agent_pipeline")
def run_agent_pipeline(session_id: str, user_id: str) -> None:
    from app.workers.pipeline_runner import run_pipeline

    # Clear first: workers are long-lived processes, and one run's identity must
    # never leak into the next task's logs. The bound correlation_id (= session_id)
    # rides along every log this task and the engine emit under asyncio.run.
    clear_run_context()
    bind_run_context(session_id, user_id=user_id)
    logger.info("pipeline_task_started")
    try:
        asyncio.run(run_pipeline(session_id, user_id))
        logger.info("pipeline_task_finished")
    except Exception as exc:  # noqa: BLE001
        logger.error("pipeline_task_failed", error=str(exc), exc_info=True)
        asyncio.run(_mark_failed(session_id, str(exc)))


@celery_app.task(name="resume_agent_pipeline")
def resume_agent_pipeline(
    session_id: str, user_id: str, approved: bool, feedback: str | None = None
) -> None:
    from app.workers.pipeline_runner import resume_pipeline

    clear_run_context()
    bind_run_context(session_id, user_id=user_id, approved=approved)
    logger.info("resume_task_started")
    try:
        asyncio.run(resume_pipeline(session_id, user_id, approved, feedback))
        logger.info("resume_task_finished")
    except Exception as exc:  # noqa: BLE001
        logger.error("resume_task_failed", error=str(exc), exc_info=True)
        asyncio.run(_mark_failed(session_id, str(exc)))


@celery_app.task(name="resume_plan_gate")
def resume_plan_gate(session_id: str, user_id: str, plan: dict) -> None:
    """Resume a session suspended at the research design gate (docs/07 §2, Phase 4).

    A separate task from `resume_agent_pipeline` rather than an extra argument on it:
    the two carry different payloads to different interrupts, and a single task that
    guessed which one it was holding is how a plan edit ends up resuming the draft gate.
    Celery also makes the distinction load-bearing — a queued message outlives a deploy,
    so widening the old task's signature would leave in-flight messages ambiguous.
    """
    from app.workers.pipeline_runner import resume_plan

    clear_run_context()
    bind_run_context(session_id, user_id=user_id)
    logger.info("plan_resume_task_started", task_count=len((plan or {}).get("tasks") or []))
    try:
        asyncio.run(resume_plan(session_id, user_id, plan))
        logger.info("plan_resume_task_finished")
    except Exception as exc:  # noqa: BLE001
        logger.error("plan_resume_task_failed", error=str(exc), exc_info=True)
        asyncio.run(_mark_failed(session_id, str(exc)))


async def _mark_failed(session_id: str, error: str) -> None:
    import uuid

    from sqlalchemy import select

    from app.db.base import AsyncSessionLocal, engine
    from app.db.redis import close_redis_pool, init_redis_pool, publish_event
    from app.models.session import Session, SessionStatus

    await init_redis_pool()
    try:
        async with AsyncSessionLocal() as db:
            session = (
                await db.execute(select(Session).where(Session.id == uuid.UUID(session_id)))
            ).scalar_one_or_none()
            if session:
                session.status = SessionStatus.FAILED
                session.error_message = error[:500]
                await db.commit()
        await publish_event(session_id, {"type": "FAILED", "data": {"reason": error[:500]}})
    finally:
        await close_redis_pool()
        await engine.dispose()
