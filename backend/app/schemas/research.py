from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.models.session import SessionStatus
from app.services.chat_scope import ChatScope

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

    # ── Research design gate (docs/07 §2, Phase 4) ─────────────────────────────
    # All three are persisted onto the session and read back into `RunConfig` on every
    # resume. They are accepted here only now that the whole resume path exists — the
    # groundwork commit deliberately left them out, because a field the schema accepts
    # and the run never reads is the exact bug AGENTS.md records for corpus_mode/demo.

    #: Subtopics the researcher requires the plan to cover. The planner treats them as a
    #: floor, not a ceiling, and the reviewer edits the result at the gate.
    topic_seeds: list[str] = Field(default_factory=list, max_length=20)
    #: A template id from `research_engine.outlines.TEMPLATES` (served by
    #: `GET /research/outline-templates`). None → no structure imposed, today's report.
    outline_template: str | None = Field(default=None, max_length=64)
    #: **True is deliberate, and is not the product default.** The app's run form sends
    #: `false` explicitly, so a person using the product gets the gate. This default
    #: governs the other population: a script or integration POSTing the same body it
    #: posted before this field existed. For them the gate would be an invisible pause
    #: they never poll past, so they keep today's journey untouched until they ask.
    skip_plan_gate: bool = True

    @field_validator("topic_seeds")
    @classmethod
    def drop_blank_seeds(cls, v: list[str]) -> list[str]:
        # A UI with three empty seed rows must not constrain the planner with three
        # empty strings — `prompts.planner_human` filters these too, belt and braces.
        return [s.strip() for s in v if s and s.strip()]


class ApprovalRequest(BaseModel):
    approved: bool
    feedback: str | None = Field(default=None, max_length=1000)

    @field_validator("feedback")
    @classmethod
    def feedback_required_on_reject(cls, v: str | None, info) -> str | None:
        if info.data.get("approved") is False and (not v or not v.strip()):
            raise ValueError("Feedback is required when rejecting a draft.")
        return v


class PlanTaskSchema(BaseModel):
    """One research task, as proposed by the planner and as edited by the reviewer.

    Mirrors `research_engine.schemas.ResearchTask`'s reviewer-facing fields. It is a
    separate model rather than a reuse because this one crosses the network in both
    directions: the engine model carries run state (`status`) that a client has no
    business setting, and a client sends an `include` flag the engine consumes and drops.
    """

    id: int = 0
    query: str = Field(min_length=3, max_length=500)
    rationale: str = Field(default="", max_length=1000)
    subtopics: list[str] = Field(default_factory=list, max_length=20)
    #: False drops this task from the run. The gate filters on it and the executor never
    #: sees the task — a review that could not remove anything would be a rubber stamp.
    include: bool = True
    source_hint: str | None = Field(default=None, max_length=200)


class OutlineSectionSchema(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=1000)


class PlanDecisionRequest(BaseModel):
    """The reviewer's decision at the design gate.

    Both fields are optional and `None` means *unedited* — the planner's proposal stands.
    That is a different thing from `[]`, which is a reviewer who removed everything, and
    the two must not be collapsed: reading "unedited" as "empty" would run a report with
    no research in it, and reading "empty" as "unedited" would ignore the decision.
    """

    #: 24 rather than the planner's own 6-task default: the cap exists because every task
    #: is a paid round of search, but a review gate whose whole point is "add the
    #: subtopics the planner missed" cannot cap the reviewer at the planner's number.
    tasks: list[PlanTaskSchema] | None = Field(default=None, max_length=24)
    outline: list[OutlineSectionSchema] | None = Field(default=None, max_length=24)


class PlanResponse(BaseModel):
    session_id: UUID
    status: SessionStatus
    tasks: list[PlanTaskSchema] = Field(default_factory=list)
    outline: list[OutlineSectionSchema] = Field(default_factory=list)
    #: Null while the session is still AWAITING_PLAN — the reviewer has not decided yet.
    #: Set once, when the plan is submitted, so a later read of this endpoint returns the
    #: decision that actually shaped the report rather than the proposal it started from.
    approved_at: datetime | None = None


class OutlineTemplateSchema(BaseModel):
    id: str
    label: str
    summary: str
    sections: list[OutlineSectionSchema]


class ChatRequest(BaseModel):
    model_config = {"str_strip_whitespace": True}

    message: str = Field(..., min_length=1, max_length=4000)
    #: What this question may read (docs/07 §2, Phase 5). "report" is today's behaviour
    #: on both chat surfaces — finished, approved research — so an un-updated client that
    #: omits the field gets exactly the answer it got before. See
    #: `app/services/chat_scope.py` for what each value promises, and for why "corpus"
    #: promises no *retrieval* egress rather than zero network calls.
    scope: ChatScope = "report"


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
    #: Fraction of this report's in-text `[n]` markers that resolve to a real source.
    #: **`None` means not measured** — no citable claims were made, or the session
    #: predates the column. Never conflate with `0.0`, which means every marker failed.
    #: History filters on it, which is why it is on the summary and not just the detail.
    citation_resolution_rate: float | None = None
    #: Which models produced this report. On the summary so History can filter by model;
    #: `None` when a run failed before routing resolved.
    model_routing: dict[str, str] | None = None

    model_config = {"from_attributes": True, "populate_by_name": True}


class SessionDetail(SessionSummary):
    draft_report: str | None = None
    final_report: str | None = None
    sources: list[SourceSchema] | None = None
    error_message: str | None = None
    updated_at: datetime
    # NOTE: `model_routing` moved up to `SessionSummary` in Phase 7 so History can filter
    # on it; it is inherited here rather than re-declared. The comment below is kept
    # because it records why the field exists at all.
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
