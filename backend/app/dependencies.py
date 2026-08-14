"""
Auth dependencies (docs/engineering/06_Security.md §1).

The browser authenticates via the httpOnly `access_token` cookie (sent
automatically through the same-origin proxy, so SSE works). A Bearer header is
also accepted for non-browser API clients. Password hashing lives in
services.passwords; token logic in services.tokens.
"""

from __future__ import annotations

import jwt
import structlog
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.base import get_db
from app.db.redis import get_redis
from app.models.user import User
from app.services import rate_limit, tokens
from app.services.passwords import hash_password, verify_password  # re-exported

logger = structlog.get_logger()

__all__ = ["hash_password", "verify_password", "get_current_user", "get_client_ip"]


def get_client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _extract_token(request: Request) -> str | None:
    cookie = request.cookies.get(tokens.ACCESS_COOKIE)
    if cookie:
        return cookie
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:]
    return None


async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> User:
    token = _extract_token(request)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    try:
        user_id = tokens.decode_access_token(token)
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError, ValueError, KeyError) as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token"
        ) from e

    user = (
        await db.execute(select(User).where(User.id == user_id, User.is_active.is_(True)))
    ).scalar_one_or_none()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or deactivated"
        )
    return user


async def enforce_research_rate_limit(
    current_user: User = Depends(get_current_user), redis=Depends(get_redis)
) -> None:
    """Per-user research throttle. Disabled (0) by default — see `Settings`.

    Returning early also skips the Redis INCR, so a disabled limit leaves no counter
    behind to expire. Re-enabling it later starts from a clean window rather than from
    usage accumulated while it was off.
    """
    limit = settings.research_rate_limit_per_hour
    if limit <= 0:
        return
    res = await rate_limit.check(
        redis, rate_limit.key_research(current_user.id), rate_limit.RateLimit(limit, 3600)
    )
    if not res.allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Research limit reached ({limit}/hour). "
            f"Retry in {max(res.ttl, 0) // 60 + 1} minutes.",
        )


async def enforce_chat_rate_limit(
    current_user: User = Depends(get_current_user), redis=Depends(get_redis)
) -> None:
    """Per-user chat throttle. Disabled (0) by default — see `Settings`."""
    limit = settings.chat_rate_limit_per_hour
    if limit <= 0:
        return
    res = await rate_limit.check(
        redis, rate_limit.key_chat(current_user.id), rate_limit.RateLimit(limit, 3600)
    )
    if not res.allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Chat limit reached ({limit}/hour). "
            f"Retry in {max(res.ttl, 0) // 60 + 1} minutes.",
        )
