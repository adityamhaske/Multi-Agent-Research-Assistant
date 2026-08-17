"""Record how much of each report's citation apparatus resolves.

The product's central claim is that every `[n]` is falsifiable. This stores that as one
number per report so History can filter on it without loading every report body
(docs/07 §2, Phase 7).

**Nullable, and NULL is a value with meaning**: "not measured" — a report that made no
citable claims, or a session finished before this column existed. `0.0` means every
marker it did make points at nothing. Those are opposite findings, so no backfill and no
default: inventing a number for a run nobody measured is precisely the failure this
project treats as a P0.

Revision ID: 0015_citation_resolution_rate
Revises: 0014_plan_gate_request_fields
Create Date: 2026-08-16
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0015_citation_resolution_rate"
down_revision: str | None = "0014_plan_gate_request_fields"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "sessions",
        sa.Column("citation_resolution_rate", sa.Numeric(5, 4), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("sessions", "citation_resolution_rate")
