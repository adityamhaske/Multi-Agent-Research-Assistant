"""
Auth endpoints (docs/05 §3, docs/06 §1–§2).

Cookie-based sessions: login sets httpOnly access + refresh cookies; refresh rotates
them; logout revokes the refresh token. Register is neutral (no account enumeration)
and rate-limited; login has per-IP and per-account limits.
"""

from __future__ import annotations

from datetime import UTC, datetime

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.base import get_db
from app.db.redis import get_redis
from app.dependencies import get_client_ip, get_current_user
from app.models.user import User
from app.schemas.auth import (
    ApiKeyRequest,
    LoginRequest,
    PasswordChangeRequest,
    ProfileUpdate,
    RegisterRequest,
    UsageResponse,
    UserResponse,
)
from app.services import auth_service, crypto, rate_limit, tokens, usage
from app.services.passwords import WeakPassword, hash_password, verify_password
from research_engine.net_guard import validate_url, SSRFBlocked

logger = structlog.get_logger()
router = APIRouter(prefix="/auth", tags=["Authentication"])


def _set_auth_cookies(response: Response, access: str, refresh: str) -> None:
    response.set_cookie(tokens.ACCESS_COOKIE, access, **tokens.access_cookie_kwargs())
    response.set_cookie(tokens.REFRESH_COOKIE, refresh, **tokens.refresh_cookie_kwargs())


async def _issue_session(response: Response, db: AsyncSession, user: User) -> None:
    access = tokens.create_access_token(user.id)
    refresh = await auth_service.issue_refresh_token(db, user.id)
    _set_auth_cookies(response, access, refresh)


@router.post("/register", status_code=201)
async def register(
    payload: RegisterRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    redis=Depends(get_redis),
):
    ip = get_client_ip(request)
    limited = await rate_limit.check(redis, rate_limit.key_register_ip(ip), rate_limit.REGISTER_IP)
    if not limited.allowed:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS, detail="Too many registrations. Try later."
        )

    try:
        hashed = hash_password(payload.password)
    except WeakPassword as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)) from e

    existing = (
        await db.execute(select(User).where(User.email == payload.email))
    ).scalar_one_or_none()
    if existing is None:
        db.add(
            User(
                email=payload.email,
                hashed_pw=hashed,
                # Public deployments set this so one account can't drain a shared
                # server key; 0 (the default) means unlimited.
                monthly_token_limit=settings.default_monthly_token_limit,
            )
        )
        await db.commit()
        logger.info("user_registered", email=payload.email)
    # Neutral response either way (no enumeration, docs/06 §1).
    return {"message": "If this email is available, the account has been created. Please log in."}


@router.post("/login")
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    redis=Depends(get_redis),
):
    ip = get_client_ip(request)
    ip_rl = await rate_limit.check(redis, rate_limit.key_login_ip(ip), rate_limit.LOGIN_IP)
    email_rl = await rate_limit.check(
        redis, rate_limit.key_login_email(payload.email), rate_limit.LOGIN_EMAIL
    )
    if not ip_rl.allowed or not email_rl.allowed:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many attempts. Please wait before trying again.",
        )

    user = (await db.execute(select(User).where(User.email == payload.email))).scalar_one_or_none()
    if not user or not verify_password(payload.password, user.hashed_pw):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password.")
    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Account is deactivated.")

    await _issue_session(response, db, user)
    await db.commit()
    logger.info("user_login", user_id=str(user.id))
    return {"message": "Logged in."}


@router.post("/refresh")
async def refresh(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    raw = request.cookies.get(tokens.REFRESH_COOKIE)
    if not raw:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="No refresh token.")
    rotated = await auth_service.rotate_refresh_token(db, raw)
    if rotated is None:
        await db.commit()  # persist any family revocation
        response.delete_cookie(tokens.ACCESS_COOKIE, path="/")
        response.delete_cookie(tokens.REFRESH_COOKIE, path="/api/v1/auth")
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token.")
    user_id, new_raw = rotated
    access = tokens.create_access_token(user_id)
    _set_auth_cookies(response, access, new_raw)
    await db.commit()
    return {"message": "Refreshed."}


@router.post("/logout")
async def logout(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    raw = request.cookies.get(tokens.REFRESH_COOKIE)
    if raw:
        await auth_service.revoke_refresh_token(db, raw)
        await db.commit()
    response.delete_cookie(tokens.ACCESS_COOKIE, path="/")
    response.delete_cookie(tokens.REFRESH_COOKIE, path="/api/v1/auth")
    return {"message": "Logged out."}


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: User = Depends(get_current_user)):
    return UserResponse.model_validate(current_user)


@router.patch("/me", response_model=UserResponse)
async def update_me(
    payload: ProfileUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update editable profile fields. Only provided fields change."""
    fields = payload.model_dump(exclude_unset=True)
    for field in ("display_name", "avatar_url", "monthly_token_limit"):
        if field in fields:
            value = fields[field]
            # Treat "" as clearing an optional text field.
            if field in ("display_name", "avatar_url") and value == "":
                value = None
            setattr(current_user, field, value)
    await db.commit()
    await db.refresh(current_user)
    logger.info("profile_updated", user_id=str(current_user.id), fields=sorted(fields))
    return UserResponse.model_validate(current_user)


@router.post("/me/password", status_code=200)
async def change_password(
    payload: PasswordChangeRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    redis=Depends(get_redis),
):
    """Change the account password.

    Requires the current password (a stolen session cookie alone must not be
    enough to lock the owner out), applies the same strength policy as
    registration, and revokes every refresh token for the account so other
    devices are signed out. The caller keeps working: we immediately issue a
    fresh token pair on this response.
    """
    # Reuse the login limiter: this endpoint verifies a password, so it is a
    # brute-force target in exactly the same way.
    ip = get_client_ip(request)
    limited = await rate_limit.check(redis, rate_limit.key_login_ip(ip), rate_limit.LOGIN_IP)
    if not limited.allowed:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many attempts. Please wait before trying again.",
        )

    if not verify_password(payload.current_password, current_user.hashed_pw):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Current password is incorrect.")
    if payload.new_password == payload.current_password:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="New password must be different from the current one.",
        )

    try:
        current_user.hashed_pw = hash_password(payload.new_password)
    except WeakPassword as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)) from e

    # Sign out every other device, then re-issue for this one.
    await auth_service.revoke_all_for_user(db, current_user.id)
    await _issue_session(response, db, current_user)
    await db.commit()
    logger.info("password_changed", user_id=str(current_user.id))
    return {"message": "Password updated. Other devices have been signed out."}


@router.put("/me/api-key", response_model=UserResponse)
async def set_api_key(
    payload: ApiKeyRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Store a user-supplied provider key (BYOK).

    The key is encrypted at rest and never returned by any endpoint — the
    response carries only the provider and a display hint (docs/06 §1).
    """
    if payload.provider == "custom" and payload.api_base_url:
        try:
            validate_url(str(payload.api_base_url))
        except SSRFBlocked as e:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(e)) from e

    current_user.api_key_encrypted = crypto.encrypt(payload.api_key)
    current_user.api_key_provider = payload.provider
    current_user.api_key_base_url = str(payload.api_base_url) if payload.api_base_url else None
    current_user.api_key_hint = crypto.hint(payload.api_key)
    current_user.api_key_set_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(current_user)
    # Log the event, never the key or its hint.
    logger.info("api_key_set", user_id=str(current_user.id), provider=payload.provider)
    return UserResponse.model_validate(current_user)


@router.delete("/me/api-key", response_model=UserResponse)
async def delete_api_key(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Remove the stored BYOK key; the deployment's server key applies again."""
    current_user.api_key_encrypted = None
    current_user.api_key_provider = None
    current_user.api_key_base_url = None
    current_user.api_key_hint = None
    current_user.api_key_set_at = None
    await db.commit()
    await db.refresh(current_user)
    logger.info("api_key_removed", user_id=str(current_user.id))
    return UserResponse.model_validate(current_user)


@router.get("/me/usage", response_model=UsageResponse)
async def get_usage(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Token/cost usage for this month, the last 7 days, and the last session."""
    return await usage.summary(db, current_user.id, current_user.monthly_token_limit)
