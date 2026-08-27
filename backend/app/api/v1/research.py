"""
Research endpoints (docs/05 §3, docs/02 §2/§5).

Auth is cookie-based (works with native EventSource). The SSE stream replays the
durable agent_logs (honoring Last-Event-ID) before tailing live Redis events, so a
reconnecting client loses nothing. Approval writes an audit_log row and resumes the
pipeline from its checkpoint.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.projects import resolve_project
from app.db.base import AsyncSessionLocal, get_db
from app.db.redis import get_redis
from app.dependencies import enforce_research_rate_limit, get_current_user
from app.logconfig import bind_run_context
from app.models.agent_log import AgentLog
from app.models.audit_log import AuditLog
from app.models.session import Session, SessionStatus
from app.models.user import User
from app.schemas.research import (
    ApprovalRequest,
    OutlineSectionSchema,
    OutlineTemplateSchema,
    PlanDecisionRequest,
    PlanResponse,
    PlanTaskSchema,
    ResearchStartRequest,
    ResearchStartResponse,
    SessionDetail,
    SessionListResponse,
    SessionSummary,
)
from app.services import checkpoints, export, model_routing, usage
from app.services.event_stream import sse_frames
from app.services.sse import SSE_HEADERS
from app.workers.tasks import resume_agent_pipeline, resume_plan_gate, run_agent_pipeline
from research_engine import bundle

#: Replay ends at a true terminal only; the live tail also ends at a gate, because a
#: suspended graph publishes nothing more until a human acts. Both hosts and both surfaces
#: use these two lists — see `app/services/event_stream.py` for why they must differ.
_REPLAY_STOP_EVENTS = ("COMPLETED", "FAILED")
_TERMINAL_EVENTS = ("COMPLETED", "FAILED", "HITL_READY", "PLAN_READY")

logger = structlog.get_logger()
router = APIRouter(prefix="/research", tags=["Research"])


@router.post("", response_model=ResearchStartResponse, status_code=202)
async def start_research(
    payload: ResearchStartRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _rl: None = Depends(enforce_research_rate_limit),
):
    # Monthly token ceiling (0 = unlimited). Checked before enqueueing so a
    # capped user gets a clear 402 instead of a session that fails mid-run.
    if current_user.monthly_token_limit > 0:
        used = await usage.monthly_tokens(db, current_user.id)
        if used >= current_user.monthly_token_limit:
            raise HTTPException(
                status.HTTP_402_PAYMENT_REQUIRED,
                detail=(
                    f"Monthly token limit reached ({used:,} of "
                    f"{current_user.monthly_token_limit:,}). It resets on the 1st, or you "
                    "can add your own API key in Settings."
                ),
            )

    # Per-run model choice, validated here so an unroutable model is rejected before a
    # session exists rather than failing inside the worker minutes later. None means
    # "use my saved settings", which the runner resolves (user → deployment).
    routing = None
    if payload.model_routing:
        try:
            routing = model_routing.validate(payload.model_routing)
        except model_routing.InvalidRouting as e:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)) from e

    # Resolve the target project (404s if it isn't this user's), or fall back to their
    # default so a first-time account can start research without creating one first.
    project = await resolve_project(db, current_user.id, payload.project_id)

    session = Session(
        user_id=current_user.id,
        project_id=project.id,
        prompt=payload.query,
        status=SessionStatus.PENDING,
        research_depth=payload.depth,
        model_routing=routing,
        # Both of these were accepted by the request schema and then dropped on the floor:
        # the session took the column default instead, so "Restrict to uploaded corpus"
        # silently ran an ordinary web search. Persist what the caller actually asked for.
        corpus_mode=payload.corpus_mode,
        demo=payload.demo,
        # Research design gate (docs/07 §2, Phase 4). Same rule as the two above and the
        # same reason they are commented: a request field that never reaches the row is
        # a promise the run does not keep. `_run_config_for` reads all three back.
        skip_plan_gate=payload.skip_plan_gate,
        topic_seeds=payload.topic_seeds or None,
        outline_template=payload.outline_template,
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)

    run_agent_pipeline.delay(str(session.id), str(current_user.id))
    # Bind the run's correlation identity so the trigger log joins with the Celery
    # task and engine logs under one correlation_id (= session_id).
    bind_run_context(str(session.id), user_id=str(current_user.id))
    logger.info("research_started", session_id=str(session.id))
    return ResearchStartResponse(session_id=session.id, status=session.status)


@router.get("", response_model=SessionListResponse)
async def list_sessions(
    page: int = 1,
    limit: int = 20,
    archived: bool = False,
    project_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List this user's sessions, optionally scoped to one project.

    `archived` selects one list or the other rather than merging them: archiving exists
    to get a session *out* of the way, so the default view must never include it, and
    the archive is a deliberate destination rather than a filter people stumble into.

    `project_id` is validated for ownership before it reaches the query, so it can never
    be used to read another user's project.
    """
    limit = max(1, min(limit, 100))
    filters = [
        Session.user_id == current_user.id,
        Session.archived_at.is_not(None) if archived else Session.archived_at.is_(None),
    ]
    if project_id is not None:
        project = await resolve_project(db, current_user.id, project_id)
        filters.append(Session.project_id == project.id)
    base = select(Session).where(*filters)
    total = (await db.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
    rows = (
        (
            await db.execute(
                base.order_by(Session.created_at.desc()).offset((page - 1) * limit).limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return SessionListResponse(
        sessions=[SessionSummary.model_validate(s) for s in rows],
        total=total,
        page=page,
        limit=limit,
    )


@router.get("/outline-templates", response_model=list[OutlineTemplateSchema])
async def list_outline_templates(_: User = Depends(get_current_user)):
    """The report structures offered at the design gate (docs/07 §2, Phase 4).

    Served from `research_engine.outlines` rather than hardcoded in the picker, so the
    sections the UI previews are the sections the synthesizer is actually given. Declared
    above `/{session_id}` because that route parses its segment as a UUID and would 422
    this path rather than falling through to it.
    """
    from research_engine import outlines

    return [OutlineTemplateSchema.model_validate(t) for t in outlines.catalog()]


@router.get("/{session_id}", response_model=SessionDetail)
async def get_session(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    session = await _authorized_session(db, session_id, current_user.id)
    return SessionDetail.model_validate(session)


@router.get("/{session_id}/stream")
async def stream_events(
    session_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    redis=Depends(get_redis),
):
    await _authorized_session(db, session_id, current_user.id)
    last_event_id = request.headers.get("last-event-id")
    after_id = int(last_event_id) if last_event_id and last_event_id.isdigit() else 0

    async def gen() -> AsyncGenerator[str, None]:
        from app import adapters

        channel = f"session:{session_id}:events"
        pubsub = redis.pubsub()
        # Subscribe BEFORE snapshotting the backlog. Any event published in the gap
        # between the snapshot and the subscribe would otherwise be lost from both —
        # which stranded fast resume→COMPLETED runs on the monitor. Now such an event
        # is queued on the pubsub and deduped against the backlog by its durable id.
        await pubsub.subscribe(channel)
        try:
            # Snapshot the backlog AFTER subscribing. Uses a fresh session because the
            # request-scoped one is closed once the endpoint returns and streaming begins.
            async with AsyncSessionLocal() as sdb:
                backlog = (
                    (
                        await sdb.execute(
                            select(AgentLog)
                            .where(AgentLog.session_id == session_id, AgentLog.id > after_id)
                            .order_by(AgentLog.id.asc())
                        )
                    )
                    .scalars()
                    .all()
                )

            # The loop is `app/services/event_stream.py`, shared with the run stream and
            # both desktop streams. This route keeps only what genuinely differs: the
            # backlog query and the Redis subscription.
            async for frame in sse_frames(
                connected={"type": "connected"},
                backlog=[(row.id, row.payload) for row in backlog],
                live=adapters.redis_event_stream(pubsub),
                replay_stop=_REPLAY_STOP_EVENTS,
                terminal_stop=_TERMINAL_EVENTS,
                already_done=False,
                seen_from=after_id,
            ):
                yield frame
        finally:
            await pubsub.unsubscribe(channel)
            await pubsub.aclose()

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


#: The demo banner and the "stamped iff demo" rule now live in `research_engine.bundle`,
#: the host-agnostic export home, so the desktop sidecar stamps `.md` identically (#52).
#: Aliased here because this module and `runs` have always referred to `_DEMO_STAMP`.
_DEMO_STAMP = bundle.DEMO_STAMP_MD


def _report_or_404(session: Session, *, stamp_demo: bool = True) -> str:
    """The report to export, stamped in place if this session was a demo.

    Every export route funnels through here on purpose, and stamping is the default:
    stamping at each call site would work until someone adds a fourth export and forgets,
    and an unstamped demo report is indistinguishable from real research the moment it
    leaves the app.

    `stamp_demo=False` exists for exactly one caller, the bundle. A bundle is a
    *verifiable* artifact: `report_hash` is checked against the `draft_hash` recorded when
    the human approved the draft, so injecting prose into the report body afterwards
    breaks the approval chain and makes every demo bundle fail verification for a reason
    that has nothing to do with its integrity. Teaching a reader that FAIL is normal for
    demos would defeat the verifier far more thoroughly than a missing banner. The bundle
    carries its provenance in the hash-covered `demo` field instead, and the verifier
    prints it above the verdict.
    """
    report = session.final_report or session.draft_report
    if not report:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="No report available to export.")
    return bundle.stamp_demo_md(report, demo=bool(session.demo) and stamp_demo)


@router.get("/{session_id}/export.md")
async def export_markdown(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    session = await _authorized_session(db, session_id, current_user.id)
    report = _report_or_404(session) + export.render_model_attribution_md(session.model_routing)
    filename = f"research-{str(session.id)[:8]}.md"
    return Response(
        content=report,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{session_id}/export.pdf")
async def export_pdf(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    session = await _authorized_session(db, session_id, current_user.id)
    report = _report_or_404(session)
    title = (session.prompt or "Research Report")[:120]
    try:
        pdf = export.render_pdf(
            report, session.sources or [], title=title, model_routing=session.model_routing
        )
    except RuntimeError as e:
        # Native PDF libs unavailable in this environment (docs/09 §1 bakes them in).
        raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, detail=str(e)) from e
    filename = f"research-{str(session.id)[:8]}.pdf"
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{session_id}/export.bundle.json")
async def export_bundle_json(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    session = await _authorized_session(db, session_id, current_user.id)
    if session.status != SessionStatus.COMPLETED:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="Bundle export is only available for COMPLETED sessions.",
        )

    # Unstamped on purpose — see `_report_or_404`. The bundle's `demo` field carries the
    # provenance and is covered by `bundle_hash`; prose in the report body would break the
    # approval-chain check instead.
    report = _report_or_404(session, stamp_demo=False)

    agent_logs = (
        (
            await db.execute(
                select(AgentLog)
                .where(AgentLog.session_id == session.id)
                .order_by(AgentLog.id.asc())
            )
        )
        .scalars()
        .all()
    )
    trace = [log.payload for log in agent_logs]

    audit_logs = (
        (
            await db.execute(
                select(AuditLog)
                .where(AuditLog.session_id == session.id)
                .order_by(AuditLog.id.asc())
            )
        )
        .scalars()
        .all()
    )
    approval_chain = [
        {
            "action": al.action,
            "feedback": al.feedback,
            "draft_hash": al.draft_hash,
            "timestamp": al.created_at.isoformat(),
        }
        for al in audit_logs
    ]

    state = await checkpoints.get_thread_state(str(session.id))
    evidence = state.get("evidence", [])
    contradictions = state.get("contradictions", [])

    from research_engine import bundle

    manifest = bundle.assemble(
        session_id=str(session.id),
        query=session.prompt,
        report=report,
        evidence=evidence,
        sources=session.sources or [],
        contradictions=contradictions,
        models=session.model_routing or {},
        cost_usd=float(session.total_cost_usd),
        tokens_input=session.total_tokens_input,
        tokens_output=session.total_tokens_output,
        elapsed_seconds=float(session.elapsed_seconds) if session.elapsed_seconds else None,
        research_depth=session.research_depth,
        approval_chain=approval_chain,
        trace=trace,
        trace_available=True,
        demo=session.demo,
    )

    filename = f"research-{str(session.id)[:8]}.bundle.json"
    return Response(
        content=bundle.serialize(manifest),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _plan_response(session: Session) -> PlanResponse:
    plan = session.plan_json or {}
    outline = session.outline_json or {}
    return PlanResponse(
        session_id=session.id,
        status=session.status,
        tasks=[PlanTaskSchema.model_validate(t) for t in (plan.get("tasks") or [])],
        outline=[OutlineSectionSchema.model_validate(s) for s in (outline.get("sections") or [])],
        approved_at=session.plan_approved_at,
    )


@router.get("/{session_id}/plan", response_model=PlanResponse)
async def get_plan(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """The research design this run is working from (docs/07 §2, Phase 4).

    404 rather than an empty plan when `plan_json` is null: a run that skipped the gate,
    or has not reached it, has no design to show, and returning `{"tasks": []}` for that
    would read as "the planner proposed nothing" — a measurement that was never taken
    rendering as zero, which is the failure mode AGENTS.md opens with.
    """
    session = await _authorized_session(db, session_id, current_user.id)
    if session.plan_json is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail="This session has no research plan to review — it did not use the design gate.",
        )
    return _plan_response(session)


@router.post("/{session_id}/plan", response_model=PlanResponse)
async def submit_plan(
    session_id: uuid.UUID,
    payload: PlanDecisionRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Approve the research design, with edits, and let the run continue.

    Mirrors `approve_or_rework` deliberately, down to the 409: resuming a thread that is
    not suspended at `plan_gate_node` would push a plan-shaped payload into whichever
    interrupt is actually pending, and `hitl_gate_node` reads `decision["approved"]` —
    absent here — as a rejection, silently counting a rework nobody asked for.

    The decision is written to the row *before* the resume is queued, so the record of
    what a human chose survives a worker that dies mid-run. That is the same ordering
    the approval path uses for its `AuditLog`, and for the same reason: the human's
    decision is evidence, and evidence is written when it is made.
    """
    session = await _authorized_session(db, session_id, current_user.id)
    if session.status != SessionStatus.AWAITING_PLAN:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=f"Session must be AWAITING_PLAN (currently {session.status}).",
        )

    proposed = (session.plan_json or {}).get("tasks") or []
    # None means "unedited" — keep the proposal. Not the same as `[]`, which is a
    # reviewer who excluded everything and gets the 422 below.
    tasks = [t.model_dump() for t in payload.tasks] if payload.tasks is not None else proposed
    outline = (
        [s.model_dump() for s in payload.outline]
        if payload.outline is not None
        else (session.outline_json or {}).get("sections") or []
    )

    kept = [t for t in tasks if t.get("include", True)]
    if not kept:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Keep at least one task — a plan with nothing in it researches nothing.",
        )

    # Store what was decided, not what was proposed: `kept` is the list the executor will
    # actually run, so a later reader of this endpoint sees the design behind the report.
    session.plan_json = {"tasks": kept}
    session.outline_json = {"sections": outline}
    session.plan_approved_at = datetime.now(UTC)
    db.add(
        AuditLog(
            session_id=session.id,
            user_id=current_user.id,
            action="plan_approved",
            feedback=None,
            # The design a human signed off on, hashed the same way the draft is at the
            # other gate, so the bundle's approval chain can carry both decisions.
            draft_hash=hashlib.sha256(
                json.dumps({"tasks": kept, "outline": outline}, sort_keys=True).encode("utf-8")
            ).hexdigest(),
        )
    )
    session.status = SessionStatus.RUNNING
    await db.commit()
    await db.refresh(session)

    resume_plan_gate.delay(
        str(session.id), str(current_user.id), {"tasks": kept, "outline": outline}
    )
    bind_run_context(str(session.id), user_id=str(current_user.id))
    logger.info("research_plan_approved", session_id=str(session.id), task_count=len(kept))
    return _plan_response(session)


@router.post("/{session_id}/approve", status_code=200)
async def approve_or_rework(
    session_id: uuid.UUID,
    payload: ApprovalRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    session = await _authorized_session(db, session_id, current_user.id)
    if session.status != SessionStatus.AWAITING_APPROVAL:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=f"Session must be AWAITING_APPROVAL (currently {session.status}).",
        )
    if not payload.approved and session.rework_count >= 3:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="Rework limit reached. Approve or abandon this session.",
        )

    draft_hash = hashlib.sha256((session.draft_report or "").encode("utf-8")).hexdigest()
    db.add(
        AuditLog(
            session_id=session.id,
            user_id=current_user.id,
            action="approved" if payload.approved else "rework_requested",
            feedback=None if payload.approved else payload.feedback,
            draft_hash=draft_hash,
        )
    )
    session.status = SessionStatus.RUNNING
    await db.commit()

    resume_agent_pipeline.delay(
        str(session.id), str(current_user.id), payload.approved, payload.feedback
    )
    bind_run_context(str(session.id), user_id=str(current_user.id))
    logger.info(
        "research_resumed",
        session_id=str(session.id),
        approved=payload.approved,
    )
    return {"message": "Approved. Finalizing." if payload.approved else "Rework requested."}


@router.post("/{session_id}/cancel", response_model=SessionSummary)
async def cancel_session(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Stop an in-progress research run.

    No Redis dependency: the only thing this route used it for was the write-only cancelled
    key, and a route that needs Redis is a route the desktop sidecar cannot serve from a
    bundle that excludes the driver (`test_sidecar_startup.py`).
    """
    session = await _authorized_session(db, session_id, current_user.id)
    if session.status not in (SessionStatus.RUNNING, SessionStatus.PENDING):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot stop a session with status {session.status}.",
        )

    session.status = SessionStatus.FAILED
    session.error_message = "Research stopped by user."
    # Durable, and the reason the run cannot be un-stopped by its own outcome (issue #54).
    # This replaces a `session:{id}:cancelled` Redis key that carried a 1h TTL and which a
    # repository-wide search found no reader for — it never did anything, and could not have
    # survived a worker restart if it had. `_persist_outcome` reads this instead.
    session.cancelled_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(session)

    from app.db.redis import publish_event

    await publish_event(
        str(session_id),
        {"type": "FAILED", "data": {"reason": "Research stopped by user."}},
    )

    logger.info("research_stopped_by_user", session_id=str(session_id))
    return SessionSummary.model_validate(session)


@router.post("/{session_id}/archive", response_model=SessionSummary)
async def archive_session(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Move a session out of the active list. Reversible, loses nothing."""
    session = await _authorized_session(db, session_id, current_user.id)
    if session.archived_at is None:
        session.archived_at = datetime.now(UTC)
        await db.commit()
        await db.refresh(session)
    return SessionSummary.model_validate(session)


@router.post("/{session_id}/unarchive", response_model=SessionSummary)
async def unarchive_session(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    session = await _authorized_session(db, session_id, current_user.id)
    if session.archived_at is not None:
        session.archived_at = None
        await db.commit()
        await db.refresh(session)
    return SessionSummary.model_validate(session)


@router.delete("/{session_id}", status_code=204)
async def delete_session(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Permanently delete a session and everything derived from it.

    Agent logs, chat messages, and audit rows go with it via ON DELETE CASCADE. The
    LangGraph checkpoints are keyed by thread id in tables we do not own, so they are
    dropped explicitly — otherwise "delete" would leave the full agent state (including
    fetched page content) behind, which is exactly what a user deleting a session is
    asking us not to do.
    """
    session = await _authorized_session(db, session_id, current_user.id)
    if session.status == SessionStatus.RUNNING:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="This session is still running. Wait for it to finish before deleting.",
        )

    await db.delete(session)
    await db.commit()

    try:
        await checkpoints.delete_thread(str(session_id))
    except Exception as e:  # noqa: BLE001 — the user's rows are gone; log and move on
        logger.warning("checkpoint_cleanup_failed", session_id=str(session_id), error=str(e))

    logger.info("session_deleted", session_id=str(session_id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


async def _authorized_session(
    db: AsyncSession, session_id: uuid.UUID, user_id: uuid.UUID
) -> Session:
    session = (
        await db.execute(
            select(Session).where(Session.id == session_id, Session.user_id == user_id)
        )
    ).scalar_one_or_none()
    if not session:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Session not found.")
    return session
