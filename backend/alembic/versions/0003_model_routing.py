"""Per-user model routing preference and per-session routing snapshot.

Additive only — both columns are nullable, so this applies cleanly to populated
tables with no backfill. NULL on `users.model_routing` means "use the deployment's
MODEL_* routing", which is exactly what every existing user was already doing.

Revision ID: 0003_model_routing
Revises: 0002_user_profile_byok
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003_model_routing"
down_revision = "0002_user_profile_byok"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The user's saved preference: {"planner": "anthropic:claude-opus-5", …}.
    op.add_column(
        "users",
        sa.Column("model_routing", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    # What actually ran, snapshotted per session so a finished report stays attributable
    # to the models that wrote it even after the user changes their preference.
    op.add_column(
        "sessions",
        sa.Column("model_routing", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("sessions", "model_routing")
    op.drop_column("users", "model_routing")
