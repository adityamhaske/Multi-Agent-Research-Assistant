"""
Project chat: threads, retrieval, and cited answers (docs/14 §5, §8).

This is the milestone's payload — chat over a project's *approved* research, where every
claim resolves to a report a human signed off on.

**Isolation is the SQL predicate in `memory.retrieve`, not a sentence in the prompt.**
The prompt does tell the model to answer only from what it was given, and that matters
for answer quality; it is not what stops project A's research reaching project B's chat.
A prompt instruction is not a security control (docs/06 §4). Ownership is checked, the
query is filtered by `project_id`, and only then does any text reach a model.

**Retrieved excerpts are untrusted input.** They originate from web pages fetched during
research, so an injection captured months ago is still an injection when it resurfaces
here — arguably a worse one, since nobody is watching the run any more. They are wrapped
in `<untrusted_web_content>` unconditionally, exactly as the retriever's output is during
a run.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime

import structlog
from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.responses import StreamingResponse
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import adapters
from app.api.v1.projects import resolve_project
from app.config import settings
from app.db.base import get_db
from app.dependencies import enforce_chat_rate_limit, get_current_user
from app.models.chat_message import ChatMessage
from app.models.chat_thread import ChatThread, derive_title
from app.models.project import Project
from app.models.user import User
from app.schemas.chat import (
    MemoryStatusResponse,
    ThreadCreateRequest,
    ThreadListResponse,
    ThreadMessageRequest,
    ThreadMessageSchema,
    ThreadResponse,
)
from app.services import chat_scope, crypto, memory
from app.services.sse import SSE_HEADERS
from research_engine import prompts
from research_engine.embeddings import EmbeddingsUnavailable
from research_engine.llm_factory import get_llm, reset_user_keys, set_user_keys, text_of

logger = structlog.get_logger()
router = APIRouter(tags=["Project chat"])

# How much of the conversation is replayed to the model. The same ceiling the per-report
# chat uses: enough for continuity, bounded so a long thread cannot grow the prompt (and
# the bill) without limit.
_HISTORY_LIMIT = 20


def _user_keys(user: User) -> dict[str, str]:
    """This user's BYOK key, if any — so their chat runs on the key their research did."""
    if not (user.api_key_encrypted and user.api_key_provider):
        return {}
    plaintext = crypto.decrypt(user.api_key_encrypted)
    if not plaintext:
        return {}
    keys = {user.api_key_provider: plaintext}
    if user.api_key_base_url:
        keys[f"{user.api_key_provider}_base_url"] = user.api_key_base_url
    return keys


async def _owned_thread(db: AsyncSession, thread_id: uuid.UUID, user_id: uuid.UUID) -> ChatThread:
    """A thread this user owns, or 404.

    Joined through `projects` so a thread in someone else's project is indistinguishable
    from one that does not exist — the same shape as every other ownership check here.
    """
    thread = (
        await db.execute(
            select(ChatThread)
            .join(Project, Project.id == ChatThread.project_id)
            .where(ChatThread.id == thread_id, Project.user_id == user_id)
        )
    ).scalar_one_or_none()
    if not thread:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Thread not found.")
    return thread


async def _message_counts(db: AsyncSession, thread_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    if not thread_ids:
        return {}
    rows = await db.execute(
        select(ChatMessage.thread_id, func.count())
        .where(ChatMessage.thread_id.in_(thread_ids))
        .group_by(ChatMessage.thread_id)
    )
    return {tid: n for tid, n in rows.all()}


# ── Threads ────────────────────────────────────────────────────────────────────────


@router.get("/projects/{project_id}/threads", response_model=ThreadListResponse)
async def list_threads(
    project_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = await resolve_project(db, current_user.id, project_id)
    rows = (
        (
            await db.execute(
                select(ChatThread)
                .where(ChatThread.project_id == project.id)
                .order_by(ChatThread.last_message_at.desc())
            )
        )
        .scalars()
        .all()
    )
    counts = await _message_counts(db, [t.id for t in rows])
    return ThreadListResponse(
        threads=[
            ThreadResponse(
                id=t.id,
                project_id=t.project_id,
                title=t.title,
                message_count=counts.get(t.id, 0),
                created_at=t.created_at,
                last_message_at=t.last_message_at,
            )
            for t in rows
        ],
        total=len(rows),
    )


@router.post("/projects/{project_id}/threads", response_model=ThreadResponse, status_code=201)
async def create_thread(
    project_id: uuid.UUID,
    payload: ThreadCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = await resolve_project(db, current_user.id, project_id)
    thread = ChatThread(project_id=project.id, title=(payload.title or "New chat").strip())
    db.add(thread)
    await db.commit()
    await db.refresh(thread)
    return ThreadResponse(
        id=thread.id,
        project_id=thread.project_id,
        title=thread.title,
        message_count=0,
        created_at=thread.created_at,
        last_message_at=thread.last_message_at,
    )


@router.delete("/threads/{thread_id}", status_code=204)
async def delete_thread(
    thread_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    thread = await _owned_thread(db, thread_id, current_user.id)
    await db.delete(thread)  # messages cascade
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/threads/{thread_id}/messages", response_model=list[ThreadMessageSchema])
async def thread_history(
    thread_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await _owned_thread(db, thread_id, current_user.id)
    return (
        (
            await db.execute(
                select(ChatMessage)
                .where(ChatMessage.thread_id == thread_id)
                .order_by(ChatMessage.created_at.asc())
            )
        )
        .scalars()
        .all()
    )


# ── The cited answer ───────────────────────────────────────────────────────────────


def _grounding(retrieved: list[memory.Retrieved]) -> tuple[str, list[dict]]:
    """Numbered excerpts for the prompt, and the citations they resolve to.

    Marker order is retrieval order, so [R1] is the nearest match. Citations are built
    here — before the model runs — because they describe what was *retrieved*, which is a
    fact, rather than what the model chose to cite, which is a claim.
    """
    blocks: list[str] = []
    citations: list[dict] = []
    for index, hit in enumerate(retrieved, start=1):
        marker = f"R{index}"
        report_title = hit.session.prompt
        blocks.append(
            f"[{marker}] From the approved report {report_title!r} "
            f"({hit.session.created_at:%Y-%m-%d}):\n{hit.chunk.text}"
        )
        citations.append(
            {
                "marker": marker,
                "session_id": str(hit.session.id),
                "title": report_title,
                "created_at": hit.session.created_at.isoformat(),
                "excerpt": hit.chunk.text,
            }
        )
    return "\n\n".join(blocks), citations


@router.post("/threads/{thread_id}/messages")
async def send_thread_message(
    thread_id: uuid.UUID,
    payload: ThreadMessageRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _rl: None = Depends(enforce_chat_rate_limit),
):
    """Answer a question from this project's approved research, with citations."""
    thread = await _owned_thread(db, thread_id, current_user.id)

    keys = _user_keys(current_user)
    scope = payload.scope
    # Which scopes actually need a vector. A web-only follow-up needs none, which is why
    # this is checked rather than assumed: embedding unconditionally made a project with
    # no embeddings provider unable to ask *any* question, including ones that never
    # touch memory.
    needs_embedder = scope in ("report", "corpus", "everything")
    embedder = await adapters.embeddings_for(keys) if needs_embedder else None

    citations: list = []
    excerpts = ""
    if scope in ("report", "everything"):
        # Embed the question and retrieve *before* writing anything. An unavailable
        # provider must not leave a user message stranded in a thread that never got an
        # answer.
        try:
            query_vector = (await embedder.embed([payload.message]))[0]
        except EmbeddingsUnavailable as e:
            # 503, not a cheerful ungrounded answer: for these scopes this endpoint's
            # whole contract is that answers come from approved research, and it cannot
            # honour that right now.
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e)) from e

        retrieved = await memory.retrieve(
            db,
            project_id=thread.project_id,
            query_vector=query_vector,
            embedding_model=embedder.model_id,
        )
        excerpts, citations = _grounding(retrieved)

    def _corpus_store():
        """This project's uploaded corpus, or None. Built lazily so a scope that never
        reads it does not touch the filesystem."""
        db_path = settings.corpus_path / f"corpus_{thread.project_id}.sqlite"
        if not db_path.exists():
            return None
        from research_engine.corpus import CorpusStore

        return CorpusStore(db_path, embedder)

    if scope in ("report", "everything") and not excerpts:
        store = _corpus_store()
        if store:
            try:
                gen_hits = await store.search_generated_reports(payload.message, 8)
                if gen_hits:
                    gen_blocks = []
                    for idx, hit in enumerate(gen_hits, 1):
                        gen_blocks.append(
                            f"[{idx}] From approved report {hit['title']}:\n{hit['snippet']}"
                        )
                        citations.append(
                            {
                                "marker": idx,
                                "session_id": hit.get("document_id", ""),
                                "title": hit.get("title", "Approved Report"),
                                "created_at": datetime.now(UTC).isoformat(),
                                "excerpt": hit.get("snippet", ""),
                            }
                        )
                    excerpts = "\n\n".join(gen_blocks)
            except Exception as e:
                logger.warning("corpus_generated_reports_search_failed", error=str(e))

    try:
        grounding = await chat_scope.gather(
            scope,
            query=payload.message,
            report=None,
            report_sources=[],
            memory_excerpts=excerpts,
            store_factory=_corpus_store,
        )
    except EmbeddingsUnavailable as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(e)) from e

    now = datetime.now(UTC)
    db.add(ChatMessage(thread_id=thread_id, role="user", content=payload.message))
    if thread.title == "New chat":
        thread.title = derive_title(payload.message)
    thread.last_message_at = now
    await db.commit()

    history = (
        (
            await db.execute(
                select(ChatMessage)
                .where(ChatMessage.thread_id == thread_id)
                .order_by(ChatMessage.created_at.asc())
                .limit(_HISTORY_LIMIT)
            )
        )
        .scalars()
        .all()
    )

    # PROJECT_CHAT_PROMPT's refusal line stays first and unchanged — its Definition of
    # Done tests for it (docs/14 §9), and widening the scope is exactly when a model is
    # most tempted to answer from its own knowledge instead of saying "not in here".
    system = (
        f"{prompts.PROJECT_CHAT_PROMPT}\n\n"
        f"{chat_scope.system_suffix(grounding)}\n\n"
        f"<untrusted_web_content>\n"
        f"{grounding.text or '(nothing has been approved yet)'}\n"
        f"</untrusted_web_content>"
    )
    messages: list = [SystemMessage(content=system)]
    for m in history:
        messages.append(
            HumanMessage(content=m.content) if m.role == "user" else AIMessage(content=m.content)
        )

    async def gen() -> AsyncGenerator[str, None]:
        keys_token = set_user_keys(keys)
        acc = ""
        try:
            llm = get_llm("chat")  # raises with an actionable message if no key
            # Citations go first so the client can render the chips as text streams in.
            yield (
                "data: "
                + json.dumps(
                    {
                        "type": "connected",
                        "citations": citations,
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

            # Persist only the citations the answer actually used. An unused excerpt is
            # not a citation, and showing it as one would be the "sources theatre" the
            # ⚠ chip exists to avoid (docs/07 §5).
            used = [c for c in citations if f"[{c['marker']}]" in acc]
            msg = ChatMessage(
                thread_id=thread_id, role="assistant", content=acc, citations=used or None
            )
            db.add(msg)
            await db.commit()
            await db.refresh(msg)
            yield (
                "data: "
                + json.dumps({"type": "done", "message_id": str(msg.id), "citations": used})
                + "\n\n"
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("thread_chat_failed", thread_id=str(thread_id), error=str(e))
            yield f"data: {json.dumps({'type': 'error', 'detail': str(e)})}\n\n"
        finally:
            reset_user_keys(keys_token)

    return StreamingResponse(gen(), media_type="text/event-stream", headers=SSE_HEADERS)


# ── Memory status ──────────────────────────────────────────────────────────────────


@router.get("/projects/{project_id}/memory/status", response_model=MemoryStatusResponse)
async def memory_status(
    project_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """What this project remembers, and what it is missing (docs/14 §8)."""
    project = await resolve_project(db, current_user.id, project_id)
    embedder = await adapters.embeddings_for(_user_keys(current_user))
    result = await memory.status(db, project_id=project.id, current_model=embedder.model_id)
    return MemoryStatusResponse(
        available=embedder.model_id != "none",
        chunk_count=result.chunk_count,
        indexed_reports=result.indexed_reports,
        approved_reports=result.approved_reports,
        pending_reports=result.pending_reports,
        current_model=result.current_model,
        models=result.models,
        stale_models=result.stale_models,
        last_ingest_at=result.last_ingest_at,
    )
