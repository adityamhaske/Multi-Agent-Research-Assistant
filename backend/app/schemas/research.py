from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.models.session import SessionStatus

# ─── Requests ───────────────────────────────────────────────────────────────────


class ResearchStartRequest(BaseModel):
    model_config = {"str_strip_whitespace": True}

    query: str = Field(..., min_length=10, max_length=2000)
    depth: str = Field(default="balanced", pattern="^(fast|balanced|comprehensive)$")
    # Which project this research belongs to. None → the user's default project, so a
    # brand-new account is never blocked from starting a run (docs/14 §7).
    project_id: UUID | None = None
    # Per-run model choice. None → fall back to the user's saved preference, then the
    # deployment default (docs/12 M8). Whatever is resolved is snapshotted on the
    # session, so a resumed run keeps the models it started with.
    model_routing: dict[str, str] | None = Field(
        default=None,
        description='Role → "provider:model". Omit to use your saved settings.',
    )
    # Airgapped corpus mode (docs/12 M10): research is performed exclusively over the
    # installed corpus with no outbound network calls.
    corpus_mode: bool = False


class ApprovalRequest(BaseModel):
    approved: bool
    feedback: str | None = Field(default=None, max_length=1000)

    @field_validator("feedback")
    @classmethod
    def feedback_required_on_reject(cls, v: str | None, info) -> str | None:
        if info.data.get("approved") is False and (not v or not v.strip()):
            raise ValueError("Feedback is required when rejecting a draft.")
        return v


class ChatRequest(BaseModel):
    model_config = {"str_strip_whitespace": True}

    message: str = Field(..., min_length=1, max_length=4000)


# ─── Responses ──────────────────────────────────────────────────────────────────


class ResearchStartResponse(BaseModel):
    session_id: UUID
    status: SessionStatus


class SourceSchema(BaseModel):
    index: int
    url: str
    title: str = ""
    snippet: str = ""


class SessionSummary(BaseModel):
    """Slim row for list/history — no report bodies (docs/05 §3)."""

    session_id: UUID = Field(validation_alias="id")
    project_id: UUID
    status: SessionStatus
    prompt: str
    research_depth: str
    total_cost_usd: float
    total_tokens_input: int
    total_tokens_output: int
    elapsed_seconds: float | None = None
    rework_count: int = 0
    created_at: datetime
    archived_at: datetime | None = None

    model_config = {"from_attributes": True, "populate_by_name": True}


class SessionDetail(SessionSummary):
    draft_report: str | None = None
    final_report: str | None = None
    sources: list[SourceSchema] | None = None
    error_message: str | None = None
    updated_at: datetime


class SessionListResponse(BaseModel):
    sessions: list[SessionSummary]
    total: int
    page: int
    limit: int


class ChatMessageSchema(BaseModel):
    id: UUID
    # Nullable since 0008: a chat message belongs to either a report or a project thread.
    # This endpoint only ever returns report-bound messages, so it is set in practice.
    session_id: UUID | None = None
    role: str
    content: str
    created_at: datetime

    model_config = {"from_attributes": True}
