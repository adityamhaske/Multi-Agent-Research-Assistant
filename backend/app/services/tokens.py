"""
Token service: short-lived access JWTs + opaque rotating refresh tokens
(docs/06_Security.md §1, docs/05 §1 refresh_tokens).

Access tokens are stateless HS256 JWTs (15 min). Refresh tokens are 256-bit opaque
strings stored server-side as sha256 with a jti; every use rotates them and reuse of
a rotated token revokes the family. Cookies are httpOnly, SameSite=Lax, Secure in prod.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

import jwt

from app.config import settings

ACCESS_COOKIE = "access_token"
REFRESH_COOKIE = "refresh_token"


def create_access_token(user_id: UUID) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "type": "access",
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_access_token_expire_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> UUID:
    """Return the user id, or raise jwt exceptions / ValueError on invalid tokens."""
    payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    if payload.get("type") != "access":
        raise ValueError("not an access token")
    return UUID(payload["sub"])


def generate_refresh_token() -> str:
    return secrets.token_urlsafe(32)


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def refresh_expiry() -> datetime:
    return datetime.now(UTC) + timedelta(days=settings.jwt_refresh_token_expire_days)


def cookie_kwargs(max_age: int, *, path: str) -> dict:
    """Shared Set-Cookie attributes for httpOnly auth cookies."""
    return {
        "httponly": True,
        "secure": settings.is_production,
        "samesite": "lax",
        "max_age": max_age,
        "path": path,
    }


def access_cookie_kwargs() -> dict:
    return cookie_kwargs(settings.jwt_access_token_expire_minutes * 60, path="/")


def refresh_cookie_kwargs() -> dict:
    return cookie_kwargs(settings.jwt_refresh_token_expire_days * 86400, path="/api/v1/auth")
