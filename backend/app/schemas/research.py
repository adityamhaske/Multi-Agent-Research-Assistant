from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.models.session import SessionStatus

# ─── Request Schemas ────────────────────────────────────────────────────────────


class ResearchStartRequest(BaseModel):
    model_config = {"str_strip_whitespace": True}

    query: str = Field(
        ...,
        min_length=10,
        max_length=2000,
        description="The research question or topic.",
        examples=["Analyze AI investments in healthcare Q3 2024"],
    )
    depth: str = Field(
        default="balanced",
        pattern="^(fast|balanced|comprehensive)$",
        description="Research thoroughness: fast | balanced | comprehensive",
    )
    sources: list[str] = Field(
        default=["web"],
        description="Data sources to query.",
    )

    @field_validator("sources")
    @classmethod
    def validate_sources(cls, v: list[str]) -> list[str]:
        allowed = {"web", "academic", "internal"}
        invalid = set(v) - allowed
        if invalid:
            raise ValueError(f"Invalid sources: {invalid}. Allowed: {allowed}")
        if not v:
            return ["web"]
        return v


class ApprovalRequest(BaseModel):
    approved: bool = Field(..., description="True=approve and finalize; False=reject and rework.")
    feedback: str | None = Field(
        default=None,
        max_length=1000,
        description="Required if approved=False. Feedback for the agent on what to fix.",
    )

    @field_validator("feedback")
    @classmethod
    def feedback_required_on_reject(cls, v: str | None, info) -> str | None:
        if info.data.get("approved") is False and (not v or not v.strip()):
            raise ValueError("Feedback is required when rejecting a draft.")
        return v


# ─── Response Schemas ───────────────────────────────────────────────────────────


class ResearchStartResponse(BaseModel):
    session_id: UUID
    status: SessionStatus
    message: str = "Research session created and queued."


class AgentLogSchema(BaseModel):
    id: int
    session_id: UUID
    agent_name: str
    action: str
    result: dict | None = None
    timestamp: datetime

    model_config = {"from_attributes": True}


class SessionStatusResponse(BaseModel):
    session_id: UUID = Field(validation_alias="id")
    status: SessionStatus
    prompt: str
    research_depth: str
    total_cost_usd: float
    total_tokens_input: int
    total_tokens_output: int
    elapsed_seconds: float | None = None
    draft_report: str | None = None
    final_report: str | None = None
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True, "populate_by_name": True}


class SessionHistoryResponse(SessionStatusResponse):
    message_count: int = Field(default=0, description="Number of follow-up chat messages")


class SessionListResponse(BaseModel):
    sessions: list[SessionHistoryResponse]
    total: int
    page: int
    limit: int


# ─── Chat Schemas ───────────────────────────────────────────────────────────────


class ChatMessageSchema(BaseModel):
    id: UUID
    session_id: UUID
    role: str
    content: str
    created_at: datetime

    model_config = {"from_attributes": True}


class ChatRequest(BaseModel):
    model_config = {"str_strip_whitespace": True}

    message: str = Field(
        ...,
        min_length=1,
        max_length=4000,
        description="The user's follow-up question or message.",
    )


class ChatResponse(BaseModel):
    reply: str
    message_id: UUID
