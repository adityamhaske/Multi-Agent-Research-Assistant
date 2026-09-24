"""
`GET /models/prompt-defaults`, driven on both hosts (scope freeze §12, D-2).

The producer is pinned in `tests/security/test_prompt_defaults_exposure.py`. This file pins
what actually crosses the wire: the same body from the server and the desktop, only the
fields the editor needs, nothing protected, and nothing about the caller — a user's saved
overrides must not leak into what is supposed to be the shipped text.

Driven through the golden-journey drivers, so each host runs its real route stack; only the
database and the identity behind the auth gate are substituted.
"""

from __future__ import annotations

import json

import httpx
import pytest

from app.schemas.auth import MAX_PROMPT_OVERRIDE_CHARS
from research_engine.prompt_composition import PROTECTED_PURPOSES, ROLES, editable_defaults
from tests.parity.drivers import desktop_driver, server_driver

PATH = "/models/prompt-defaults"
FORBIDDEN_NAMES = (
    "citation_verify",
    "contradiction_detector",
    "synthesizer.repair",
    "chat.project",
)


@pytest.fixture
async def hosts(tmp_path):
    async with server_driver(tmp_path / "server") as server:
        async with desktop_driver(tmp_path / "desktop") as desktop:
            yield server, desktop


async def _body(host) -> dict:
    resp = await host.request("GET", PATH)
    assert resp.status_code == 200, f"{host.name}: {resp.text}"
    return resp.json()


async def test_both_hosts_serve_an_identical_body(hosts):
    server, desktop = hosts
    assert await _body(server) == await _body(desktop)


async def test_the_body_is_exactly_the_producer_output(hosts):
    server, _ = hosts
    body = await _body(server)
    assert body == {
        "max_chars": MAX_PROMPT_OVERRIDE_CHARS,
        "roles": [
            {"role": d.role, "default_prompt": d.text, "untrusted_content_framed": d.framed}
            for d in editable_defaults()
        ],
    }


async def test_the_body_carries_only_the_fields_the_editor_needs(hosts):
    """No hashes, no runtime state, no preference — the shape is closed."""
    for host in hosts:
        body = await _body(host)
        assert set(body) == {"max_chars", "roles"}, host.name
        assert [r["role"] for r in body["roles"]] == list(ROLES), host.name
        for entry in body["roles"]:
            assert set(entry) == {"role", "default_prompt", "untrusted_content_framed"}, host.name


async def test_no_protected_purpose_appears_on_the_wire(hosts):
    for host in hosts:
        raw = json.dumps(await _body(host))
        for name in (*FORBIDDEN_NAMES, *PROTECTED_PURPOSES):
            assert name not in raw, f"{host.name}: {name}"


async def test_the_body_does_not_depend_on_the_callers_preferences(hosts):
    """Save an override for every role, then ask again: the defaults must not move, and the
    saved text must not appear. The editor shows a user's own text from `GET /auth/me`."""
    for host in hosts:
        before = await _body(host)
        saved = {role: f"SAVED OVERRIDE FOR {role.upper()}" for role in ROLES}
        resp = await host.request(
            "PATCH", "/auth/me", json={"preferences": {"prompt_overrides": saved}}
        )
        assert resp.status_code == 200, f"{host.name}: {resp.text}"
        after = await _body(host)
        assert after == before, host.name
        assert "SAVED OVERRIDE" not in json.dumps(after), host.name


async def test_the_server_requires_authentication():
    """The drivers substitute the auth gate, so this asks the real app with no credentials."""
    from app.main import app as server_app

    transport = httpx.ASGITransport(app=server_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://server.invalid") as c:
        resp = await c.get(f"/api/v1{PATH}")
    assert resp.status_code == 401


async def test_the_desktop_requires_its_launch_token(tmp_path):
    from desktop.sidecar import create_sidecar_app

    app = create_sidecar_app(data_dir=tmp_path, token="launch-token", fake=True)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:9") as c:
            assert (await c.get(f"/api/v1{PATH}")).status_code == 401
            ok = await c.get(f"/api/v1{PATH}", headers={"Authorization": "Bearer launch-token"})
            assert ok.status_code == 200
