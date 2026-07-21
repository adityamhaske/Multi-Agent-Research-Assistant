import json
import uuid
from collections.abc import AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.base import get_db
from app.dependencies import check_rate_limit, get_current_user
from app.models.chat_message import ChatMessage
from app.models.session import Session, SessionStatus
from app.models.user import User
from app.schemas.research import ChatMessageSchema, ChatRequest

router = APIRouter(prefix="/research/{session_id}/chat", tags=["Chat"])


@router.get("/", response_model=list[ChatMessageSchema])
async def get_chat_history(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get the full chat history for a research session."""
    # Verify ownership
    result = await db.execute(
        select(Session).where(Session.id == session_id, Session.user_id == current_user.id)
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")

    result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at.asc())
    )
    return result.scalars().all()


@router.post("/")
async def send_chat_message(
    session_id: uuid.UUID,
    payload: ChatRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _rate_limit: None = Depends(check_rate_limit),
):
    """Send a message and get an AI response streamed via SSE."""
    # Verify ownership and status
    result = await db.execute(
        select(Session).where(Session.id == session_id, Session.user_id == current_user.id)
    )
    session = result.scalar_one_or_none()

    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    if session.status != SessionStatus.COMPLETED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Chat is only available for COMPLETED sessions.",
        )

    # Save user message
    user_msg = ChatMessage(session_id=session_id, role="user", content=payload.message)
    db.add(user_msg)
    await db.commit()
    await db.refresh(user_msg)

    # Load history for context
    history_result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at.asc())
        .limit(20)  # Keep context window reasonable
    )
    chat_history = history_result.scalars().all()

    # Construct LLM prompt
    system_prompt = f"""You are an expert analyst and research assistant.
You recently completed a research report for the user. Answer their follow-up questions using the context of the original report.
Be concise, accurate, and professional. Use Markdown for formatting.

--- ORIGINAL RESEARCH REPORT ---
{session.final_report}
"""
    messages = [SystemMessage(content=system_prompt)]
    for msg in chat_history:
        # Avoid passing the last message again as it's already in chat_history
        if msg.role == "user":
            messages.append(HumanMessage(content=msg.content))
        else:
            messages.append(SystemMessage(content=msg.content))  # Assistant message

    async def generate_response() -> AsyncGenerator[str, None]:
        llm = ChatGoogleGenerativeAI(
            model="gemini-1.5-flash",
            api_key=settings.google_api_key,
            temperature=0.3,
            max_tokens=2000,
        )

        ai_content = ""
        try:
            # Yield initial connection heartbeat
            yield f"data: {json.dumps({'type': 'connected'})}\n\n"

            async for chunk in llm.astream(messages):
                if chunk.content:
                    ai_content += chunk.content
                    yield f"data: {json.dumps({'type': 'chunk', 'text': chunk.content})}\n\n"

            # Save the full AI response to DB
            ai_msg = ChatMessage(session_id=session_id, role="assistant", content=ai_content)
            db.add(ai_msg)
            await db.commit()

            yield f"data: {json.dumps({'type': 'done', 'message_id': str(ai_msg.id)})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'text': str(e)})}\n\n"

    return StreamingResponse(
        generate_response(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
