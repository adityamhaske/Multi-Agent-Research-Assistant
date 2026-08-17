"""Persist the design-gate request fields on the session.

`topic_seeds` and `outline_template` are chosen when research is started, but the engine
config is rebuilt from the session row on every resume — a value that lived only on the
original request would be present for the planner and silently empty for every call
after it. Both hosts write these at `Session(...)` construction; both read them back in
their `RunConfig` builder (docs/07 §2, Phase 4).

Nullable with no default, because absent is the meaningful value: no seeds and no
template is today's unconstrained planner, which is what every existing row was.

Revision ID: 0014_plan_gate_request_fields
Revises: 0013_awaiting_plan_status
Create Date: 2026-08-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0014_plan_gate_request_fields"
down_revision: str | None = "0013_awaiting_plan_status"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "sessions",
        sa.Column("topic_seeds", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column("sessions", sa.Column("outline_template", sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column("sessions", "outline_template")
    op.drop_column("sessions", "topic_seeds")
