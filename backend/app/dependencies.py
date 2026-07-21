from datetime import UTC, datetime, timedelta
from uuid import UUID

import bcrypt
import jwt
import structlog
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.base import get_db
from app.db.redis import get_redis
from app.models.user import User

logger = structlog.get_logger()
bearer_scheme = HTTPBearer()

# bcrypt silently ignores bytes past 72 — reject instead (docs/06 §1).
_BCRYPT_MAX_BYTES = 72


def hash_password(password: str) -> str:
    pw = password.encode("utf-8")
    if len(pw) > _BCRYPT_MAX_BYTES:
        raise ValueError(f"Password exceeds bcrypt's {_BCRYPT_MAX_BYTES}-byte limit.")
    return bcrypt.hashpw(pw, bcrypt.gensalt(rounds=12)).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        return False


def create_access_token(user_id: UUID) -> tuple[str, int]:
    """Returns (token, expires_in_seconds)."""
    expire = datetime.now(UTC) + timedelta(minutes=settings.jwt_access_token_expire_minutes)
    payload = {"sub": str(user_id), "exp": expire, "type": "access"}
    token = jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
    return token, settings.jwt_access_token_expire_minutes * 60


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    """FastAPI dependency: validates JWT and returns the authenticated User."""
    token = credentials.credentials
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
        user_id: str = payload.get("sub")
        if not user_id or payload.get("type") != "access":
            raise ValueError("Invalid token payload")
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError, ValueError) as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        ) from e

    result = await db.execute(
        select(User).where(User.id == UUID(user_id), User.is_active == True)  # noqa: E712
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or deactivated",
        )
    return user


async def check_rate_limit(
    current_user: User = Depends(get_current_user), redis=Depends(get_redis)
) -> None:
    """Enforce 5 research sessions per hour per user."""
    user_id = current_user.id
    key = f"rate:user:{user_id}:sessions"
    count = await redis.incr(key)
    if count == 1:
        await redis.expire(key, 3600)  # 1 hour TTL
    if count > 5:
        ttl = await redis.ttl(key)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Rate limit exceeded. Maximum 5 sessions per hour. Retry in {ttl // 60} minutes.",
        )
