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


# ── V2 native runs ────────────────────────────────────────────────────────────────
#
# Separate task names from the V1 pair, for the reason `resume_plan_gate` is separate: a
# queued Celery message outlives a deploy, so widening an existing task's meaning would
# leave in-flight messages ambiguous about which domain they belong to.


@celery_app.task(name="run_v2_pipeline")
def run_v2_pipeline(run_id: str, user_id: str) -> None:
    from app.v2_execution import execute_run

    clear_run_context()
    bind_run_context(run_id, user_id=user_id)
    logger.info("v2_pipeline_task_started")
    try:
        asyncio.run(execute_run(run_id))
        logger.info("v2_pipeline_task_finished")
    except Exception as exc:  # noqa: BLE001
        logger.error("v2_pipeline_task_failed", error=str(exc), exc_info=True)
        asyncio.run(_mark_v2_failed(run_id, str(exc)))


@celery_app.task(name="resume_v2_pipeline")
def resume_v2_pipeline(
    run_id: str, user_id: str, approved: bool, feedback: str | None = None
) -> None:
    from app.v2_execution import execute_run

    clear_run_context()
    bind_run_context(run_id, user_id=user_id, approved=approved)
    logger.info("v2_resume_task_started")
    try:
        asyncio.run(execute_run(run_id, resume=(approved, feedback)))
        logger.info("v2_resume_task_finished")
    except Exception as exc:  # noqa: BLE001
        logger.error("v2_resume_task_failed", error=str(exc), exc_info=True)
        asyncio.run(_mark_v2_failed(run_id, str(exc)))


@celery_app.task(name="resume_v2_plan_gate")
def resume_v2_plan_gate(run_id: str, user_id: str, plan: dict) -> None:
    from app.v2_execution import execute_run

    clear_run_context()
    bind_run_context(run_id, user_id=user_id)
    logger.info("v2_plan_resume_task_started")
    try:
        asyncio.run(execute_run(run_id, plan=plan))
        logger.info("v2_plan_resume_task_finished")
    except Exception as exc:  # noqa: BLE001
        logger.error("v2_plan_resume_task_failed", error=str(exc), exc_info=True)
        asyncio.run(_mark_v2_failed(run_id, str(exc)))


async def _mark_v2_failed(run_id: str, error: str) -> None:
    """A crash outside the adapter still has to leave the run FAILED, not RUNNING forever.

    The V2 counterpart of `_mark_failed`, and the same shape: its own session, its own Redis
    lifecycle, and it never raises — a failure here would lose the only record of the first
    failure.
    """
    import uuid

    from sqlalchemy import select

    from app import v2_runtime
    from app.db.base import AsyncSessionLocal
    from app.db.redis import close_redis_pool, init_redis_pool, publish_event
    from app.models.research import ResearchRun

    await init_redis_pool()
    try:
        async with AsyncSessionLocal() as db:
            run = (
                await db.execute(select(ResearchRun).where(ResearchRun.id == uuid.UUID(run_id)))
            ).scalar_one_or_none()
            if run:
                # Through `record_failure` rather than assigning status here, so this path
                # inherits the cancelled-run rule instead of being a second place that has
                # to remember it (issue #54). Writing FAILED over a CANCELLED run violates
                # `ck_run_cancelled` and raises — from the one function whose docstring
                # promises it never does.
                await v2_runtime.record_failure(db, run, error[:500])
                await db.commit()
        await publish_event(run_id, {"type": "FAILED", "data": {"reason": error[:500]}})
    finally:
        await close_redis_pool()
