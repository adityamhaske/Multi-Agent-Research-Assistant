"""Add plan gate columns to sessions.

The research design gate (docs/07 §2, Phase 4): a second durable interrupt after the
planner. plan_json/outline_json hold the reviewer's edited decision, not the planner's
raw proposal — same reasoning as model_routing snapshotting what actually ran rather
than a preference that can change afterwards. skip_plan_gate defaults false: the
confirmed product decision is a second gate after the planner, opt-out not opt-in.

Revision ID: 0012_plan_gate
Revises: 0011_user_preferences
Create Date: 2026-08-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0012_plan_gate"
down_revision: str | None = "0011_user_preferences"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "sessions", sa.Column("plan_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True)
    )
    op.add_column(
        "sessions",
        sa.Column("outline_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "sessions", sa.Column("plan_approved_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "sessions",
        sa.Column("skip_plan_gate", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )


def downgrade() -> None:
    op.drop_column("sessions", "skip_plan_gate")
    op.drop_column("sessions", "plan_approved_at")
    op.drop_column("sessions", "outline_json")
    op.drop_column("sessions", "plan_json")
