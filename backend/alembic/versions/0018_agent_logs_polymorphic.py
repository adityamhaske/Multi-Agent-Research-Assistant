"""agent_logs.session_id becomes polymorphic across V1 sessions and V2 runs

The column identifies "the run this event belongs to", and there are now two run tables. An
FK can only point at one of them, so before this a V2-native run could not write a trace at
all — and `trace_available` in a bundle is a claim about exactly that trace.

Same reasoning as `audit_events`, which has never had an FK to its subject (M2B §9.4):
a polymorphic reference with no FK, and deletion handled explicitly by the paths that delete
a run. `checkpoints` have always worked this way too — `app/services/checkpoints.py` exists
precisely because the checkpointer's `thread_id` has no FK back to `sessions`.

**Trade-off, stated rather than discovered later:** dropping the FK also drops
`ON DELETE CASCADE`. Deleting a session no longer removes its `agent_logs` rows at the
database level. The ORM relationship on `Session` cascades in the application instead
(`cascade="all, delete-orphan"` over an explicit `primaryjoin`), which is the path the delete
endpoint uses. A row inserted by something that bypasses the ORM and then orphaned is the
residual risk, and it is the same risk the checkpoint tables already carry.

Revision ID: 0018_agent_logs_polymorphic
Revises: 0017_m2f_domain_fidelity
Create Date: 2026-08-18
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0018_agent_logs_polymorphic"
down_revision: Union[str, None] = "0017_m2f_domain_fidelity"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()

    # The constraint's NAME is reflected, not hardcoded. `0001` created it through the
    # metadata naming convention (`fk_agent_logs_session_id_sessions`), a database built by
    # `create_all` may name it differently, and a hardcoded guess fails the migration on the
    # environments it does not match — which is exactly what happened on the first attempt.
    names = [
        fk["name"]
        for fk in sa.inspect(bind).get_foreign_keys("agent_logs")
        if fk.get("referred_table") == "sessions" and fk.get("name")
    ]
    if not names:
        # Already polymorphic — a database built from the current models by `create_all`.
        return

    if bind.dialect.name == "sqlite":
        # SQLite cannot drop a constraint in place; batch mode rebuilds the table.
        with op.batch_alter_table("agent_logs", schema=None) as batch:
            for name in names:
                batch.drop_constraint(name, type_="foreignkey")
        return
    for name in names:
        op.drop_constraint(name, "agent_logs", type_="foreignkey")


def downgrade() -> None:
    # Reinstating the FK will fail if any V2-native run has written a trace, which is
    # correct: those rows reference `research_runs`, and the constraint would be a lie.
    op.create_foreign_key(
        "fk_agent_logs_session_id_sessions",
        "agent_logs",
        "sessions",
        ["session_id"],
        ["id"],
        ondelete="CASCADE",
    )
