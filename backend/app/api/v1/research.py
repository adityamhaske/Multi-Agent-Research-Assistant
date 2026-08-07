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
from app.models.agent_log import AgentLog
from app.models.audit_log import AuditLog
from app.models.session import Session, SessionStatus
from app.models.user import User
from app.schemas.research import (
    ApprovalRequest,
    ResearchStartRequest,
    ResearchStartResponse,
    SessionDetail,
    SessionListResponse,
    SessionSummary,
)
from app.services import checkpoints, export, model_routing, usage
from app.services.sse import SSE_HEADERS
from app.workers.tasks import resume_agent_pipeline, run_agent_pipeline

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
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)

    run_agent_pipeline.delay(str(session.id), str(current_user.id))
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
        channel = f"session:{session_id}:events"
        pubsub = redis.pubsub()
        # Subscribe BEFORE snapshotting the backlog. Any event published in the gap
        # between the snapshot and the subscribe would otherwise be lost from both —
        # which stranded fast resume→COMPLETED runs on the monitor. Now such an event
        # is queued on the pubsub and deduped against the backlog by its durable id.
        await pubsub.subscribe(channel)
        seen_max = after_id
        try:
            yield f"data: {json.dumps({'type': 'connected'})}\n\n"

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
                replay = [(row.id, row.payload) for row in backlog]

            for eid, payload in replay:
                seen_max = max(seen_max, eid or 0)
                yield f"id: {eid}\ndata: {json.dumps(payload)}\n\n"
                if payload.get("type") in ("COMPLETED", "FAILED"):
                    return
            async for message in pubsub.listen():
                if message["type"] != "message":
                    continue
                try:
                    payload = json.loads(message["data"])
                except (json.JSONDecodeError, TypeError):
                    continue
                eid = payload.get("id")
                if eid is not None and eid <= seen_max:
                    continue  # already replayed
                if eid:
                    yield f"id: {eid}\ndata: {json.dumps(payload)}\n\n"
                else:
                    yield f"data: {json.dumps(payload)}\n\n"
                if payload.get("type") in ("COMPLETED", "FAILED", "HITL_READY"):
                    break
        finally:
            await pubsub.unsubscribe(channel)
            await pubsub.aclose()

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


def _report_or_404(session: Session) -> str:
    report = session.final_report or session.draft_report
    if not report:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="No report available to export.")
    return report


@router.get("/{session_id}/export.md")
async def export_markdown(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    session = await _authorized_session(db, session_id, current_user.id)
    report = _report_or_404(session)
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
        pdf = export.render_pdf(report, session.sources or [], title=title)
    except RuntimeError as e:
        # Native PDF libs unavailable in this environment (docs/09 §1 bakes them in).
        raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, detail=str(e)) from e
    filename = f"research-{str(session.id)[:8]}.pdf"
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


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
    return {"message": "Approved. Finalizing." if payload.approved else "Rework requested."}


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
