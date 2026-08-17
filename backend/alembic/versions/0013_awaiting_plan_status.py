"""Add AWAITING_PLAN to the session_status enum.

The research design gate (docs/07 §2, Phase 4) is a second durable pause, and it needs a
status of its own rather than reusing AWAITING_APPROVAL. The two resume with different
payloads — a plan edit versus a draft approval — so a session sitting at the plan gate
that reported AWAITING_APPROVAL would offer the reviewer an "Approve" button that resumed
`plan_gate_node` with `{"approved": true}`, a shape it does not understand.

`ADD VALUE` rather than a type rebuild: PostgreSQL 12+ permits it inside a transaction
block as long as the new value is not *used* in the same transaction, and nothing here
writes a row. The deployment floor is well above that — every compose file and the CI
service pin `pgvector/pgvector:pg16`, and pgvector itself needs 13+.

The desktop needs no counterpart: SQLite renders this enum as a plain `VARCHAR(17)` with
`create_constraint=False` (the SQLAlchemy 2.0 default), and 'AWAITING_PLAN' is shorter
than the 'AWAITING_APPROVAL' that set that width — so `sidecar._add_missing_columns` has
nothing to do and an existing install accepts the new value as it stands.

Revision ID: 0013_awaiting_plan_status
Revises: 0012_plan_gate
Create Date: 2026-08-16
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0013_awaiting_plan_status"
down_revision: str | None = "0012_plan_gate"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # IF NOT EXISTS so a database that reached this value by another route (a dev box
    # that ran the ORM's create_all before this migration existed) is not a hard failure.
    op.execute("ALTER TYPE session_status ADD VALUE IF NOT EXISTS 'AWAITING_PLAN'")


def downgrade() -> None:
    """Deliberately a no-op — PostgreSQL cannot drop an enum value.

    The alternatives are both worse than doing nothing. Rebuilding the type would fail
    the `USING status::text::session_status` cast on any row actually parked at the plan
    gate, and rewriting those rows to some other status first would silently discard a
    user's paused session to make a schema operation succeed.

    Leaving the value in place is inert: once the code that writes it is rolled back,
    nothing produces it, and a stale row keeps a status the application can still read.
    """
