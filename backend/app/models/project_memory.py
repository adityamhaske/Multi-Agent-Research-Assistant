"""
V2 project memory, with provenance to approved artifacts only (M2B §2.14).

**Created, not yet used.** M2D builds the contract; nothing writes these tables.

**The memory boundary is two foreign keys and a check constraint.** `project_memory_provenance`
has exactly one artifact-side foreign key, pointing at `research_artifacts` — and an artifact
cannot exist without an approving review (see `review.py`). So "only approved research becomes
memory" is structural, not a status comparison in a service (M2A §3.10). There is no column
anywhere that could point a memory item at a revision, a run, or a chat message.

**Cardinality is deliberately not fixed** (M2A §13.5). Provenance is a link table rather than
an `artifact_id` column, because the justification for one-artifact-per-item is "that is what
today's chunker does" — an implementation fact, not a domain one. The relationship is
one-to-many in the model and one-to-one in practice until something justifies otherwise.

Like `memory_chunks`, `project_memory_items` is **Postgres-only**: its embedding column is
pgvector. Both tables here are excluded from the desktop's `create_all` via
`POSTGRES_ONLY_TABLES` in `app/models/__init__.py` — provenance to a table that does not
exist is meaningless, so they are excluded together.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.memory_chunk import EMBEDDING_DIMENSIONS
from app.models.types import UuidType


class ProjectMemoryItem(Base):
    """One retrievable chunk of approved knowledge. Wholly derived from artifacts."""

    __tablename__ = "project_memory_items"

    id: Mapped[uuid.UUID] = mapped_column(UuidType, primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UuidType, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIMENSIONS), nullable=False)
    # Vectors from different models are not comparable even at equal width, so retrieval
    # filters on the model that produced them — the rule `memory.retrieve` already enforces.
    embedding_model: Mapped[str] = mapped_column(String(128), nullable=False)
    # SHA-256 over the ordered set of source artifact hashes. Makes re-ingestion idempotent
    # without a group-by over the link table; recomputable from `project_memory_provenance`.
    provenance_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "embedding_model",
            "provenance_digest",
            "chunk_index",
            name="uq_memory_chunk",
        ),
        CheckConstraint("chunk_index >= 0", name="ck_memory_chunk"),
        CheckConstraint("length(provenance_digest) = 64", name="ck_memory_digest"),
    )


class ProjectMemoryProvenance(Base):
    """Which approved artifact(s) a memory item derives from.

    The only artifact-side foreign key in the memory subsystem, and therefore the boundary
    itself. Every durable memory item must reach at least one approved ResearchArtifact
    through this table — a rule the database cannot express ("a child row must exist"), so
    that remainder is application-enforced (M2B §9.4).
    """

    __tablename__ = "project_memory_provenance"

    memory_item_id: Mapped[uuid.UUID] = mapped_column(
        UuidType,
        ForeignKey("project_memory_items.id", ondelete="CASCADE"),
        primary_key=True,
    )
    artifact_id: Mapped[uuid.UUID] = mapped_column(
        UuidType,
        ForeignKey("research_artifacts.id", ondelete="CASCADE"),
        primary_key=True,
    )
