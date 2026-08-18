"""
Durable pipeline event stream (docs/05 §1, docs/02 §5).

Every pipeline event is a row here first, then published to Redis. On (re)connect
the SSE endpoint replays these rows so a late-joining or reconnecting client loses
nothing; the bigserial id doubles as the SSE Last-Event-ID cursor.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.types import BigIntAutoType, JsonType, UuidType


class AgentLog(Base):
    __tablename__ = "agent_logs"

    id: Mapped[int] = mapped_column(BigIntAutoType, primary_key=True, autoincrement=True)
    # The run this event belongs to — a V1 `sessions.id` or a V2 `research_runs.id`.
    #
    # **No foreign key**, deliberately, and for the same reason `audit_events` has none
    # (M2B §9.4): the column is polymorphic across two run tables, so an FK could only
    # point at one of them. Before the V2 native runtime it pointed at `sessions`, which
    # made the trace — the thing a bundle's `trace_available` claims — unwritable for a
    # native run. Cascade-on-delete is replaced by the explicit cleanup the delete paths
    # already perform for checkpoints, which have never had an FK either.
    session_id: Mapped[uuid.UUID] = mapped_column(UuidType, nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(
        String(40), nullable=False
    )  # agent_log|PLAN_READY|HITL_READY|COMPLETED|FAILED
    agent_name: Mapped[str | None] = mapped_column(String(50), nullable=True)
    payload: Mapped[dict] = mapped_column(JsonType, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )

    def __repr__(self) -> str:
        return f"<AgentLog id={self.id} type={self.event_type} session={self.session_id}>"
