"""Add demo flag to sessions.

Demo mode was a process-wide environment variable (`LLM_MODE=fake`), which cannot say
*which* session was scripted — so an exported report carried no evidence of its own
provenance. Persisting it per session is what lets every export path stamp itself
(docs/17 §6.2): the product's whole claim is verifiable output, so a demo artifact that
could pass as real research is a correctness defect, not a cosmetic one.

Defaults to false, so every existing row is treated as real research. That is the safe
direction: mislabelling real work as a demo is recoverable, the reverse is not.

Revision ID: 0010_session_demo
Revises: e9f72cd4cd56
Create Date: 2026-08-14
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0010_session_demo"
down_revision: str | None = "e9f72cd4cd56"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "sessions",
        sa.Column(
            "demo",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("sessions", "demo")
