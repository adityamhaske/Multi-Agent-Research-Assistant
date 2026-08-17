"""
Project chat threads and memory status (docs/14 §8).

Separate from `schemas/research.py` because these describe conversation *about a
project*, not about one research run — the distinction the whole milestone rests on.
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.services.chat_scope import ChatScope


class ThreadCreateRequest(BaseModel):
    model_config = {"str_strip_whitespace": True}

    # Optional: a thread opened from the composer is titled from its first message
    # instead, so the user never has to name a conversation before having it.
    title: str | None = Field(default=None, max_length=200)


class ThreadResponse(BaseModel):
    id: UUID
    project_id: UUID
    title: str
    message_count: int = 0
    created_at: datetime
    last_message_at: datetime

    model_config = {"from_attributes": True}


class ThreadListResponse(BaseModel):
    threads: list[ThreadResponse]
    total: int


class Citation(BaseModel):
    """One [R{n}] marker, resolved to the approved report it came from.

    `excerpt` is the retrieved chunk verbatim. Storing it is what makes a citation
    checkable rather than decorative: the chip shows the user the exact text the claim
    was drawn from, the same contract as the source snippets on a report (docs/07 §5).
    """

    marker: str
    session_id: UUID
    title: str
    created_at: datetime
    excerpt: str


class ThreadMessageSchema(BaseModel):
    id: UUID
    thread_id: UUID | None = None
    role: str
    content: str
    citations: list[Citation] | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ThreadMessageRequest(BaseModel):
    model_config = {"str_strip_whitespace": True}

    message: str = Field(..., min_length=1, max_length=4000)
    #: What this question may read (docs/07 §2, Phase 5). Same vocabulary as
    #: `research.ChatRequest.scope` — one word must mean one thing on both chat
    #: surfaces, which is why both defer to `app/services/chat_scope.py`. "report"
    #: here means this project's approved research, which is today's behaviour.
    scope: ChatScope = "report"


class MemoryModelBreakdown(BaseModel):
    embedding_model: str
    chunks: int
    reports: int


class MemoryStatusResponse(BaseModel):
    """Makes memory legible rather than magic (docs/14 §8).

    `pending_reports` and `stale_models` exist so the two ways memory can quietly be
    incomplete — an ingestion that failed, and chunks written by a model that is no
    longer configured — are visible in the UI instead of being discovered as "chat can't
    find my research".
    """

    available: bool
    chunk_count: int
    indexed_reports: int
    approved_reports: int
    pending_reports: int
    current_model: str
    models: list[MemoryModelBreakdown]
    stale_models: list[str]
    last_ingest_at: datetime | None = None
