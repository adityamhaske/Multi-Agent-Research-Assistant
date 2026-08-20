"""
The registration limiter is real, and stays real (issue #51).

`REGISTER_IP` is brute-force protection, deliberately not configurable — an operator must
not be able to raise a usage cap and switch off credential-stuffing defence in the same
setting. The E2E suite works *around* it (`frontend/e2e/fixtures.ts` clears this suite's
own `rl:*` counters between journeys) rather than turning it down, and this test is the
other half of that arrangement: proof that the cap the suite steps around is still armed.

Run against a real Redis rather than a fake. The limiter's whole substance is one Lua
script doing INCR + conditional EXPIRE atomically; a stub reimplementing that in Python
would be testing the stub, which is the trap `AGENTS.md` names under "a test that stubs
the thing it is testing proves nothing".
"""

from __future__ import annotations

import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.services import rate_limit

pytestmark = pytest.mark.asyncio

#: Strong enough for `hash_password`, which rejects weak input with `WeakPassword`.
PASSWORD = "Str0ng-P@ssw0rd-For-Tests!"


@pytest.fixture
async def client(db):  # noqa: ARG001 - the route needs a migrated, truncated database
    """The real app, entered through its lifespan.

    The lifespan is what calls `init_redis_pool()`, and `get_redis` raises without it.
    Driving the app without it would mean overriding `get_redis` with something of our
    own — which is precisely the stub this test exists not to write.
    """
    from app.main import app

    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c


def _fresh_ip() -> str:
    """An IP no other run has used, so the counter starts at zero without a flush.

    Deriving it from a uuid keeps the test independent of Redis state — repeated local
    runs against a warm Redis are exactly the situation issue #51 is about, and a test
    for that must not itself depend on someone having flushed first.
    """
    return f"203.0.113.{uuid.uuid4().int % 254 + 1}-{uuid.uuid4().hex[:8]}"


async def _register(client: AsyncClient, ip: str):
    return await client.post(
        "/api/v1/auth/register",
        json={"email": f"{uuid.uuid4().hex}@example.com", "password": PASSWORD},
        headers={"x-forwarded-for": ip},
    )


def test_the_documented_cap_has_not_been_quietly_widened():
    """Pin the number itself, not just that some cap exists.

    The tests below read `REGISTER_IP.limit`, so they keep passing if the cap is raised —
    they prove the limiter *works*, not that it is still tight. Raising it to 500 leaves
    them green. This assertion is the one that fails, and it names the value
    `docs/architecture/06-security.md` §2 publishes, so widening the cap has to be a
    deliberate edit to a test that says why.
    """
    assert rate_limit.REGISTER_IP.limit == 5
    assert rate_limit.REGISTER_IP.window_seconds == 3600


async def test_registration_is_capped_per_ip_and_says_so(client: AsyncClient):
    """The documented limit holds exactly, and the refusal names its reason."""
    ip = _fresh_ip()

    for i in range(rate_limit.REGISTER_IP.limit):
        resp = await _register(client, ip)
        assert resp.status_code == 201, f"registration {i + 1} should be allowed: {resp.text}"

    resp = await _register(client, ip)
    assert resp.status_code == 429, "the cap is not enforced — brute-force protection is off"
    assert resp.json()["detail"] == "Too many registrations. Try later."


async def test_the_cap_is_per_ip_not_global(client: AsyncClient):
    """A second address is unaffected by the first one's exhaustion.

    Without this, a limiter keyed globally would pass the test above while locking every
    user out the moment any one address hit the cap.
    """
    exhausted = _fresh_ip()
    for _ in range(rate_limit.REGISTER_IP.limit):
        assert (await _register(client, exhausted)).status_code == 201
    assert (await _register(client, exhausted)).status_code == 429

    assert (await _register(client, _fresh_ip())).status_code == 201
