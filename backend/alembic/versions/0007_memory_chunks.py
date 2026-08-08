"""Project memory: embedded chunks of approved reports (docs/14 §2, §3).

Only reports that passed the human approval gate are ever written here — that is the
design idea, not an implementation detail (docs/14 §2). The schema enforces what it can:

- **Both foreign keys cascade.** A deleted project or a deleted session must not leave
  orphan vectors behind; "deleting a project deletes its memory" is a Definition of Done
  item (docs/14 §9), so it is a database guarantee rather than application etiquette.
- **`(source_session_id, chunk_index)` is unique.** Chunking is deterministic, so
  re-ingesting a report collides with its existing rows instead of silently doubling the
  corpus. Ingestion can therefore be retried after a failure.
- **`embedding_model` is NOT NULL.** Vectors from different models are not comparable
  even at equal width, so every row records what produced it and retrieval filters on it
  (docs/14 §4). Without this column a provider switch returns confident nonsense.

Requires the extension enabled by 0006, and pgvector >= 0.5.0 for the HNSW index.

Revision ID: 0007_memory_chunks
Revises: 0006_pgvector
Create Date: 2026-08-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0007_memory_chunks"
down_revision: str | None = "0006_pgvector"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Kept in step with app.adapters.EMBEDDING_DIMENSIONS. Every supported provider is
# configured to this width, so changing providers is a re-index, not a migration.
EMBEDDING_DIMENSIONS = 768

# HNSW landed in pgvector 0.5.0. An older extension would fail on the CREATE INDEX below
# with a bare syntax error, so the version is checked first and reported as what it is.
_MIN_PGVECTOR = (0, 5, 0)


def _assert_hnsw_available() -> None:
    version = op.get_bind().execute(
        sa.text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
    ).scalar()
    if version is None:
        raise RuntimeError(
            "The pgvector extension is not installed. Migration 0006 enables it; a stock "
            "postgres image cannot, which is why the compose files pin "
            "pgvector/pgvector:pgNN."
        )
    parts = tuple(int(part) for part in version.split(".")[:3] if part.isdigit())
    if parts < _MIN_PGVECTOR:
        raise RuntimeError(
            f"pgvector {version} is too old for an HNSW index (needs "
            f"{'.'.join(map(str, _MIN_PGVECTOR))}+). Upgrade the Postgres image."
        )


def upgrade() -> None:
    _assert_hnsw_available()

    op.create_table(
        "memory_chunks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "source_session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(EMBEDDING_DIMENSIONS), nullable=False),
        sa.Column("embedding_model", sa.String(120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_index("ix_memory_chunks_project_id", "memory_chunks", ["project_id"])
    op.create_index(
        "ix_memory_chunks_source_session_id", "memory_chunks", ["source_session_id"]
    )
    # Re-ingestion lands on these rows rather than duplicating them.
    op.create_index(
        "uq_memory_chunks_session_chunk",
        "memory_chunks",
        ["source_session_id", "chunk_index"],
        unique=True,
    )
    # Cosine distance (`<=>`), matching the retrieval query. Embeddings from every
    # supported provider are direction-carrying, so cosine is the meaningful metric.
    op.execute(
        "CREATE INDEX ix_memory_chunks_embedding_hnsw ON memory_chunks "
        "USING hnsw (embedding vector_cosine_ops)"
    )


def downgrade() -> None:
    op.drop_table("memory_chunks")
