"""
Project memory — one embedded slice of an approved report (docs/14 §2, §4).

Rows arrive from exactly one place: the COMPLETED transition in
`app/workers/pipeline_runner._persist_outcome`, which is only reachable after a human
approved the draft. Drafts, rejected work and failed runs are therefore absent by
construction rather than by filtering, which is what keeps retrieval trustworthy.
"""

import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

# The stored vector width. Mirrored in migration 0007 and app.adapters, where the
# providers are configured to match it.
EMBEDDING_DIMENSIONS = 768


class MemoryChunk(Base):
    __tablename__ = "memory_chunks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # The report this text came from. Retrieval resolves citations back through it to the
    # report's own sources, which is the whole provenance chain (docs/14 §5).
    source_session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIMENSIONS), nullable=False)
    # Which model produced the vector, e.g. "ollama:nomic-embed-text". Equal width is not
    # equal meaning, so retrieval filters on this rather than assuming comparability.
    embedding_model: Mapped[str] = mapped_column(String(120), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    project: Mapped["Project"] = relationship("Project", back_populates="memory_chunks")  # noqa: F821
    source_session: Mapped["Session"] = relationship("Session")  # noqa: F821

    def __repr__(self) -> str:
        return f"<MemoryChunk id={self.id} project={self.project_id} index={self.chunk_index}>"
