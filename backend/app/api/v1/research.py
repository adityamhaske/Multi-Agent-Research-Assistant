import json
import uuid
from collections.abc import AsyncGenerator

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import get_db
from app.db.redis import get_redis
from app.dependencies import check_rate_limit, get_current_user
from app.models.session import Session, SessionStatus
from app.models.user import User
from app.schemas.research import (
    ApprovalRequest,
    ResearchStartRequest,
    ResearchStartResponse,
    SessionHistoryResponse,
    SessionListResponse,
    SessionStatusResponse,
)
from app.workers.tasks import run_agent_pipeline

logger = structlog.get_logger()
router = APIRouter(prefix="/research", tags=["Research"])


@router.post("/start", response_model=ResearchStartResponse, status_code=202)
async def start_research(
    payload: ResearchStartRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _rate_limit: None = Depends(check_rate_limit),
):
    """Start a new research session. Returns 202 immediately; agent runs in background."""
    session = Session(
        user_id=current_user.id,
        prompt=payload.query,
        status=SessionStatus.PENDING,
        research_depth=payload.depth,
        selected_sources=payload.sources,
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)

    # Enqueue the agent pipeline as a background Celery task
    run_agent_pipeline.delay(str(session.id), str(current_user.id))

    log = logger.bind(session_id=str(session.id), user_id=str(current_user.id))
    log.info("research_started", prompt_preview=payload.query[:50])

    return ResearchStartResponse(session_id=session.id, status=session.status)


@router.get("/{session_id}/status", response_model=SessionStatusResponse)
async def get_session_status(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get the current status and metadata of a research session."""
    session = await _get_authorized_session(db, session_id, current_user.id)
    return SessionStatusResponse.model_validate(session)


@router.get("/{session_id}/stream")
async def stream_session_events(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    redis=Depends(get_redis),
):
    """SSE endpoint streaming real-time agent log events for a session."""
    # Verify session ownership before opening stream
    await _get_authorized_session(db, session_id, current_user.id)

    async def event_generator() -> AsyncGenerator[str, None]:
        channel = f"session:{session_id}:events"
        pubsub = redis.pubsub()
        await pubsub.subscribe(channel)

        try:
            # Handshake event
            yield f"data: {json.dumps({'type': 'connected', 'session_id': str(session_id)})}\n\n"

            async for message in pubsub.listen():
                if message["type"] == "message":
                    yield f"data: {message['data']}\n\n"

                    # Close stream on terminal events
                    try:
                        payload = json.loads(message["data"])
                        if payload.get("type") in ("COMPLETED", "FAILED", "HITL_READY"):
                            break
                    except json.JSONDecodeError:
                        pass
        finally:
            await pubsub.unsubscribe(channel)
            await pubsub.aclose()

    return StreamingResponse(
        event_generator(),
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
    """Approve or reject the synthesized draft at the HITL gate."""
    session = await _get_authorized_session(db, session_id, current_user.id)

    if session.status != SessionStatus.AWAITING_APPROVAL:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Session must be in AWAITING_APPROVAL status. Current: {session.status}",
        )

    if payload.approved:
        # Resume the graph with approval signal
        run_agent_pipeline.delay(
            str(session.id), str(current_user.id), resume=True, approved=True, feedback=None
        )
        return {"message": "Approved. Finalizing report.", "session_id": str(session_id)}
    else:
        # Resume with rework instructions
        run_agent_pipeline.delay(
            str(session.id),
            str(current_user.id),
            resume=True,
            approved=False,
            feedback=payload.feedback,
        )
        return {"message": "Rework requested. Agent is resuming.", "session_id": str(session_id)}


@router.get("/", response_model=SessionListResponse)
async def list_sessions(
    page: int = 1,
    limit: int = 20,
    status_filter: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all research sessions for the authenticated user."""
    query = select(Session).where(Session.user_id == current_user.id)

    if status_filter:
        try:
            status_enum = SessionStatus(status_filter.upper())
            query = query.where(Session.status == status_enum)
        except ValueError:
            pass  # Invalid filter — ignore and return all

    # Count total
    count_result = await db.execute(select(func.count()).select_from(query.subquery()))
    total = count_result.scalar_one()

    from sqlalchemy.orm import selectinload

    # Paginate and eager load chat_messages for the count
    query = (
        query.order_by(Session.created_at.desc())
        .offset((page - 1) * limit)
        .limit(limit)
        .options(selectinload(Session.chat_messages))
    )
    result = await db.execute(query)
    sessions = result.scalars().all()

    # Build response with message counts
    session_responses = []
    for s in sessions:
        # Pydantic v2 from_attributes handles ORM
        base_resp = SessionStatusResponse.model_validate(s).model_dump(by_alias=True)
        base_resp["message_count"] = len(s.chat_messages)
        session_responses.append(SessionHistoryResponse(**base_resp))

    return SessionListResponse(
        sessions=session_responses,
        total=total,
        page=page,
        limit=limit,
    )


# ─── Helper ─────────────────────────────────────────────────────────────────────


async def _get_authorized_session(
    db: AsyncSession,
    session_id: uuid.UUID,
    user_id: uuid.UUID,
) -> Session:
    """Fetch a session and verify it belongs to the authenticated user."""
    result = await db.execute(
        select(Session).where(
            Session.id == session_id,
            Session.user_id == user_id,  # ← Security: always scope to current user
        )
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session {session_id} not found or you don't have access.",
        )
    return session
