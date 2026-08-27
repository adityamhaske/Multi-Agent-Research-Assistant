"""
Execution wiring: the research engine, persisted into the research domain.

This is an **adapter**, not a second pipeline. `research_engine.runner.run` and `.resume` are
called exactly as `app/workers/pipeline_runner.py` calls them, with the same ports, the same
`RunConfig`, the same LangGraph topology and the same checkpointer. Nothing in
`research_engine/` learns the domain exists — the dependency points one way, from here into the
engine.

    POST /runs ──► ResearchRun (PENDING)
                       │
                       ├─ Celery: run_research_pipeline
                       │    ├─ resolve routing + BYOK + RunConfig   (shared)
                       │    ├─ runner.run(...)                      (unchanged engine)
                       │    ├─ RunOutcome  +  final checkpoint state
                       │    └─ persist_outcome() ──► run_lifecycle ──► run rows
                       │
                       └─ POST /report-review APPROVED ──► Artifact ──► bundle ──► verifier

**Two sources, because the engine has two outputs.** `RunOutcome` carries the report, the
numbered source list, cost and tokens. Evidence and contradictions live in the LangGraph
checkpoint and always have — the session bundle route reads them the same way. So the adapter
reads the final state once, through the tri-state reader, and persists it transactionally.
After that the `evidence` table is authoritative and the checkpoint is execution history.

**The tri-state matters here too.** A run whose checkpoint cannot be read has not gathered
zero evidence; it has an unknown amount. `persist_outcome` records which of the three it was
and refuses to write a revision claiming citations it cannot resolve.

`persist_outcome` is deliberately the seam: pure over (db, run, outcome, state), with no
Celery, no Redis and no HTTP, so the integration test can drive the real engine and then call
it directly.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, replace

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import run_lifecycle
from app.models.research import ResearchRun
from app.models.user import User
from app.runtime import run_config_from_settings
from app.services import model_routing
from app.services.run_config import apply_demo_rule
from research_engine import citation_rate, events
from research_engine.checkpoint_read import CheckpointOutcome, read_checkpoint
from research_engine.runconfig import RunConfig
from research_engine.runner import RunOutcome

logger = structlog.get_logger()

#: Preference keys that map 1:1 onto a `RunConfig` field. Same list the session worker uses; it
#: is imported rather than restated so the two hosts cannot drift on which preferences a
#: run honours.
from app.workers.pipeline_runner import (  # noqa: E402
    _PREFERENCE_FIELDS,
    _preference_overrides,
    _user_provider_keys,
)

__all__ = [
    "PersistResult",
    "persist_outcome",
    "run_config_for_run",
    "provider_keys_for",
    "_PREFERENCE_FIELDS",
]


@dataclass
class PersistResult:
    """What the adapter wrote, and what it declined to write.

    `evidence_outcome` is the tri-state, carried out so a caller can log it and a test can
    assert on it. `revision` is None when the run produced no report — a failed run, or one
    stopped at a gate.
    """

    status: str
    evidence_outcome: str
    source_count: int = 0
    evidence_count: int = 0
    revision_version: int | None = None
    claim_count: int = 0
    link_count: int = 0
    contradiction_count: int = 0


async def provider_keys_for(db: AsyncSession, owner_id: uuid.UUID) -> dict[str, str]:
    """This run's BYOK keys. Shared with the session worker — one decrypt path, one fallback."""
    return await _user_provider_keys(db, str(owner_id))


async def run_config_for_run(db: AsyncSession, run: ResearchRun) -> RunConfig:
    """The engine config for a run.

    Deliberately the same resolution order as the session worker — run → user → deployment — and
    the same snapshot rule: once `model_routing` is stamped on the run it wins, so a resumed
    run keeps the models it started with rather than producing a report whose halves were
    written by different models.
    """
    user = (await db.execute(select(User).where(User.id == run.owner_id))).scalar_one_or_none()

    routing = model_routing.resolve(
        session_routing=run.model_routing,
        user_routing=(user.model_routing if user else None),
    )
    if run.model_routing != routing:
        run.model_routing = routing
        await db.flush()

    base = run_config_from_settings()
    overrides = _preference_overrides(user)
    overrides |= {
        "skip_plan_gate": bool(run.skip_plan_gate),
        "topic_seeds": tuple(run.topic_seeds or ()),
        "outline_template": run.outline_template,
    }
    # The demo rule, shared with the session worker and both desktop drivers — see
    # `app/services/run_config.py` for why it is one branch and why it has to be one home.
    config, needs_stamp = apply_demo_rule(
        base, row_demo=bool(run.demo), host_is_scripted=base.llm_mode == "fake"
    )
    if needs_stamp:
        run.demo = True
        await db.flush()
    return replace(config, models=routing, **overrides)


async def persist_outcome(
    db: AsyncSession,
    run: ResearchRun,
    outcome: RunOutcome,
    *,
    saver=None,
    state: dict | None = None,
) -> PersistResult:
    """Write one graph invocation's result into the research domain. Caller owns the transaction.

    `state` is the final checkpoint values; pass it directly (a test that already has them)
    or pass `saver` and let this read them through the tri-state reader. Passing neither
    means the evidence is **unknown**, and that is recorded rather than treated as zero.
    """
    # A run the user stopped stays stopped (issue #54). Cancellation is advisory — nothing
    # interrupts the graph — so the outcome still arrives, minutes later with a real model,
    # and every branch below would move the run out of CANCELLED.
    #
    # Without this the write did not merely mis-record: `ck_run_cancelled` ties CANCELLED to
    # `cancelled_at`, so the UPDATE violated the constraint and raised IntegrityError inside
    # the worker's background task. The status survived (the transaction rolled back) but the
    # spend went with it — a run cancelled after $0.50 recorded $0.00. Guarding here is what
    # turns an accidental save-by-constraint into a decision, and keeps the money.
    #
    # Spend is committed because tokens burned between the stop and the pipeline noticing are
    # real; dropping them would make usage totals lie. Nothing else is written: the run's own
    # conclusion is not the user's decision, and the user's decision is the one that stands.
    #
    # Two more homes of this rule for sessions — `pipeline_runner._persist_outcome` and
    # `sidecar._apply_outcome`. Change all three.
    if run.status == "CANCELLED":
        await run_lifecycle.record_metrics(
            db,
            run,
            cost_usd=outcome.cost_usd,
            tokens_input=outcome.tokens_input,
            tokens_output=outcome.tokens_output,
            elapsed_seconds=outcome.elapsed_seconds,
        )
        logger.info(
            "outcome_discarded_run_cancelled",
            run_id=str(run.id),
            outcome_status=outcome.status,
            cost_usd=round(outcome.cost_usd, 4),
        )
        return PersistResult(status="CANCELLED", evidence_outcome="NOT_READ")

    if outcome.status == "failed":
        await run_lifecycle.record_failure(db, run, outcome.error)
        return PersistResult(status="FAILED", evidence_outcome="NOT_READ")

    # ── the plan gate ─────────────────────────────────────────────────────────────
    if outcome.status == "awaiting_plan":
        # The proposal, not a decision: `approved_at` stays NULL until a PLAN review
        # stamps it, and `origin` says the model wrote it.
        await run_lifecycle.record_plan(
            db,
            run,
            tasks=outcome.plan_tasks,
            outline_sections=outcome.plan_outline,
            origin="MODEL_PROPOSED",
        )
        await run_lifecycle.record_metrics(
            db,
            run,
            cost_usd=outcome.cost_usd,
            tokens_input=outcome.tokens_input,
            tokens_output=outcome.tokens_output,
        )
        await run_lifecycle.set_status(db, run, "AWAITING_PLAN")
        return PersistResult(status="AWAITING_PLAN", evidence_outcome="NOT_READ")

    # ── evidence, from the checkpoint, tri-state ──────────────────────────────────
    evidence_outcome = "NOT_READ"
    values: dict = {}
    if state is not None:
        evidence_outcome, values = "READ", state
    elif saver is not None:
        read = await read_checkpoint(saver, str(run.id))
        if read.outcome is CheckpointOutcome.READ:
            evidence_outcome, values = "READ", read.values
        elif read.outcome is CheckpointOutcome.MISSING:
            evidence_outcome = "CHECKPOINT_MISSING"
        else:
            evidence_outcome = "CHECKPOINT_UNREADABLE"

    written = None
    if evidence_outcome == "READ":
        evidence = [e for e in (values.get("evidence") or []) if isinstance(e, dict)]
        # An evidence item with no `source_url` has no identity anywhere, and
        # `record_evidence` refuses the whole batch rather than invent one. The engine's
        # own numbering skips such items too, so dropping them here loses nothing the
        # report could have cited — but it IS a drop, so it is counted and logged.
        usable = [e for e in evidence if (e.get("source_url") or "").strip()]
        if len(usable) != len(evidence):
            logger.warning(
                "evidence_without_source_url_skipped",
                run_id=str(run.id),
                skipped=len(evidence) - len(usable),
            )
        written = await run_lifecycle.record_evidence(
            db, run, evidence=usable, numbered_sources=outcome.sources
        )

    # ── the revision, its claims and their links ──────────────────────────────────
    revision_version = claim_count = link_count = 0
    report = outcome.report
    if report:
        result = await run_lifecycle.record_revision(
            db, run, report_markdown=report, evidence_index=written
        )
        revision_version = result.revision.version
        claim_count, link_count = result.claim_count, result.link_count

    # ── contradictions ────────────────────────────────────────────────────────────
    contradiction_count = 0
    if evidence_outcome == "READ":
        pairs = [c for c in (values.get("contradictions") or []) if isinstance(c, dict)]
        # `detector_ran=True` even for an empty list: the engine runs the detector on every
        # non-corpus path and surfaces nothing when it is unavailable, so "no pairs" here is
        # a measured absence. A caller that knows the detector was skipped passes False.
        contradiction_count = await run_lifecycle.record_contradictions(
            db, run, pairs=pairs, evidence_index=written
        )

    # ── metrics and status ────────────────────────────────────────────────────────
    rate = None
    if outcome.status == "completed" and report:
        # Measured once, when the report becomes final — the same rule and the same
        # function the session worker uses. NULL when there was nothing to measure.
        rate = citation_rate.resolution_rate(report, outcome.sources)
    await run_lifecycle.record_metrics(
        db,
        run,
        cost_usd=outcome.cost_usd,
        tokens_input=outcome.tokens_input,
        tokens_output=outcome.tokens_output,
        elapsed_seconds=outcome.elapsed_seconds,
        citation_resolution_rate=rate,
    )

    # Persisted, not merely logged. Whether the evidence was ever read is what separates a
    # measured zero from an unmeasured one, and `run_bundle` has to be able to ask the run
    # itself — a log line cannot be consulted at export time.
    run.evidence_outcome = evidence_outcome

    status = run_lifecycle.OUTCOME_STATUS.get(outcome.status, "RUNNING")
    if status == "COMPLETED" and not report:
        # A completed run with no report is not completed. Fail closed rather than mark a
        # run finished with nothing to review.
        await run_lifecycle.record_failure(db, run, "the graph completed without a report")
        status = "FAILED"
    else:
        await run_lifecycle.set_status(db, run, status)

    return PersistResult(
        status=status,
        evidence_outcome=evidence_outcome,
        source_count=written.source_count if written else 0,
        evidence_count=written.evidence_count if written else 0,
        revision_version=revision_version or None,
        claim_count=claim_count,
        link_count=link_count,
        contradiction_count=contradiction_count,
    )


def lifecycle_event(result: PersistResult) -> dict:
    """The event a host publishes after `persist_outcome`, in the existing vocabulary.

    Reuses `research_engine.events.make_event` and the same four names the session stream and
    both hosts' stop-lists already know (`PLAN_READY`, `HITL_READY`, `COMPLETED`, `FAILED`),
    so no second event architecture appears and no stream is left waiting on a name nothing
    publishes.
    """
    if result.status == "AWAITING_PLAN":
        return events.make_event("PLAN_READY", data={"run_id": None})
    if result.status == "AWAITING_REVIEW":
        return events.make_event(
            "HITL_READY",
            data={
                "revision_version": result.revision_version,
                "source_count": result.source_count,
                "evidence_count": result.evidence_count,
                "contradiction_count": result.contradiction_count,
            },
        )
    if result.status == "FAILED":
        return events.make_event("FAILED", data={"reason": "see error_message"})
    # A cancelled run reports FAILED rather than a name of its own (issue #54). `CANCELLED`
    # is not in `_TERMINAL_EVENTS` on either host, so inventing it here would leave the
    # stream open on a run that will never publish again — and the fall-through below would
    # otherwise tell the UI a run the user stopped had COMPLETED. `POST /{id}/cancel`
    # publishes nothing itself, so this is the event that actually closes the stream.
    if result.status == "CANCELLED":
        return events.make_event("FAILED", data={"reason": "Research stopped by user."})
    return events.make_event(
        "COMPLETED",
        data={
            "revision_version": result.revision_version,
            "claim_count": result.claim_count,
            # The tri-state, carried into the event: a UI must be able to tell "no
            # evidence" from "evidence unknown".
            "evidence_outcome": result.evidence_outcome,
        },
    )


# ── The worker driver ─────────────────────────────────────────────────────────────
#
# Everything above is host-free. This part is the server's half — the run lock, one DB
# session scope, the Postgres checkpointer, the event sink — and it is deliberately a near
# mirror of `pipeline_runner._execute` rather than a new design. The differences are the
# row it loads (`ResearchRun`) and where the outcome goes (`persist_outcome`).


async def execute_run(
    run_id: str,
    *,
    resume: tuple[bool, str | None] | None = None,
    plan: dict | None = None,
) -> None:
    """Drive one run through the engine and persist it into the research domain."""
    from app import adapters
    from app.config import settings
    from app.db.base import AsyncSessionLocal, engine
    from app.db.redis import (
        acquire_session_lock,
        close_redis_pool,
        init_redis_pool,
        release_session_lock,
    )
    from research_engine import runner

    lock_token = uuid.uuid4().hex
    await init_redis_pool()
    try:
        # Celery can redeliver, so double execution is a real risk here in a way it is not
        # in a single-process desktop app. Same lock, same key space as the session worker.
        if not await acquire_session_lock(
            run_id, lock_token, ttl=settings.celery_task_timeout_seconds + 60
        ):
            logger.warning("run_lock_busy", run_id=run_id)
            return
        try:
            async with AsyncSessionLocal() as db:
                run = (
                    await db.execute(select(ResearchRun).where(ResearchRun.id == uuid.UUID(run_id)))
                ).scalar_one_or_none()
                if run is None:
                    logger.error("run_not_found", run_id=run_id)
                    return

                # "No new research will be started for this run" is what `POST /cancel`
                # tells the caller, in those words. Without this it was not true: a resume
                # dispatched after the cancel — approving the plan of a run you had just
                # stopped — started the pipeline again, and the `set_status` below wrote
                # RUNNING over CANCELLED, violating `ck_run_cancelled` and killing the task
                # on an IntegrityError. Observed live before this guard existed.
                #
                # Returning rather than raising: the run is already in the terminal state
                # the user asked for, nothing is wrong, and there is nothing new to publish
                # — the stream closed when the cancel did.
                if run.status == "CANCELLED":
                    logger.info("run_start_skipped_cancelled", run_id=run_id)
                    return

                await run_lifecycle.set_status(db, run, "RUNNING")
                await db.commit()

                sink = adapters.agent_log_sink(db, run_id)
                ports = {
                    "provider_keys": await provider_keys_for(db, run.owner_id),
                    "event_sink": sink,
                    "cache": adapters.RedisCache(),
                    "run_config": await run_config_for_run(db, run),
                }
                await db.commit()

                if run.corpus_mode:
                    guard = await _corpus_port(db, run, ports)
                    if guard is not None:
                        await run_lifecycle.record_failure(db, run, guard)
                        await db.commit()
                        await sink(run_id, events.make_event("FAILED", data={"reason": guard}))
                        return

                from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

                dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
                async with AsyncPostgresSaver.from_conn_string(dsn) as saver:
                    await saver.setup()
                    if plan is not None:
                        outcome = await runner.resume(
                            checkpointer=saver, session_id=run_id, plan=plan, **ports
                        )
                    elif resume is None:
                        outcome = await runner.run(
                            checkpointer=saver,
                            session_id=run_id,
                            user_id=str(run.owner_id),
                            query=run.question,
                            depth=run.depth,
                            **ports,
                        )
                    else:
                        approved, feedback = resume
                        outcome = await runner.resume(
                            checkpointer=saver,
                            session_id=run_id,
                            approved=approved,
                            feedback=feedback,
                            **ports,
                        )
                    # Read the state INSIDE the saver context: the evidence lives there and
                    # the connection closes on exit.
                    result = await persist_outcome(db, run, outcome, saver=saver)

                # Persist, commit, then publish — a client acting on COMPLETED must never
                # re-read a status that has not caught up.
                await db.commit()
                await sink(run_id, lifecycle_event(result))
                logger.info(
                    "run_persisted",
                    run_id=run_id,
                    status=result.status,
                    evidence_outcome=result.evidence_outcome,
                    evidence=result.evidence_count,
                    claims=result.claim_count,
                )
        finally:
            await release_session_lock(run_id, lock_token)
    finally:
        await close_redis_pool()
        await engine.dispose()


async def _corpus_port(db: AsyncSession, run: ResearchRun, ports: dict) -> str | None:
    """Attach the corpus store, or return the reason the run cannot proceed.

    Both guards are the session worker's, unchanged: a remote embedder would egress the corpus,
    and a missing corpus database means the documents were never ingested. Returning the
    reason rather than raising keeps the caller's failure path in one place.
    """
    from app import adapters
    from app.config import settings
    from research_engine.corpus import CorpusStore

    embedder = await adapters.embeddings_for(ports["provider_keys"])
    if not (embedder.model_id.startswith("ollama:") or embedder.model_id.startswith("local:")):
        return f"Corpus mode requires a local embedder (Ollama), but got {embedder.model_id}."
    db_path = settings.corpus_path / f"corpus_{run.project_id}.sqlite"
    if not db_path.exists():
        return f"Corpus database not found for project {run.project_id}. Ingest documents first."
    ports["corpus"] = CorpusStore(db_path, embedder)
    return None
