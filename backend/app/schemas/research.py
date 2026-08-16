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
    # Run with scripted models and fixture sources instead of a real provider
    # (docs/17 §6.2), so the product can be demonstrated before any key exists. Persisted
    # on the session, which is what lets every export stamp itself as not-real research.
    demo: bool = False
    # NOT YET (docs/07 §2, Phase 4): topic_seeds/outline_template/skip_plan_gate are
    # deliberately not accepted here. The engine-level plan-gate primitives exist
    # (research_engine/schemas.py, graph.py::plan_gate_node) but nothing can resume a
    # session past that interrupt yet — accepting these fields now and silently
    # dropping them would be exactly the "accepted by the schema, dropped on the
    # floor" bug AGENTS.md documents for corpus_mode/demo. Add them back in the same
    # change that adds SessionStatus.AWAITING_PLAN, the resume dispatch, and the
    # /{id}/plan endpoint.


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
    # Every verbatim snippet extracted from this source (docs/12 M5 defect D3). Omitting
    # it here silently undid that fix on BOTH hosts: the engine produces `snippets`
    # (research_engine/schemas.py::Source) and the browser reads it
    # (frontend/lib/citations.tsx:141), but this response model sits between them and
    # Pydantic drops undeclared fields — so every hovercard fell back to the single
    # `snippet`, showing one quote for the ~8 different claims that cite a page.
    # Third copy of one contract; see AGENTS.md "two hosts, one contract".
    snippets: list[str] = Field(default_factory=list)


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
    # On the summary rather than the detail: history lists sessions side by side, and a
    # demo run sitting unmarked next to real ones is the thing this flag exists to prevent.
    demo: bool = False
    corpus_mode: bool = False

    model_config = {"from_attributes": True, "populate_by_name": True}


class SessionDetail(SessionSummary):
    draft_report: str | None = None
    final_report: str | None = None
    sources: list[SourceSchema] | None = None
    error_message: str | None = None
    updated_at: datetime
    # Resolved per-role routing (docs/07 §2, "truthful per-agent model attribution").
    # `session.model_routing` has been resolved and snapshotted since before this field
    # existed (`app/workers/pipeline_runner.py::_run_config_for`) — this class just
    # never declared it, so Pydantic silently dropped it en route to the browser. Third
    # copy of one contract; see the `snippets` comment on `SourceSchema` for the
    # identical bug (AGENTS.md — two hosts, one contract). `None` means "not resolved"
    # (a run that failed before the planner, or predates this field) — never a guessed
    # default; the unmeasured-vs-zero rule.
    model_routing: dict[str, str] | None = None


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
