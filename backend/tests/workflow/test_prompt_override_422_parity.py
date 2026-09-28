"""
A refused prompt override answers with the same 422 body on both hosts (scope freeze §7).

§7 is explicit, twice: the D-2 table says the error is "identical on server and desktop",
and the validation table ends "Rejections are 422 with an identical body on both hosts."
`test_prompt_override_api.py` proves the desktop refuses what the server refuses; it never
compared what the two *say*, and they did not say the same thing. The server's body is
FastAPI rendering its own validation of the whole request, so each error is located from
`body` and carries the rejected `input`; the desktop validated `body["preferences"]` alone
and stripped both, so the same mistake arrived at a different location with less in it.

The server's route is called for real, with its user and database dependencies stubbed —
the body is refused during FastAPI's parameter validation, before either is used, so the
comparison needs no Postgres. The desktop is its real sidecar app.
"""

from __future__ import annotations

import httpx
import pytest

from app.db.base import get_db
from app.dependencies import get_current_user
from app.main import app as server_app
from app.schemas.auth import MAX_PROMPT_OVERRIDE_CHARS
from desktop.sidecar import create_sidecar_app

TOKEN = "test-422-parity-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
VALID = "You are a meticulous planner. Prefer primary sources over summaries."

#: Every refusal §7's validation table lists, as the body a client would send.
REFUSED = [
    pytest.param({"prompt_overrides": {"critic": ""}}, id="empty"),
    pytest.param({"prompt_overrides": {"critic": "   "}}, id="whitespace-only"),
    pytest.param({"prompt_overrides": {"critic": 42}}, id="non-string-int"),
    pytest.param({"prompt_overrides": {"critic": ["a"]}}, id="non-string-list"),
    pytest.param({"prompt_overrides": {"researcher": VALID}}, id="unknown-role"),
    pytest.param({"prompt_overrides": {"critic.citation_verify": VALID}}, id="purpose-not-role"),
    pytest.param(
        {"prompt_overrides": {"critic": "x" * (MAX_PROMPT_OVERRIDE_CHARS + 1)}}, id="over-limit"
    ),
    pytest.param({"prompt_overrides": "not an object"}, id="not-an-object"),
]


@pytest.fixture
async def server():
    async def no_db():
        yield None

    server_app.dependency_overrides[get_current_user] = lambda: object()
    server_app.dependency_overrides[get_db] = no_db
    try:
        transport = httpx.ASGITransport(app=server_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://server.invalid") as c:
            yield c
    finally:
        server_app.dependency_overrides.pop(get_current_user, None)
        server_app.dependency_overrides.pop(get_db, None)


@pytest.fixture
async def desktop(tmp_path):
    app = create_sidecar_app(data_dir=tmp_path, token=TOKEN, fake=True)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:9") as c:
            yield c


@pytest.mark.parametrize("preferences", REFUSED)
async def test_a_refused_override_has_an_identical_422_body_on_both_hosts(
    server, desktop, preferences
):
    body = {"preferences": preferences}
    on_server = await server.patch("/api/v1/auth/me", headers=AUTH, json=body)
    on_desktop = await desktop.patch("/api/v1/auth/me", headers=AUTH, json=body)
    assert on_server.status_code == on_desktop.status_code == 422
    assert on_desktop.json() == on_server.json()
