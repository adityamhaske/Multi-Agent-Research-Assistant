"""migration ledger

The V1 → V2 migration's own audit record (M2C §5, M2E §2). One row per V1 session the
migration **considered**; absence from this table means `NOT_PROCESSED` and never `EMPTY`.

Separate from the M2D domain tables on purpose: this is not part of the product's schema,
it is the record of how the product's data got here. It outlives the migration (M2C §12),
so it is created by a migration rather than by the tool that writes it.

Revision ID: 0016_migration_ledger
Revises: eafdf189af24
Create Date: 2026-08-17
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0016_migration_ledger"
down_revision: Union[str, None] = "eafdf189af24"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "migration_ledger",
        # The V1 session id IS the identity: a second migration pass finds the existing
        # row rather than writing a competing terminal outcome.
        sa.Column("session_id", sa.Uuid().with_variant(sa.UUID(), "postgresql"), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("v2_run_id", sa.Uuid().with_variant(sa.UUID(), "postgresql"), nullable=True),
        sa.Column("failure_category", sa.String(length=48), nullable=True),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("evidence_outcome", sa.String(length=24), nullable=True),
        sa.Column("revision_outcome", sa.String(length=24), nullable=True),
        sa.Column("artifact_outcome", sa.String(length=24), nullable=True),
        sa.Column("bundle_result", sa.String(length=24), nullable=True),
        sa.Column("rows_written", sa.Integer(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column(
            "started_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("session_id"),
        sa.UniqueConstraint("session_id", name="uq_ledger_session"),
    )
    # No foreign key to `sessions`, deliberately: the ledger must survive the deletion of
    # the row it describes, for the same reason `audit_events` has no FK to its subject
    # (M2B §9.4). A migration record that vanishes with its session cannot answer "what
    # happened to that run?", which is the only question it exists to answer.


def downgrade() -> None:
    op.drop_table("migration_ledger")
