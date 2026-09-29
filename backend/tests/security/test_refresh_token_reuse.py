"""
Refresh-token rotation and reuse detection (docs/06 §1).

The README and docs/06 both advertise "rotating refresh tokens with reuse detection", and
`app/services/auth_service.py` implements it — but until these tests nothing exercised it:
the one existing assertion was that `revoke_all_for_user` is *callable*. A security claim the
product makes about itself is a claim a release audit must be able to point at a test for
(RELEASE.md, "Negative and failure-injection coverage").

The rule under test: presenting a token that was already rotated away is treated as theft,
so every live token that user holds is revoked — the attacker's copy *and* the victim's
current one, which forces a fresh login on every device.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest_asyncio
from sqlalchemy import insert, select

from app.models.refresh_token import RefreshToken
from app.models.user import User
from app.services import auth_service, tokens


@pytest_asyncio.fixture
async def user_id(db):
    uid = uuid.uuid4()
    await db.execute(
        insert(User).values(
            id=uid,
            email=f"{uid}@x.invalid",
            hashed_pw="x",
            is_active=True,
            created_at=datetime.now(UTC),
        )
    )
    await db.commit()
    return uid


async def _live_tokens(db, user_id) -> int:
    rows = (await db.execute(select(RefreshToken).where(RefreshToken.user_id == user_id))).scalars()
    return sum(1 for r in rows if r.revoked_at is None)


async def test_rotation_issues_a_new_token_and_retires_the_old(db, user_id):
    first = await auth_service.issue_refresh_token(db, user_id)

    rotated = await auth_service.rotate_refresh_token(db, first)

    assert rotated is not None
    owner, second = rotated
    assert owner == user_id
    assert second != first
    assert await _live_tokens(db, user_id) == 1


async def test_reusing_a_rotated_token_revokes_every_token_the_user_holds(db, user_id):
    stolen = await auth_service.issue_refresh_token(db, user_id)
    _owner, current = await auth_service.rotate_refresh_token(db, stolen)
    other_device = await auth_service.issue_refresh_token(db, user_id)
    assert await _live_tokens(db, user_id) == 2

    # The attacker presents the copy that was already rotated away.
    assert await auth_service.rotate_refresh_token(db, stolen) is None

    # Family revocation: the victim's current token and every other device are out too.
    assert await _live_tokens(db, user_id) == 0
    assert await auth_service.rotate_refresh_token(db, current) is None
    assert await auth_service.rotate_refresh_token(db, other_device) is None


async def test_an_expired_token_is_refused_without_revoking_the_family(db, user_id):
    live = await auth_service.issue_refresh_token(db, user_id)
    expired = tokens.generate_refresh_token()
    db.add(
        RefreshToken(
            user_id=user_id,
            token_hash=tokens.hash_refresh_token(expired),
            expires_at=datetime.now(UTC) - timedelta(minutes=1),
        )
    )
    await db.flush()

    assert await auth_service.rotate_refresh_token(db, expired) is None
    # Expiry is ordinary, not evidence of theft: the user's other session survives.
    assert await auth_service.rotate_refresh_token(db, live) is not None


async def test_an_unknown_token_is_refused(db, user_id):
    await auth_service.issue_refresh_token(db, user_id)

    assert await auth_service.rotate_refresh_token(db, tokens.generate_refresh_token()) is None
    assert await _live_tokens(db, user_id) == 1
