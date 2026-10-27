"""
The desktop runs under the server's limits, and reports the custom endpoint it will use.

Both found by driving the published 3.0.3 app (v3.0.3 record, Findings 13 and 14):

- `sidecar_run_config` restated the budget defaults instead of sharing them, and restated
  two of them wrong: a 600 s wallclock cap and a $0.50 spend cap, where the server and the
  CLI default every run limit to 0 = unlimited (AGENTS.md). It also never read
  `MAX_INPUT_TOKENS`. A local model at Fast depth hit the 600 s cap mid-run.
- `GET /models/custom/status` on the desktop probed with the process `RunConfig`, which this
  host never sets outside a run — so after Save URL had written the endpoint, Settings still
  said "No endpoint configured" and the run form warned it was unreachable, while runs on it
  worked.

Each test drives the real builder or route; only the network is replaced.
"""

from __future__ import annotations

import httpx
import pytest

import desktop.sidecar as sc
import research_engine.local as local
from app.config import Settings
from desktop.sidecar import create_sidecar_app, save_routing, sidecar_run_config
from tests.workflow.test_desktop_contract_gaps import _mock_probe_transport
from tests.workflow.test_desktop_local_models_without_a_key import KEY_ENV, ROLES

TOKEN = "test-limits-token"
LIMIT_ENV = (
    "MAX_CRITIC_LOOPS",
    "MAX_COST_PER_SESSION_USD",
    "MAX_WALLCLOCK_SECONDS",
    "MAX_INPUT_TOKENS",
    "MAX_PARALLEL_TASKS",
)
LIMIT_FIELDS = (
    "max_critic_loops",
    "max_cost_per_session_usd",
    "max_wallclock_seconds",
    "max_input_tokens",
    "max_parallel_tasks",
)


@pytest.fixture
def clean_env(monkeypatch, tmp_path):
    """No key, no limit override, and an Ollama routing that needs no key."""
    for name in (*KEY_ENV, *LIMIT_ENV):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(sc, "load_env_file", lambda *a, **kw: False)
    monkeypatch.setattr(sc, "stored_keys", dict)
    save_routing(tmp_path, dict.fromkeys(ROLES, "ollama:qwen2.5:7b"))
    return tmp_path


def test_the_desktop_run_limits_default_to_the_servers(clean_env):
    config = sidecar_run_config(fake=False, data_dir=clean_env)

    for name in LIMIT_FIELDS:
        assert getattr(config, name) == Settings.model_fields[name].default, name
    assert config.max_wallclock_seconds == 0
    assert config.max_cost_per_session_usd == 0.0


def test_the_desktop_honours_every_limit_the_cli_does(clean_env, monkeypatch):
    """`MAX_INPUT_TOKENS` used to be read by the CLI and ignored by the desktop."""
    monkeypatch.setenv("MAX_WALLCLOCK_SECONDS", "900")
    monkeypatch.setenv("MAX_COST_PER_SESSION_USD", "1.25")
    monkeypatch.setenv("MAX_INPUT_TOKENS", "50000")

    config = sidecar_run_config(fake=False, data_dir=clean_env)

    assert config.max_wallclock_seconds == 900
    assert config.max_cost_per_session_usd == 1.25
    assert config.max_input_tokens == 50000


def test_the_desktop_and_the_cli_read_limits_through_one_function():
    """Two readers drifted once (600 vs 0); one reader cannot."""
    assert sc.run_limits_from_env is local.run_limits_from_env


@pytest.fixture
async def sidecar(clean_env):
    app = create_sidecar_app(data_dir=clean_env, token=TOKEN, fake=False)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:9") as client:
            yield client


def _auth() -> dict:
    return {"Authorization": f"Bearer {TOKEN}"}


def _gateway(seen: list[httpx.Request]):
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"data": [{"id": "auto/best-fast"}]})

    return handler


async def test_custom_endpoint_status_reports_the_url_saved_in_settings(sidecar, monkeypatch):
    """Save URL, then ask — the exact order the Settings screen uses."""
    saved = await sidecar.put(
        "/api/v1/desktop/keys/custom_endpoint",
        json={"base_url": "http://localhost:20128/v1"},
        headers=_auth(),
    )
    assert saved.status_code == 204
    seen: list[httpx.Request] = []
    monkeypatch.setattr(sc, "stored_keys", lambda: {"custom": "gateway-key"})
    monkeypatch.setattr(httpx, "AsyncClient", _mock_probe_transport(_gateway(seen)))

    resp = await sidecar.get("/api/v1/models/custom/status", headers=_auth())

    assert resp.status_code == 200
    body = resp.json()
    assert body["configured_base_url"] == "http://localhost:20128/v1"
    assert body["reachable"] is True, body
    assert body["models"] == ["auto/best-fast"]
    # It dialled the saved address — port 20128, which the production SSRF guard's port
    # allowlist would refuse — with the stored key, exactly as a run on this host does.
    assert [str(r.url) for r in seen] == ["http://localhost:20128/v1/models"]
    # Compared as a bool so a failure cannot print whatever real key the process holds.
    sent_the_stored_key = seen[0].headers.get("Authorization") == "Bearer gateway-key"
    assert sent_the_stored_key


async def test_with_no_saved_url_the_status_still_says_none_is_configured(sidecar, monkeypatch):
    seen: list[httpx.Request] = []
    monkeypatch.setattr(httpx, "AsyncClient", _mock_probe_transport(_gateway(seen)))

    resp = await sidecar.get("/api/v1/models/custom/status", headers=_auth())

    assert resp.status_code == 200
    assert resp.json()["configured_base_url"] == ""
    assert resp.json()["reachable"] is False
    assert seen == []
