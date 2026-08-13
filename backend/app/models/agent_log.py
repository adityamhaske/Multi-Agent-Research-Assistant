"""
Durable pipeline event stream (docs/05 §1, docs/02 §5).

Every pipeline event is a row here first, then published to Redis. On (re)connect
the SSE endpoint replays these rows so a late-joining or reconnecting client loses
nothing; the bigserial id doubles as the SSE Last-Event-ID cursor.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.types import BigIntAutoType, JsonType, UuidType


class AgentLog(Base):
    __tablename__ = "agent_logs"

    id: Mapped[int] = mapped_column(BigIntAutoType, primary_key=True, autoincrement=True)
    session_id: Mapped[uuid.UUID] = mapped_column(
        UuidType,
        ForeignKey("sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    event_type: Mapped[str] = mapped_column(
        String(40), nullable=False
    )  # agent_log|HITL_READY|COMPLETED|FAILED
    agent_name: Mapped[str | None] = mapped_column(String(50), nullable=True)
    payload: Mapped[dict] = mapped_column(JsonType, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )

    session: Mapped["Session"] = relationship("Session", back_populates="agent_logs")  # noqa: F821

    def __repr__(self) -> str:
        return f"<AgentLog id={self.id} type={self.event_type} session={self.session_id}>"
