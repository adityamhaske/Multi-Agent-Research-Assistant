"""
Project memory — one embedded slice of an approved report.

Rows arrive only from an approval transition, never from a draft or a failed run, so
drafts and rejected work are absent by construction rather than by filtering. That is what
keeps retrieval trustworthy in a way a "remember everything" feature is not.
"""

import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.types import UuidType

# The stored vector width. Mirrored in migration 0007 and app.adapters, where the
# providers are configured to match it.
EMBEDDING_DIMENSIONS = 768


class MemoryChunk(Base):
    __tablename__ = "memory_chunks"

    id: Mapped[uuid.UUID] = mapped_column(UuidType, primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UuidType,
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # The report this text came from, and the whole provenance chain: retrieval resolves a
    # citation back through it to that report's own sources.
    #
    # Polymorphic across `research_runs.id` and `sessions.id`, so it carries no foreign key
    # — one constraint cannot point at two tables, and the version that did meant reports
    # from the current runtime could never be indexed at all. Deletion is the ORM's job
    # here (see the relationships on `ResearchRun` and `Session`); `project_id` below still
    # cascades in the database, which is what makes "delete the project, lose its memory"
    # hold whatever else happens.
    source_report_id: Mapped[uuid.UUID] = mapped_column(UuidType, nullable=False, index=True)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIMENSIONS), nullable=False)
    # Which model produced the vector, e.g. "ollama:nomic-embed-text". Equal width is not
    # equal meaning, so retrieval filters on this rather than assuming comparability.
    embedding_model: Mapped[str] = mapped_column(String(120), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    project: Mapped["Project"] = relationship("Project", back_populates="memory_chunks")  # noqa: F821

    def __repr__(self) -> str:
        return f"<MemoryChunk id={self.id} project={self.project_id} index={self.chunk_index}>"
