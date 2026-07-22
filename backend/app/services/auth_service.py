"""
Refresh-token lifecycle: issue, rotate, revoke, reuse-detect (docs/06 §1).

A refresh token is opaque; only its sha256 is stored. Rotation issues a new token
and revokes the old one. Presenting an already-revoked token is treated as theft:
the whole family for that user is revoked.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.refresh_token import RefreshToken
from app.services import tokens


async def issue_refresh_token(db: AsyncSession, user_id: UUID) -> str:
    raw = tokens.generate_refresh_token()
    db.add(
        RefreshToken(
            user_id=user_id,
            token_hash=tokens.hash_refresh_token(raw),
            expires_at=tokens.refresh_expiry(),
        )
    )
    await db.flush()
    return raw


async def rotate_refresh_token(db: AsyncSession, raw: str) -> tuple[UUID, str] | None:
    """Validate + rotate. Returns (user_id, new_raw) or None if invalid.

    Reuse of a revoked token revokes every token for that user (family revocation).
    """
    token_hash = tokens.hash_refresh_token(raw)
    row = (
        await db.execute(select(RefreshToken).where(RefreshToken.token_hash == token_hash))
    ).scalar_one_or_none()
    if row is None:
        return None

    now = datetime.now(UTC)
    if row.revoked_at is not None:
        # Reuse of a rotated/revoked token → assume compromise, revoke the family.
        await _revoke_all_for_user(db, row.user_id)
        return None
    if row.expires_at <= now:
        return None

    row.revoked_at = now
    new_raw = await issue_refresh_token(db, row.user_id)
    return row.user_id, new_raw


async def revoke_refresh_token(db: AsyncSession, raw: str) -> None:
    token_hash = tokens.hash_refresh_token(raw)
    await db.execute(
        update(RefreshToken)
        .where(RefreshToken.token_hash == token_hash, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )


async def _revoke_all_for_user(db: AsyncSession, user_id: UUID) -> None:
    await db.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )
