"""
The login limiter does what docs/architecture/06-security.md §4 says: 20 attempts a minute
per IP, and 5 *failures* per 15 minutes per account.

The per-account counter used to count every attempt, successes included, so a person who
signed in correctly six times in fifteen minutes — a second device, a sign-out and back —
was refused with 429 by their own correct password (found by v3.0.2's upgrade checks,
release-audit/v3.0.2/record.md Finding 11). The per-IP counter does count every attempt,
and should: it paces a single source whatever it guesses.

Real Redis and the real app, as in `test_auth_rate_limit.py` and for the same reason: the
limiter is a Lua script, and a stub of it would be testing the stub. Every test uses fresh
addresses and accounts, so a warm Redis cannot leak a count into it.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.services import rate_limit

pytestmark = pytest.mark.asyncio

PASSWORD = "Str0ng-P@ssw0rd-For-Tests!"


@pytest.fixture
async def client(db):  # noqa: ARG001 - the route needs a migrated, truncated database
    from app.main import app

    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c


def _ip() -> str:
    return f"198.51.100.{uuid.uuid4().int % 254 + 1}-{uuid.uuid4().hex[:8]}"


async def _account(client: AsyncClient) -> str:
    email = f"{uuid.uuid4().hex}@example.com"
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": PASSWORD},
        headers={"x-forwarded-for": _ip()},
    )
    assert resp.status_code == 201, resp.text
    return email


async def _login(client: AsyncClient, email: str, password: str, ip: str | None = None):
    return await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
        headers={"x-forwarded-for": ip or _ip()},
    )


def test_the_documented_login_caps_have_not_been_widened():
    # The numbers docs/06 §4 publishes; the tests below read them, so this is what fails
    # if one is quietly raised.
    assert (rate_limit.LOGIN_IP.limit, rate_limit.LOGIN_IP.window_seconds) == (20, 60)
    assert (rate_limit.LOGIN_EMAIL.limit, rate_limit.LOGIN_EMAIL.window_seconds) == (5, 900)


async def test_successful_logins_never_lock_the_account(client: AsyncClient):
    email = await _account(client)
    for i in range(rate_limit.LOGIN_EMAIL.limit + 3):
        resp = await _login(client, email, PASSWORD)
        assert resp.status_code == 200, f"correct login {i + 1} was refused: {resp.text}"


async def test_failures_lock_the_account_even_against_the_right_password(client: AsyncClient):
    email = await _account(client)
    for i in range(rate_limit.LOGIN_EMAIL.limit):
        resp = await _login(client, email, "not-the-password")
        assert resp.status_code == 401, f"failure {i + 1}: {resp.text}"
    # The lock is the point: once an account has absorbed its failures, the right password
    # waits out the window too, or a guesser could keep going until it lands.
    resp = await _login(client, email, PASSWORD)
    assert resp.status_code == 429
    assert resp.json()["detail"] == "Too many attempts. Please wait before trying again."


async def test_successes_do_not_add_to_the_failures_that_lock(client: AsyncClient):
    # Four failures, then any number of correct logins, then a fifth failure: still one
    # attempt short of the lock. Counting successes would have locked at the second login.
    email = await _account(client)
    for _ in range(rate_limit.LOGIN_EMAIL.limit - 1):
        assert (await _login(client, email, "not-the-password")).status_code == 401
    for _ in range(3):
        assert (await _login(client, email, PASSWORD)).status_code == 200
    assert (await _login(client, email, "not-the-password")).status_code == 401
    assert (await _login(client, email, PASSWORD)).status_code == 429


async def test_an_unknown_email_is_locked_exactly_like_a_known_one(client: AsyncClient):
    # Both failure paths must count, or the limiter itself would tell a guesser which
    # addresses have accounts: a known one locking after five, an unknown one never.
    email = f"{uuid.uuid4().hex}@example.com"
    for _ in range(rate_limit.LOGIN_EMAIL.limit):
        resp = await _login(client, email, "not-the-password")
        assert resp.status_code == 401
        assert resp.json()["detail"] == "Invalid email or password."
    assert (await _login(client, email, "not-the-password")).status_code == 429


async def test_the_per_ip_limit_still_counts_every_attempt(client: AsyncClient):
    # Successes included: the address limit paces one source, whatever it sends.
    email = await _account(client)
    ip = _ip()
    for i in range(rate_limit.LOGIN_IP.limit):
        resp = await _login(client, email, PASSWORD, ip=ip)
        assert resp.status_code == 200, f"login {i + 1} from one address: {resp.text}"
    assert (await _login(client, email, PASSWORD, ip=ip)).status_code == 429
