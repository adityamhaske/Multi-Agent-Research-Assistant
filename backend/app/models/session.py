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

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships. passive_deletes lets the DB-level ON DELETE CASCADE do the work
    # instead of the ORM loading every child row (docs/05 §5).
    user: Mapped["User"] = relationship("User", back_populates="sessions")  # noqa: F821
    project: Mapped["Project"] = relationship("Project", back_populates="sessions")  # noqa: F821
    agent_logs: Mapped[list["AgentLog"]] = relationship(  # noqa: F821
        "AgentLog",
        back_populates="session",
        cascade="all, delete-orphan",
        passive_deletes=True,
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
