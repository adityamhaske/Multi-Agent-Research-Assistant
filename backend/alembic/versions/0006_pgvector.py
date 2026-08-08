"""Enable the pgvector extension (docs/14 §3).

Separated from the table that uses it so the prerequisite fails loudly and on its own
if the deployment is still running a stock Postgres image. The compose files pin
pgvector/pgvector:pgNN, matching each volume's major version.

Revision ID: 0006_pgvector
Revises: 0005_projects
Create Date: 2026-08-06
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0006_pgvector"
down_revision: str | None = "0005_projects"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")


def downgrade() -> None:
    # Dropping the extension would take every vector column with it. Memory tables are
    # removed by their own migration; leaving the extension installed is harmless.
    pass
