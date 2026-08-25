"""users.api_key_label — a display name for the active BYOK connection

`api_key_provider` is the fixed catalog label ("Custom Endpoint") shared by every user
routed through the `custom:` provider, regardless of which gateway they actually pointed
it at. A user with more than one OpenAI-compatible gateway over time (or several people
reading the same Settings screen) had no way to tell them apart from that label alone —
only the last-4 hint distinguished one saved connection from another.

Nullable, defaulting every existing account to "no nickname" — the catalog label is
still shown when this is unset, so the column adds a capability without changing what
anyone already sees. Renaming is its own endpoint (`PATCH /me/api-key/label`) rather
than a field on `PUT /me/api-key`: a nickname describes which gateway this is, which
does not change just because the underlying key or base URL is rotated, so renaming
must not require re-entering the key.

Revision ID: 0020_api_key_label
Revises: 0019_sessions_cancelled_at
Create Date: 2026-08-25
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0020_api_key_label"
down_revision: Union[str, None] = "0019_sessions_cancelled_at"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("api_key_label", sa.String(length=60), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "api_key_label")
