"""
Password policy + hashing (docs/06_Security.md §1).

bcrypt directly (passlib is unmaintained). Reject >72 bytes explicitly rather than
letting bcrypt silently truncate. A small embedded breached-password set blocks the
most common choices; production can point BREACHED_PATH at a larger list.
"""

from __future__ import annotations

import bcrypt

MIN_LENGTH = 12
MAX_BYTES = 72

# A tiny sample of the most-common breached passwords. Real deployments should load
# a larger list (e.g. top 10k) — this keeps the dependency-free default honest.
_COMMON = {
    "password",
    "password123",
    "123456789012",
    "qwertyuiop12",
    "letmein12345",
    "changeme1234",
    "administrator",
    "welcome12345",
}


class WeakPassword(ValueError):
    """Raised when a password fails the policy."""


def validate_password(password: str) -> None:
    if len(password) < MIN_LENGTH:
        raise WeakPassword(f"Password must be at least {MIN_LENGTH} characters.")
    if len(password.encode("utf-8")) > MAX_BYTES:
        raise WeakPassword(f"Password must not exceed {MAX_BYTES} bytes.")
    if password.lower() in _COMMON:
        raise WeakPassword("This password is too common. Choose something less guessable.")


def hash_password(password: str) -> str:
    validate_password(password)
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        return False
