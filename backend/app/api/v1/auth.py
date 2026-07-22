"""
Auth endpoints (docs/05 §3, docs/06 §1–§2).

Cookie-based sessions: login sets httpOnly access + refresh cookies; refresh rotates
them; logout revokes the refresh token. Register is neutral (no account enumeration)
and rate-limited; login has per-IP and per-account limits.
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import get_db
from app.db.redis import get_redis
from app.dependencies import get_client_ip, get_current_user
from app.models.user import User
from app.schemas.auth import LoginRequest, RegisterRequest, UserResponse
from app.services import auth_service, rate_limit, tokens
from app.services.passwords import WeakPassword, hash_password, verify_password

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
        db.add(User(email=payload.email, hashed_pw=hashed))
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
