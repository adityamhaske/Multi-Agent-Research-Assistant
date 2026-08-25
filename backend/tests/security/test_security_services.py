"""Unit tests for the M2 security services (docs/06, docs/08 §3)."""

import uuid

import pytest

from app.services import passwords, rate_limit, tokens
from app.services.passwords import WeakPassword

# ── Passwords ─────────────────────────────────────────────────────────────────────


def test_password_too_short_rejected():
    with pytest.raises(WeakPassword):
        passwords.validate_password("short")


def test_common_password_rejected():
    with pytest.raises(WeakPassword):
        passwords.validate_password("password123")


def test_password_over_72_bytes_rejected():
    with pytest.raises(WeakPassword):
        passwords.validate_password("a" * 73)


def test_hash_and_verify_roundtrip():
    h = passwords.hash_password("a-strong-passphrase-2026")
    assert passwords.verify_password("a-strong-passphrase-2026", h)
    assert not passwords.verify_password("wrong", h)


# ── Tokens ────────────────────────────────────────────────────────────────────────


def test_access_token_roundtrip():
    uid = uuid.uuid4()
    token = tokens.create_access_token(uid)
    assert tokens.decode_access_token(token) == uid


def test_refresh_token_hash_is_deterministic_and_opaque():
    raw = tokens.generate_refresh_token()
    assert tokens.hash_refresh_token(raw) == tokens.hash_refresh_token(raw)
    assert raw not in tokens.hash_refresh_token(raw)


def test_refresh_cookie_scoped_to_auth_path():
    assert tokens.refresh_cookie_kwargs()["path"] == "/api/v1/auth"
    assert tokens.access_cookie_kwargs()["path"] == "/"
    assert tokens.refresh_cookie_kwargs()["httponly"] is True


# ── Rate limiting (fake Redis executing the Lua contract) ──────────────────────────


class _FakeRedis:
    """Minimal INCR/EXPIRE/TTL emulation matching the Lua script's semantics."""

    def __init__(self):
        self.counts: dict[str, int] = {}
        self.ttls: dict[str, int] = {}

    async def eval(self, script, numkeys, key, limit, window):
        self.counts[key] = self.counts.get(key, 0) + 1
        if self.counts[key] == 1:
            self.ttls[key] = int(window)
        return [self.counts[key], self.ttls.get(key, -1)]


@pytest.mark.asyncio
async def test_rate_limit_allows_then_blocks_and_keeps_ttl():
    redis = _FakeRedis()
    rule = rate_limit.RateLimit(limit=3, window_seconds=60)
    key = "rl:test:user"

    results = [await rate_limit.check(redis, key, rule) for _ in range(4)]
    assert [r.allowed for r in results] == [True, True, True, False]
    # TTL is set on the very first increment and never lost (docs/06 §2).
    assert all(r.ttl == 60 for r in results)


def test_rate_limit_keys_are_per_operation():
    uid = "u1"
    assert rate_limit.key_research(uid) != rate_limit.key_chat(uid)
    assert rate_limit.key_login_ip("1.2.3.4") != rate_limit.key_login_email("a@b.co")
