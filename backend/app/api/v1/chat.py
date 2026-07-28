"""
Follow-up chat grounded in a completed report (docs/04 §5, docs/05 §3).

Assistant history is replayed as AIMessage (never SystemMessage — model output must
not gain system authority, docs/06 §4). Streaming is SSE; the report + sources are
provided as grounding, wrapped as untrusted content.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent import prompts
from app.agent.llm_factory import get_llm, text_of
from app.db.base import get_db
from app.dependencies import enforce_chat_rate_limit, get_current_user
from app.models.chat_message import ChatMessage
from app.models.session import Session, SessionStatus
from app.models.user import User
from app.schemas.research import ChatMessageSchema, ChatRequest

router = APIRouter(prefix="/research/{session_id}/chat", tags=["Chat"])


async def _authorized_completed_session(db, session_id, user_id) -> Session:
    session = (
        await db.execute(
            select(Session).where(Session.id == session_id, Session.user_id == user_id)
        )
    ).scalar_one_or_none()
    if not session:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Session not found.")
    return session


@router.get("", response_model=list[ChatMessageSchema])
async def get_history(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await _authorized_completed_session(db, session_id, current_user.id)
    rows = (
        (
            await db.execute(
                select(ChatMessage)
                .where(ChatMessage.session_id == session_id)
                .order_by(ChatMessage.created_at.asc())
            )
        )
        .scalars()
        .all()
    )
    return rows


@router.post("")
async def send_message(
    session_id: uuid.UUID,
    payload: ChatRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _rl: None = Depends(enforce_chat_rate_limit),
):
    session = await _authorized_completed_session(db, session_id, current_user.id)
    if session.status != SessionStatus.COMPLETED:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, detail="Chat is available only for completed sessions."
        )

    db.add(ChatMessage(session_id=session_id, role="user", content=payload.message))
    await db.commit()

    history = (
        (
            await db.execute(
                select(ChatMessage)
                .where(ChatMessage.session_id == session_id)
                .order_by(ChatMessage.created_at.asc())
                .limit(20)
            )
        )
        .scalars()
        .all()
    )

    sources = json.dumps(session.sources or [], indent=2)
    system = (
        f"{prompts.CHAT_PROMPT_V2}\n\n"
        f"--- REPORT ---\n{session.final_report}\n\n"
        f"--- SOURCES ---\n<untrusted_web_content>\n{sources}\n</untrusted_web_content>"
    )
    messages: list = [SystemMessage(content=system)]
    for m in history:
        messages.append(
            HumanMessage(content=m.content) if m.role == "user" else AIMessage(content=m.content)
        )

    async def gen() -> AsyncGenerator[str, None]:
        llm = get_llm("chat")
        acc = ""
        try:
            yield f"data: {json.dumps({'type': 'connected'})}\n\n"
            async for chunk in llm.astream(messages):
                text = text_of(chunk)
                if text:
                    acc += text
                    yield f"data: {json.dumps({'type': 'chunk', 'text': text})}\n\n"
            msg = ChatMessage(session_id=session_id, role="assistant", content=acc)
            db.add(msg)
            await db.commit()
            await db.refresh(msg)
            yield f"data: {json.dumps({'type': 'done', 'message_id': str(msg.id)})}\n\n"
        except Exception as e:  # noqa: BLE001
            yield f"data: {json.dumps({'type': 'error', 'detail': str(e)})}\n\n"

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
