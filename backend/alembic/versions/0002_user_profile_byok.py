"""User profile fields, BYOK provider key, and monthly token limit.

Additive only — every column is nullable or has a server default, so this applies
cleanly to a populated users table without backfill.

Revision ID: 0002_user_profile_byok
Revises: 0001_initial_v2
"""

from alembic import op
import sqlalchemy as sa

revision = "0002_user_profile_byok"
down_revision = "0001_initial_v2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("display_name", sa.String(length=80), nullable=True))
    op.add_column("users", sa.Column("avatar_url", sa.Text(), nullable=True))
    # BYOK: ciphertext + display-only hint. Never stores plaintext.
    op.add_column("users", sa.Column("api_key_encrypted", sa.Text(), nullable=True))
    op.add_column("users", sa.Column("api_key_provider", sa.String(length=20), nullable=True))
    op.add_column("users", sa.Column("api_key_hint", sa.String(length=16), nullable=True))
    op.add_column(
        "users", sa.Column("api_key_set_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "users",
        sa.Column(
            "monthly_token_limit",
            sa.Integer(),
            nullable=False,
            server_default="0",  # 0 = unlimited
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "monthly_token_limit")
    op.drop_column("users", "api_key_set_at")
    op.drop_column("users", "api_key_hint")
    op.drop_column("users", "api_key_provider")
    op.drop_column("users", "api_key_encrypted")
    op.drop_column("users", "avatar_url")
    op.drop_column("users", "display_name")
