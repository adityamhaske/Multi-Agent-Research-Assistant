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

from app.db.base import get_db
from app.dependencies import enforce_chat_rate_limit, get_current_user
from app.models.chat_message import ChatMessage
from app.models.session import Session, SessionStatus
from app.models.user import User
from app.schemas.research import ChatMessageSchema, ChatRequest
from app.services import chat_scope, crypto
from app.services.sse import SSE_HEADERS
from research_engine import prompts
from research_engine.embeddings import EmbeddingsUnavailable
from research_engine.llm_factory import get_llm, reset_user_keys, set_user_keys, text_of

router = APIRouter(prefix="/research/{session_id}/chat", tags=["Chat"])


def _user_provider_keys(user: User) -> dict[str, str]:
    """This user's BYOK key, so follow-up chat runs on the same key their research did."""
    if not (user.api_key_encrypted and user.api_key_provider):
        return {}
    plaintext = crypto.decrypt(user.api_key_encrypted)
    if not plaintext:
        return {}
    keys = {user.api_key_provider: plaintext}
    if user.api_key_base_url:
        keys[f"{user.api_key_provider}_base_url"] = user.api_key_base_url
    return keys


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

    # BYOK first: the corpus store embeds on this user's key exactly as their research
    # did, so it has to be resolved before the grounding is gathered.
    user_keys = _user_provider_keys(current_user)

    def _corpus_store():
        """The project's corpus, or None when it has none. Built lazily — `report` scope
        must not touch the filesystem to answer a question about a report."""
        from app.config import settings

        db_path = settings.corpus_path / f"corpus_{session.project_id}.sqlite"
        if not db_path.exists():
            return None
        from research_engine.corpus import CorpusStore

        return CorpusStore(db_path, _embedder_cache["value"])

    _embedder_cache: dict = {"value": None}
    if payload.scope in ("corpus", "everything"):
        from app import adapters

        _embedder_cache["value"] = await adapters.embeddings_for(user_keys)

    try:
        grounding = await chat_scope.gather(
            payload.scope,
            query=payload.message,
            report=session.final_report,
            report_sources=session.sources or [],
            memory_excerpts=None,
            store_factory=_corpus_store,
        )
    except EmbeddingsUnavailable as e:
        # 400, not a cheerful ungrounded answer: the user asked for corpus scope
        # specifically, and the honest response to "that would have left your machine"
        # is to say so rather than to answer from somewhere else.
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(e)) from e

    system = (
        f"{prompts.CHAT_PROMPT_V2}\n\n"
        f"{chat_scope.system_suffix(grounding)}\n\n"
        f"<untrusted_web_content>\n{grounding.text}\n</untrusted_web_content>"
    )
    messages: list = [SystemMessage(content=system)]
    for m in history:
        messages.append(
            HumanMessage(content=m.content) if m.role == "user" else AIMessage(content=m.content)
        )

    async def gen() -> AsyncGenerator[str, None]:
        keys_token = set_user_keys(user_keys)
        acc = ""
        try:
            llm = get_llm("chat")  # raises with an actionable message if no key
            # Sources first so the client can render citation chips as text streams in,
            # and so a web-scoped answer's [n] markers resolve to something. `scope` is
            # echoed back because the answer has to be able to say which one produced it.
            yield (
                "data: "
                + json.dumps(
                    {
                        "type": "connected",
                        "scope": grounding.scope,
                        "sources": grounding.sources,
                        "notes": grounding.notes,
                    }
                )
                + "\n\n"
            )
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
        finally:
            reset_user_keys(keys_token)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )
