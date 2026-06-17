import uuid
import enum
from datetime import datetime
from typing import Optional
from sqlalchemy import String, Text, Float, Integer, Enum as SAEnum, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import Base


class SessionStatus(str, enum.Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
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
    research_depth: Mapped[str] = mapped_column(
        String(20), nullable=False, default="balanced"
    )
    selected_sources: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=lambda: ["web"]
    )
    total_cost_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    total_tokens_input: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_tokens_output: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    elapsed_seconds: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    draft_report: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    final_report: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    checkpoint_data: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="sessions")  # noqa: F821
    agent_logs: Mapped[list["AgentLog"]] = relationship(  # noqa: F821
        "AgentLog",
        back_populates="session",
        cascade="all, delete-orphan",
        lazy="select",
    )
    chat_messages: Mapped[list["ChatMessage"]] = relationship(  # noqa: F821
        "ChatMessage",
        back_populates="session",
        cascade="all, delete-orphan",
        lazy="select",
        order_by="ChatMessage.created_at",
    )

    def __repr__(self) -> str:
        return f"<Session id={self.id} status={self.status}>"
