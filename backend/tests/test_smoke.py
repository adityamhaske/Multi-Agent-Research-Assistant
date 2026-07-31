"""
M0 smoke tests: the app imports, health responds, and config validation
refuses dangerous secrets (docs/engineering/06_Security.md §1).
"""

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import Settings


@pytest.mark.asyncio
async def test_health_endpoint_responds():
    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_settings_reject_placeholder_jwt_secret():
    with pytest.raises(ValueError, match="JWT_SECRET_KEY"):
        Settings(
            database_url="postgresql+asyncpg://u:p@localhost/db",
            jwt_secret_key="change-me-to-a-long-random-secret-string-in-production",
        )


def test_settings_reject_short_jwt_secret():
    with pytest.raises(ValueError, match="JWT_SECRET_KEY"):
        Settings(
            database_url="postgresql+asyncpg://u:p@localhost/db",
            jwt_secret_key="short",
        )


def test_settings_accept_strong_secret():
    s = Settings(
        database_url="postgresql+asyncpg://u:p@localhost/db",
        jwt_secret_key="x" * 64,
    )
    assert s.jwt_secret_key == "x" * 64
