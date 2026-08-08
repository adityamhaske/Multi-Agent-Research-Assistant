"""
Server adapter for the research pipeline (docs/02 §2/§6, docs/13 §4–§5).

The orchestration itself lives in `research_engine.runner`, which knows nothing about
Postgres, Redis, Celery, or ORM models. This module supplies the server's half:

- the run lock (a Redis token lock — Celery can redeliver, so double execution is a real
  risk here in a way it is not in a single-process desktop app),
- one DB session scope for the whole run (no detached-object writes),
- the Postgres checkpointer, so approval/rework resumes from the gate rather than
  re-running research the user already paid for,
- the `agent_logs` + Redis event sink and the Redis search cache (`app/adapters.py`),
- persisting the outcome and *then* emitting the lifecycle event, so a client acting on
  COMPLETED never re-reads a stale RUNNING status.
"""

from __future__ import annotations

import uuid
from dataclasses import replace

import structlog
from sqlalchemy import select

from app import adapters
from app.config import settings
from app.db.base import AsyncSessionLocal, engine
from app.db.redis import (
    acquire_session_lock,
    close_redis_pool,
    init_redis_pool,
    release_session_lock,
)
from app.models.session import Session, SessionStatus
from app.models.user import User
from app.runtime import run_config_from_settings
from app.services import crypto, model_routing
from research_engine import events, runner
from research_engine.runconfig import RunConfig
from research_engine.runner import RunOutcome

logger = structlog.get_logger()


def _checkpointer_dsn() -> str:
    # LangGraph's Postgres saver uses psycopg (sync-style DSN), not asyncpg.
    return settings.database_url.replace("postgresql+asyncpg://", "postgresql://")


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


async def _run_config_for(db, session: Session, user_id: str) -> RunConfig:
    """The engine config for this run, with model routing resolved and snapshotted.

    Resolution order is session → user → deployment. The session's own snapshot wins so a
    resumed run (approve or rework) keeps the models it started with — the alternative is
    a report whose first half was written by one model and second half by another, which
    would quietly undermine the per-report attribution the snapshot exists to provide.
    """
    user = (
        await db.execute(select(User).where(User.id == uuid.UUID(user_id)))
    ).scalar_one_or_none()

    routing = model_routing.resolve(
        session_routing=session.model_routing,
        user_routing=(user.model_routing if user else None),
    )

    if session.model_routing != routing:
        session.model_routing = routing
        await db.commit()

    return replace(run_config_from_settings(), models=routing)


async def _execute(
    session_id: str, user_id: str, *, resume: tuple[bool, str | None] | None
) -> None:
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

                sink = adapters.agent_log_sink(db, session_id)
                ports = {
                    # BYOK: this user's own key, scoped to the run so concurrent runs in
                    # one worker never see each other's key. Empty → the server key.
                    "provider_keys": await _user_provider_keys(db, user_id),
                    "event_sink": sink,
                    "cache": adapters.RedisCache(),
                    # Per-run model routing (docs/12 M8). This is the per-run RunConfig
                    # override from M6 step 3 doing the job it was built for: a session
                    # runs on its own models without touching the process default, so
                    # concurrent runs on different models stay isolated.
                    "run_config": await _run_config_for(db, session, user_id),
                }

                from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

                async with AsyncPostgresSaver.from_conn_string(_checkpointer_dsn()) as saver:
                    await saver.setup()
                    if resume is None:
                        outcome = await runner.run(
                            checkpointer=saver,
                            session_id=session_id,
                            user_id=user_id,
                            query=session.prompt,
                            depth=session.research_depth,
                            **ports,
                        )
                    else:
                        approved, feedback = resume
                        outcome = await runner.resume(
                            checkpointer=saver,
                            session_id=session_id,
                            approved=approved,
                            feedback=feedback,
                            **ports,
                        )

                await _persist_outcome(
                    db, session, session_id, outcome, sink, ports["provider_keys"]
                )
        finally:
            await release_session_lock(session_id, lock_token)
    finally:
        await close_redis_pool()
        await engine.dispose()


async def _ingest_into_project_memory(db, session: Session, provider_keys: dict[str, str]) -> None:
    """Add this approved report to its project's memory (docs/14 §2).

    The single ingestion point in the system, and it sits on the *approval* transition on
    purpose: the human gate is the quality filter that keeps drafts and rejected work out
    of retrieval, which is what makes memory here trustworthy in a way "remember
    everything" features are not.

    Runs after the COMPLETED event has been published, not before. Embedding costs a round
    trip — a cold local model can take tens of seconds — and blocking the event the client
    is waiting on would trade a visible delay for an invisible benefit. Memory being a
    second behind the report is fine; the report appearing a second late is not.

    Never raises. The run has already succeeded and been committed; failing it
    retroactively because an embedding provider was down would destroy work in order to
    report a gap. The gap is reported instead, by `memory/status`, which counts approved
    reports against indexed ones and self-heals on the next re-index.
    """
    try:
        from app import adapters
        from app.services import memory

        embedder = await adapters.embeddings_for(provider_keys)
        result = await memory.ingest_session(db, session, embedder)
        if result.skipped:
            logger.info(
                "memory_ingest_skipped", session_id=str(session.id), reason=result.reason
            )
    except Exception as e:  # noqa: BLE001 — see docstring: never fail a completed run
        await db.rollback()
        logger.warning(
            "memory_ingest_failed",
            session_id=str(session.id),
            project_id=str(session.project_id),
            error=str(e),
        )


async def _persist_outcome(
    db,
    session: Session,
    session_id: str,
    outcome: RunOutcome,
    sink,
    provider_keys: dict[str, str] | None = None,
) -> None:
    """Write the outcome, commit, then publish the lifecycle event — in that order."""
    session.total_cost_usd = outcome.cost_usd
    session.total_tokens_input = outcome.tokens_input
    session.total_tokens_output = outcome.tokens_output
    session.rework_count = outcome.rework_count
    session.sources = outcome.sources

    if outcome.status == "awaiting_approval":
        session.status = SessionStatus.AWAITING_APPROVAL
        session.draft_report = outcome.draft_report
        await db.commit()
        await sink(
            session_id,
            events.make_event(
                "HITL_READY",
                data={
                    "word_count": len((outcome.draft_report or "").split()),
                    "source_count": len(outcome.sources),
                    "cost_usd": round(outcome.cost_usd, 4),
                },
            ),
        )
        return

    if outcome.status == "failed":
        session.status = SessionStatus.FAILED
        session.error_message = outcome.error
        await db.commit()
        await sink(session_id, events.make_event("FAILED", data={"reason": outcome.error}))
        return

    session.status = SessionStatus.COMPLETED
    session.final_report = outcome.final_report
    session.elapsed_seconds = outcome.elapsed_seconds
    await db.commit()
    await sink(
        session_id,
        events.make_event(
            "COMPLETED",
            data={
                "elapsed_s": float(outcome.elapsed_seconds or 0),
                "cost_usd": round(outcome.cost_usd, 4),
            },
        ),
    )
    # The one place approved research enters project memory (docs/14 §2).
    await _ingest_into_project_memory(db, session, provider_keys or {})


async def run_pipeline(session_id: str, user_id: str) -> None:
    await _execute(session_id, user_id, resume=None)


async def resume_pipeline(
    session_id: str, user_id: str, approved: bool, feedback: str | None
) -> None:
    await _execute(session_id, user_id, resume=(approved, feedback))
