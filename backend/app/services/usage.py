"""
Token/cost usage aggregation for the profile page and the monthly limit.

Usage is derived from the `sessions` rows a user already owns — there is no
separate counter to drift out of sync. Three windows are reported:

- month: the current calendar month (UTC). This is the window the limit applies
  to, so it resets on the 1st, matching how users read "monthly limit".
- week: a rolling 7 days.
- last_session: the most recently created session on its own.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.session import Session
from app.schemas.auth import UsageResponse, UsageWindow


def month_start(now: datetime | None = None) -> datetime:
    now = now or datetime.now(UTC)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


async def _window(db: AsyncSession, user_id: uuid.UUID, since: datetime | None) -> UsageWindow:
    q = select(
        func.coalesce(func.sum(Session.total_tokens_input), 0),
        func.coalesce(func.sum(Session.total_tokens_output), 0),
        func.coalesce(func.sum(Session.total_cost_usd), 0),
        func.count(Session.id),
    ).where(Session.user_id == user_id)
    if since is not None:
        q = q.where(Session.created_at >= since)
    tin, tout, cost, count = (await db.execute(q)).one()
    return UsageWindow(
        tokens_input=int(tin),
        tokens_output=int(tout),
        tokens_total=int(tin) + int(tout),
        cost_usd=round(float(cost), 6),
        sessions=int(count),
    )


async def _last_session(db: AsyncSession, user_id: uuid.UUID) -> UsageWindow:
    row = (
        await db.execute(
            select(
                Session.total_tokens_input,
                Session.total_tokens_output,
                Session.total_cost_usd,
            )
            .where(Session.user_id == user_id)
            .order_by(Session.created_at.desc())
            .limit(1)
        )
    ).first()
    if row is None:
        return UsageWindow()
    tin, tout, cost = int(row[0] or 0), int(row[1] or 0), float(row[2] or 0)
    return UsageWindow(
        tokens_input=tin,
        tokens_output=tout,
        tokens_total=tin + tout,
        cost_usd=round(cost, 6),
        sessions=1,
    )


async def monthly_tokens(db: AsyncSession, user_id: uuid.UUID) -> int:
    """Total tokens used in the current calendar month — the limit's basis."""
    window = await _window(db, user_id, month_start())
    return window.tokens_total


async def summary(db: AsyncSession, user_id: uuid.UUID, monthly_limit: int) -> UsageResponse:
    now = datetime.now(UTC)
    month = await _window(db, user_id, month_start(now))
    week = await _window(db, user_id, now - timedelta(days=7))
    last = await _last_session(db, user_id)

    unlimited = monthly_limit <= 0
    remaining = None if unlimited else max(0, monthly_limit - month.tokens_total)
    return UsageResponse(
        month=month,
        week=week,
        last_session=last,
        monthly_token_limit=monthly_limit,
        limit_remaining=remaining,
        limit_reached=(not unlimited and month.tokens_total >= monthly_limit),
    )
