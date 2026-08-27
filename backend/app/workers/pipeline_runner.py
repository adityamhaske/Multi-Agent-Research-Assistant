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
from app.services.run_config import apply_demo_rule
from app.services.session_events import lifecycle_event
from research_engine import citation_rate, events, runner
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
    keys = {user.api_key_provider: plaintext}
    if user.api_key_base_url:
        keys[f"{user.api_key_provider}_base_url"] = user.api_key_base_url
    return keys


#: Preference keys that map 1:1 onto a `RunConfig` field of the same name (docs/07 §2,
#: Phase 3). `None`/absent means "use the deployment default" — the class default
#: already is that default, so an unset preference contributes nothing to `replace()`.
_PREFERENCE_FIELDS = (
    "retrieval_k",
    "min_sources_per_task",
    "snippet_max_chars",
    "tavily_api_key",
    "brave_api_key",
)


def _preference_overrides(user: User | None) -> dict:
    prefs = (user.preferences if user else None) or {}
    return {k: prefs[k] for k in _PREFERENCE_FIELDS if prefs.get(k) is not None}


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

    base = run_config_from_settings()
    overrides = _preference_overrides(user)
    # The research design gate (docs/07 §2, Phase 4), now that the whole resume path
    # exists: SessionStatus.AWAITING_PLAN, `runner.resume(plan=…)`, the `resume_plan_gate`
    # task, and `GET/POST /research/{id}/plan`. Sourced from the session row rather than
    # the request because this is rebuilt on every resume, long after the request is gone.
    # `RunConfig`'s own defaults stay the un-gated ones for callers with no opinion (the
    # CLI, the eval harness); this is where a *hosted* run states its. Desktop
    # counterpart: `sidecar._drive_session`.
    overrides |= {
        "skip_plan_gate": bool(session.skip_plan_gate),
        "topic_seeds": tuple(session.topic_seeds or ()),
        "outline_template": session.outline_template,
    }
    # Scripted models and fixture retrievers (docs/17 §6.2). The rule — a run that reached
    # no provider is *recorded* as a demo, whichever way it got there — is one function, in
    # `app/services/run_config.py`, called by both hosts. It used to be this branch plus
    # three more, kept in step by a note in AGENTS.md.
    config, needs_stamp = apply_demo_rule(
        base, row_demo=bool(session.demo), host_is_scripted=base.llm_mode == "fake"
    )
    if needs_stamp:
        session.demo = True
        await db.commit()
    return replace(config, models=routing, **overrides)


async def _execute(
    session_id: str,
    user_id: str,
    *,
    resume: tuple[bool, str | None] | None,
    plan: dict | None = None,
) -> None:
    """Drive one session through the engine end to end: lock, wire ports, resume-or-run.

    `resume`/`plan` select which of three engine entry points this call is (fresh start,
    plan-gate resume, hitl-gate resume) — see the branch below. All three share the same
    lock, the same Postgres checkpointer and the same corpus guard, because a session that
    can start any of these three ways must not be able to start the other two
    concurrently.

    The session lock is acquired first and released last (the `finally` chain), because
    Celery can redeliver a task — unlike the desktop's single in-process host, more than
    one worker can legitimately pick up the same `session_id` here. A busy lock is not an
    error: the caller that lost the race simply returns, trusting the caller that holds it
    to finish and persist the outcome.

    The corpus-mode guard (local embedder required, corpus database must already exist)
    runs *before* the checkpointer is opened, so a run that cannot proceed fails with a
    clear reason instead of spending a database round trip first.
    """
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

                if session.corpus_mode:
                    from research_engine.corpus import CorpusStore

                    embedder = await adapters.embeddings_for(ports["provider_keys"])
                    # Egress guard: require local embedder for airgapped mode
                    if not (
                        embedder.model_id.startswith("ollama:")
                        or embedder.model_id.startswith("local:")
                    ):
                        session.status = SessionStatus.FAILED
                        session.error_message = f"Corpus mode requires a local embedder (Ollama), but got {embedder.model_id}."
                        await db.commit()
                        await sink(
                            session_id,
                            events.make_event("FAILED", data={"reason": session.error_message}),
                        )
                        return

                    # Must be `corpus_path`, matching app/api/v1/corpus.py. The worker and
                    # the API are separate processes with their own working directories,
                    # so resolving a relative setting independently is what let a document
                    # upload succeed and then be invisible to the run that needed it.
                    db_path = settings.corpus_path / f"corpus_{session.project_id}.sqlite"
                    if not db_path.exists():
                        session.status = SessionStatus.FAILED
                        session.error_message = f"Corpus database not found for project {session.project_id}. Ingest documents first."
                        await db.commit()
                        await sink(
                            session_id,
                            events.make_event("FAILED", data={"reason": session.error_message}),
                        )
                        return

                    ports["corpus"] = CorpusStore(db_path, embedder)

                async with AsyncPostgresSaver.from_conn_string(_checkpointer_dsn()) as saver:
                    await saver.setup()
                    if plan is not None:
                        # Resuming the design gate (docs/07 §2, Phase 4).
                        outcome = await runner.resume(
                            checkpointer=saver, session_id=session_id, plan=plan, **ports
                        )
                    elif resume is None:
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
            logger.info("memory_ingest_skipped", session_id=str(session.id), reason=result.reason)
    except Exception as e:  # noqa: BLE001 — see docstring: never fail a completed run
        await db.rollback()
        logger.warning(
            "memory_ingest_failed",
            session_id=str(session.id),
            project_id=str(session.project_id),
            error=str(e),
        )


async def _ingest_report_into_corpus(session: Session, provider_keys: dict[str, str]) -> None:
    """Auto-save this approved report into its project's corpus (app/services/report_corpus.py).

    Same transition as `_ingest_into_project_memory` and the same reason: never fail an
    already-committed run over it. Uses whatever embedder the deployment resolves to —
    unlike corpus-mode *search*, ingestion is not required to be local (the upload route
    ingests uploads the same way), so a hosted embedder here is not an egress violation.
    """
    try:
        from app import adapters
        from app.config import settings
        from app.services.report_corpus import ingest_report
        from research_engine.corpus import CorpusStore

        settings.corpus_path.mkdir(parents=True, exist_ok=True)
        db_path = settings.corpus_path / f"corpus_{session.project_id}.sqlite"
        embedder = await adapters.embeddings_for(provider_keys)
        store = CorpusStore(db_path, embedder)
        await ingest_report(store, session_id=str(session.id), report_markdown=session.final_report)
    except Exception as e:  # noqa: BLE001 — see report_corpus.ingest_report's own docstring
        logger.warning(
            "report_corpus_ingest_setup_failed",
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

    # A run the user stopped stays stopped (issue #54). Cancellation does not interrupt the
    # pipeline — it keeps going to its next checkpoint — so without this guard the outcome
    # arriving minutes later moved the session back to AWAITING_APPROVAL or COMPLETED. The
    # user saw a stopped run, then a live one, and approving it put a report they had tried
    # to abandon into project memory.
    #
    # The spend assigned above is committed regardless: tokens burned between the stop and
    # the pipeline noticing are real money, and dropping them would make usage totals lie.
    # Everything that describes the run's *conclusion* is withheld — status, the reports,
    # `sources`, and the lifecycle event — because the conclusion is not the user's decision
    # and the decision is the one that stands.
    #
    # Two more homes of this rule: `desktop/sidecar.py::_apply_outcome` for the desktop's
    # session journey, and `run_execution.persist_outcome` for runs. Change all three.
    if session.is_cancelled:
        await db.commit()
        logger.info(
            "outcome_discarded_session_cancelled",
            session_id=session_id,
            outcome_status=outcome.status,
            cost_usd=round(outcome.cost_usd, 4),
        )
        return

    session.sources = outcome.sources

    if outcome.status == "awaiting_plan":
        # The research design gate (docs/07 §2, Phase 4). Persisted before the event
        # leaves, same ordering as every other branch here: a client that acts on
        # PLAN_READY and immediately GETs /plan must not read a row that has not caught
        # up yet. `plan_approved_at` stays null — this is the proposal, not a decision;
        # `POST /{id}/plan` stamps it.
        session.status = SessionStatus.AWAITING_PLAN
        session.plan_json = {"tasks": outcome.plan_tasks}
        session.outline_json = {"sections": outcome.plan_outline}
        await db.commit()
        await sink(session_id, lifecycle_event(outcome))
        return

    if outcome.status == "awaiting_approval":
        session.status = SessionStatus.AWAITING_APPROVAL
        session.draft_report = outcome.draft_report
        await db.commit()
        await sink(session_id, lifecycle_event(outcome))
        return

    if outcome.status == "failed":
        session.status = SessionStatus.FAILED
        session.error_message = outcome.error
        await db.commit()
        await sink(session_id, lifecycle_event(outcome))
        return

    session.status = SessionStatus.COMPLETED
    session.final_report = outcome.final_report
    session.elapsed_seconds = outcome.elapsed_seconds
    # Computed once, at the moment the report becomes final, rather than per list request
    # — the same reason `model_routing` is snapshotted. Desktop counterpart:
    # `sidecar._apply_outcome`.
    session.citation_resolution_rate = citation_rate.resolution_rate(
        outcome.final_report or "", outcome.sources
    )
    await db.commit()
    await sink(session_id, lifecycle_event(outcome))
    # The one place approved research enters project memory (docs/14 §2).
    await _ingest_into_project_memory(db, session, provider_keys or {})
    # And its project's corpus (docs/12 M10 follow-up) — see report_corpus.py.
    await _ingest_report_into_corpus(session, provider_keys or {})


async def run_pipeline(session_id: str, user_id: str) -> None:
    await _execute(session_id, user_id, resume=None)


async def resume_pipeline(
    session_id: str, user_id: str, approved: bool, feedback: str | None
) -> None:
    await _execute(session_id, user_id, resume=(approved, feedback))


async def resume_plan(session_id: str, user_id: str, plan: dict) -> None:
    """Resume a session paused at the research design gate with the reviewer's edits."""
    await _execute(session_id, user_id, resume=None, plan=plan)
