import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.types import JsonType, UuidType


class SessionStatus(enum.StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    # Paused at the research design gate (docs/07 §2, Phase 4) — the planner has proposed
    # tasks and an outline and is waiting on the reviewer, before any search has spent
    # anything. Distinct from AWAITING_APPROVAL rather than a shared "paused": the two
    # gates resume with different payloads, so a client that could not tell them apart
    # would offer "Approve draft" for a draft that does not exist yet.
    AWAITING_PLAN = "AWAITING_PLAN"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = mapped_column(UuidType, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UuidType,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Every session lives in a project (docs/14 §3). Existing rows were backfilled into
    # a per-user "General" project by migration 0005, which is why this is NOT NULL.
    project_id: Mapped[uuid.UUID] = mapped_column(
        UuidType,
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[SessionStatus] = mapped_column(
        SAEnum(SessionStatus, name="session_status"),
        nullable=False,
        default=SessionStatus.PENDING,
        index=True,
    )
    research_depth: Mapped[str] = mapped_column(String(20), nullable=False, default="balanced")
    draft_report: Mapped[str | None] = mapped_column(Text, nullable=True)
    final_report: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Numbered citation table the UI renders: [{index, url, title, snippet}] (docs/05 §1).
    sources: Mapped[list | None] = mapped_column(JsonType, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Money as Numeric — never float (docs/05 §5).
    total_cost_usd: Mapped[float] = mapped_column(Numeric(10, 6), nullable=False, default=0)
    total_tokens_input: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_tokens_output: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    elapsed_seconds: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    rework_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Archiving is reversible and keeps the row; deletion is a separate, hard action.
    # Timestamp rather than a boolean so "when did this leave the active list" is
    # answerable without a second column.
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Which models actually produced this report (docs/12 M8). Snapshotted at run time
    # rather than read back from the user's current preference, because a preference can
    # change afterwards and a report has to stay attributable to what wrote it — the same
    # reason the approval decision is recorded in the audit log.
    model_routing: Mapped[dict | None] = mapped_column(JsonType, nullable=True)

    # How much of this report's citation apparatus resolves (docs/07 §2, Phase 7).
    # **Nullable, and NULL means "not measured"** — a report that made no citable claims,
    # or a session predating this column. A `0.0` here would mean "every marker points at
    # nothing", which is the opposite finding; storing the two as one value is the
    # unmeasured-vs-zero bug this codebase exists to refuse.
    citation_resolution_rate: Mapped[float | None] = mapped_column(Numeric(5, 4), nullable=True)

    # Airgapped corpus mode (docs/12 M10).
    corpus_mode: Mapped[bool] = mapped_column(nullable=False, server_default="false")

    # This run used scripted models and fixture retrievers rather than a real provider
    # (docs/17 §6.2). Persisted rather than inferred from the process's LLM_MODE, because
    # every export path must be able to stamp the artifact long after the run — and
    # because a report that cannot prove it is a demo is exactly the kind of unverifiable
    # output this product exists to refuse.
    demo: Mapped[bool] = mapped_column(nullable=False, server_default="false")

    # ── Plan gate (docs/07 §2, Phase 4) ────────────────────────────────────────
    # The reviewer's decision, not the planner's proposal — plan_json/outline_json
    # hold the request as edited at the gate, same as model_routing snapshots what
    # actually ran rather than a current, possibly-since-changed preference.
    plan_json: Mapped[dict | None] = mapped_column(JsonType, nullable=True)
    outline_json: Mapped[dict | None] = mapped_column(JsonType, nullable=True)
    plan_approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Whether this run skipped the design gate. Both hosts' start endpoints always set
    # it explicitly from `ResearchStartRequest.skip_plan_gate`, so the `false` server
    # default below is reached only by a row created outside those endpoints — it is
    # kept as-is because migration 0012 shipped it and a column default that says
    # "gated" is the safer thing for a row nobody claimed.
    #
    # The request's own default is the opposite (True — skip), and deliberately so: the
    # gate is the product default *for the app*, where the run form sends `false`
    # explicitly, but a script POSTing last week's JSON must not start pausing at a gate
    # it cannot see or resume. `RunConfig.skip_plan_gate` defaults to True for the same
    # reason one layer down, covering the CLI and the eval harness.
    skip_plan_gate: Mapped[bool] = mapped_column(nullable=False, server_default="false")
    # What the researcher asked for at start time, as opposed to what they decided at the
    # gate (`plan_json`/`outline_json` above). Persisted rather than passed through the
    # queue because `RunConfig` is rebuilt from this row on every resume, and a field that
    # only existed on the original request would silently become empty the second time.
    topic_seeds: Mapped[list | None] = mapped_column(JsonType, nullable=True)
    outline_template: Mapped[str | None] = mapped_column(String(64), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships. passive_deletes lets the DB-level ON DELETE CASCADE do the work
    # instead of the ORM loading every child row (docs/05 §5).
    user: Mapped["User"] = relationship("User", back_populates="sessions")  # noqa: F821
    project: Mapped["Project"] = relationship("Project", back_populates="sessions")  # noqa: F821
    # `agent_logs.session_id` is polymorphic across V1 sessions and V2 runs and carries no
    # foreign key, so the relationship states the join condition explicitly and cascades in
    # the ORM rather than relying on the database. `viewonly=False` with `delete-orphan` is
    # what keeps "delete this session removes its trace" true without an FK.
    agent_logs: Mapped[list["AgentLog"]] = relationship(  # noqa: F821
        "AgentLog",
        primaryjoin="Session.id == foreign(AgentLog.session_id)",
        cascade="all, delete-orphan",
        lazy="select",
    )
    chat_messages: Mapped[list["ChatMessage"]] = relationship(  # noqa: F821
        "ChatMessage",
        back_populates="session",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="select",
        order_by="ChatMessage.created_at",
    )

    def __repr__(self) -> str:
        return f"<Session id={self.id} status={self.status}>"
