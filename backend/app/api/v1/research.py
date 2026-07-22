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

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import get_db
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
    session = Session(
        user_id=current_user.id,
        prompt=payload.query,
        status=SessionStatus.PENDING,
        research_depth=payload.depth,
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
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    limit = max(1, min(limit, 100))
    base = select(Session).where(Session.user_id == current_user.id)
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

    # Snapshot the backlog to replay before subscribing to live events.
    backlog = (
        (
            await db.execute(
                select(AgentLog)
                .where(AgentLog.session_id == session_id, AgentLog.id > after_id)
                .order_by(AgentLog.id.asc())
            )
        )
        .scalars()
        .all()
    )
    replay = [(row.id, row.payload) for row in backlog]

    async def gen() -> AsyncGenerator[str, None]:
        channel = f"session:{session_id}:events"
        pubsub = redis.pubsub()
        await pubsub.subscribe(channel)
        seen_max = after_id
        try:
            yield f"data: {json.dumps({'type': 'connected'})}\n\n"
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
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
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
