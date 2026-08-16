"""Add preferences JSON column to users.

Settings IA (docs/07 §2, Phase 3): the customization surface adds more knobs than a
column-per-setting migration cadence can sustain, so this is one JSON blob validated
shape-side by `app.schemas.auth.UserPreferences` rather than a table column each. NULL
means "every preference unset" — the default, and what every existing user keeps until
they change one, same convention `model_routing`'s NULL already uses.

Revision ID: 0011_user_preferences
Revises: 0010_session_demo
Create Date: 2026-08-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0011_user_preferences"
down_revision: str | None = "0010_session_demo"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("preferences", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "preferences")
