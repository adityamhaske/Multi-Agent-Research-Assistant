"""
The migration ledger table (M2C §5, M2E §2).

One row per V1 session **considered** by the V1→V2 migration. Absence of a row means
`NOT_PROCESSED` — never `EMPTY`. That distinction is the reason the table exists, and since
S6 was withdrawn it is the **only** place `EMPTY` / `CHECKPOINT_MISSING` / `READ_FAILURE` are
told apart (M2F Amendment §9).

**Filed under `app/models/` rather than in `migration/`** because it is a table in the
product database, created by a revision in the product's own Alembic chain, and read by the
product: `app/v2_bundle.py` consults it before asserting that a run gathered no evidence.
The migration *tool* stays in `migration/`; `migration.ledger` re-exports these names so its
own imports read as they did.

Not dropped when the migration finishes: it is the record of what could and could not be
recovered, and it outlives the migration (M2C §12).
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.types import UuidType


class MigrationStatus(enum.StrEnum):
    """Terminal unless stated. `NOT_PROCESSED` is represented by the ABSENCE of a row."""

    IN_PROGRESS = "IN_PROGRESS"  # non-terminal
    MIGRATED = "MIGRATED"
    MIGRATED_WITH_MISMATCH = "MIGRATED_WITH_MISMATCH"
    EMPTY = "EMPTY"  # checkpoint read, zero evidence
    CHECKPOINT_MISSING = "CHECKPOINT_MISSING"  # no snapshot at all
    READ_FAILURE = "READ_FAILURE"  # snapshot exists, could not decode
    NO_REPORT = "NO_REPORT"
    INCONSISTENT_V1 = "INCONSISTENT_V1"  # unmigratable without inventing a fact
    FAILED = "FAILED"  # retryable


TERMINAL = frozenset(MigrationStatus) - {MigrationStatus.IN_PROGRESS}


class MigrationLedger(Base):
    """Exactly one row per considered session; `attempt` counts retries in place."""

    __tablename__ = "migration_ledger"

    # The V1 session id IS the identity. Deterministic by construction: a second run of the
    # migration finds the existing row rather than creating a competing terminal outcome.
    session_id: Mapped[uuid.UUID] = mapped_column(UuidType, primary_key=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    # Set only when a run actually produced V2 rows. Same value as session_id by design
    # (§ deterministic identity), stored so the ledger is readable without knowing that.
    v2_run_id: Mapped[uuid.UUID | None] = mapped_column(UuidType, nullable=True)

    failure_category: Mapped[str | None] = mapped_column(String(48), nullable=True)
    # Diagnosis, not payload: an exception message and the offending id, never a report,
    # never a snippet, never a key.
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)

    evidence_outcome: Mapped[str | None] = mapped_column(String(24), nullable=True)
    revision_outcome: Mapped[str | None] = mapped_column(String(24), nullable=True)
    artifact_outcome: Mapped[str | None] = mapped_column(String(24), nullable=True)
    bundle_result: Mapped[str | None] = mapped_column(String(24), nullable=True)

    rows_written: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (UniqueConstraint("session_id", name="uq_ledger_session"),)
