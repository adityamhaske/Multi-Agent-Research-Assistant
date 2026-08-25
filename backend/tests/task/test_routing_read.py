"""
`GET /models/routing` — the verb that was missing from both hosts.

Found by running the stack rather than the suite: the API log showed
`GET /api/v1/models/routing HTTP/1.1" 405` twice on a plain dashboard load. Both hosts
defined PUT and DELETE on `/routing` and no GET, while `frontend/hooks/queries.ts`
already fetched it — so `useModelRouting()`, which the project hub renders its
"agent/model config" panel from, could never succeed.

Worth writing down because of how it hid: nothing failed. The suite was green, the page
rendered, and the panel simply showed its empty state forever. A 405 on a read is
invisible unless someone reads the access log or the panel's absence is noticed.

The desktop half is asserted over real HTTP for the same reason as every other sidecar
test — it is the host whose routes only get exercised at release time.
"""

from __future__ import annotations

import httpx
import pytest
import pytest_asyncio

TOKEN = "test-sidecar-token"

ROUTING = {
    "planner": "ollama:qwen2.5",
    "executor": "ollama:qwen2.5",
    "critic": "ollama:qwen2.5",
    "synthesizer": "ollama:qwen2.5",
    "chat": "ollama:qwen2.5",
}


@pytest_asyncio.fixture
async def sidecar(tmp_path):
    from desktop.sidecar import create_sidecar_app

    app = create_sidecar_app(data_dir=tmp_path, token=TOKEN, fake=True)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:9") as client:
            yield client


def _auth() -> dict:
    return {"Authorization": f"Bearer {TOKEN}"}


def test_the_server_declares_a_get_for_routing():
    """A route-table assertion rather than a request, because the server path needs a
    database this test does not have — but "the verb exists" is exactly the bug, and the
    route table is where a missing verb is visible."""
    from app.api.v1.models import router

    # Matched by suffix: the router carries its own prefix, so `route.path` is the
    # mounted path, not the decorator's argument.
    verbs = {
        method
        for route in router.routes
        if str(getattr(route, "path", "")).endswith("/routing")
        for method in getattr(route, "methods", set())
    }
    assert verbs, "no /routing route found at all — did the path change?"
    assert verbs >= {"GET", "PUT", "DELETE"}, f"/routing is missing a verb: {sorted(verbs)}"


@pytest.mark.asyncio
async def test_desktop_returns_the_saved_routing_and_the_effective_one(sidecar):
    """Both halves matter to the caller: `routing` is what the user chose (null when
    they have chosen nothing), `effective_routing` is what a run would actually dial.
    Collapsing them would make "I have not picked anything" indistinguishable from
    "I picked exactly the deployment defaults"."""
    empty = await sidecar.get("/api/v1/models/routing", headers=_auth())
    assert empty.status_code == 200, "a read must not 405"
    body = empty.json()
    assert body["routing"] is None, "nothing saved yet is null, not a guess"
    assert set(body["effective_routing"]) == set(ROUTING), "a run always has a full routing"

    await sidecar.put("/api/v1/models/routing", headers=_auth(), json={"routing": ROUTING})

    saved = (await sidecar.get("/api/v1/models/routing", headers=_auth())).json()
    assert saved["routing"] == ROUTING
    assert saved["effective_routing"] == ROUTING


@pytest.mark.asyncio
async def test_desktop_read_reflects_a_clear(sidecar):
    await sidecar.put("/api/v1/models/routing", headers=_auth(), json={"routing": ROUTING})
    await sidecar.delete("/api/v1/models/routing", headers=_auth())

    body = (await sidecar.get("/api/v1/models/routing", headers=_auth())).json()
    assert body["routing"] is None
    assert body["effective_routing"], "clearing falls back to the deployment routing"


@pytest.mark.asyncio
async def test_desktop_routing_read_needs_the_token(sidecar):
    assert (await sidecar.get("/api/v1/models/routing")).status_code in (401, 403)
