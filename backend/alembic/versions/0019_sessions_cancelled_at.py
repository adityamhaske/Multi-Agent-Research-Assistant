"""sessions.cancelled_at — cancellation becomes durable state, not an advisory event

"Stop research" recorded an intent and nothing enforced it. The run continued, and when it
finished, the outcome writer overwrote the stopped session with AWAITING_APPROVAL or
COMPLETED — so a user was shown a stopped run, then a live one, with nothing explaining the
transition. Approving at that point put a report they had tried to abandon into project
memory.

The state has to be durable and readable by the outcome writer, which rules out the Redis
key the server used to set: it carried a 1h TTL, had no reader anywhere in the repository,
and would not have survived a worker restart if it had. A nullable timestamp on the session
is readable by both hosts through the same ORM model, which is what keeps the guard
single-homed.

A timestamp rather than a boolean, matching `research_runs.cancelled_at` that runs already
carries: "when did the user stop this" is a fact worth keeping, and it distinguishes a
cancelled run from one that failed on its own without adding a status to the vocabulary
both hosts map.

No CHECK constraint tying this to `status`, unlike `ck_run_cancelled` on runs. A session reuses
FAILED for a stopped run, so the pair is not mutually determined the way CANCELLED and its
timestamp are, and a constraint here would reject the FAILED rows this column is being
added alongside.

Revision ID: 0019_sessions_cancelled_at
Revises: 0018_agent_logs_polymorphic
Create Date: 2026-08-24
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0019_sessions_cancelled_at"
down_revision: Union[str, None] = "0018_agent_logs_polymorphic"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("sessions", sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("sessions", "cancelled_at")
