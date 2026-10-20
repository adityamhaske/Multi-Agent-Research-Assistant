"""
A desktop with Ollama and no API key can research, as its Settings page says it can.

The 3.0.2 release check found three defects that together closed that path on every desktop
release since 2.1.0, while the server ran it:

- `sidecar_run_config` refused any run when no key was stored, Ollama routing or not — the
  CLI and the server both exempt keyless providers.
- The model catalog answered `available_providers` from keys alone, so `ollama` was never
  in it, and Settings offered no local preset.
- `PUT /desktop/keys/custom_endpoint` was declared after `PUT /desktop/keys/{provider}`, which
  took the path first and answered "Unknown provider." — so the one keyless workaround a
  user could reach in the GUI could not be saved either.

Each test drives the real function or route; nothing here stubs the rule it is testing.
"""

from __future__ import annotations

import json

import httpx
import pytest

import desktop.sidecar as sc
from desktop.sidecar import create_sidecar_app, save_routing, sidecar_run_config
from tests.workflow.test_desktop_contract_gaps import (
    _mock_probe_transport,
    _ollama_down,
    _ollama_serving,
)

TOKEN = "test-keyless-token"
ROLES = ("planner", "executor", "critic", "synthesizer", "chat")
KEY_ENV = (
    "GOOGLE_API_KEY",
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "OPENROUTER_API_KEY",
    "CUSTOM_API_KEY",
)


@pytest.fixture
def no_keys(monkeypatch):
    """No key anywhere this host looks: environment, `.env`, keychain."""
    for name in KEY_ENV:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(sc, "load_env_file", lambda *a, **kw: False)
    monkeypatch.setattr(sc, "stored_keys", dict)


@pytest.fixture
async def sidecar(tmp_path, no_keys):
    app = create_sidecar_app(data_dir=tmp_path, token=TOKEN, fake=False)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:9") as client:
            yield client


def _auth() -> dict:
    return {"Authorization": f"Bearer {TOKEN}"}


def test_ollama_routing_needs_no_key(tmp_path, no_keys):
    save_routing(tmp_path, dict.fromkeys(ROLES, "ollama:qwen2.5:7b"))

    config = sidecar_run_config(fake=False, data_dir=tmp_path)

    assert config.llm_mode == "real"
    assert set(config.models.values()) == {"ollama:qwen2.5:7b"}
    assert config.provider_keys == {}


def test_a_hosted_route_with_no_key_is_still_refused_up_front(tmp_path, no_keys):
    save_routing(tmp_path, dict.fromkeys(ROLES, "google:gemini-2.5-flash"))

    with pytest.raises(RuntimeError, match="No provider key found"):
        sidecar_run_config(fake=False, data_dir=tmp_path)


def test_a_custom_endpoint_url_is_not_a_key(tmp_path, no_keys):
    """The URL makes `custom:` routes reachable; it must not satisfy a hosted route."""
    sc.save_custom_endpoint(tmp_path, "http://localhost:11434/v1")
    save_routing(tmp_path, dict.fromkeys(ROLES, "google:gemini-2.5-flash"))

    with pytest.raises(RuntimeError, match="No provider key found"):
        sidecar_run_config(fake=False, data_dir=tmp_path)


async def test_the_catalog_offers_ollama_with_no_key(sidecar, monkeypatch):
    monkeypatch.setattr(httpx, "AsyncClient", _mock_probe_transport(_ollama_serving("qwen2.5:7b")))

    body = (await sidecar.get("/api/v1/models", headers=_auth())).json()

    # The server's `model_routing.available_providers` lists ollama unconditionally;
    # Settings offers a provider's presets only when it is listed here.
    assert body["available_providers"] == ["ollama"]
    assert body["presets"]["ollama"]["balanced"]["planner"] == "ollama:qwen2.5:7b"


async def test_the_catalog_offers_custom_once_its_url_is_saved(sidecar, monkeypatch):
    monkeypatch.setattr(httpx, "AsyncClient", _mock_probe_transport(_ollama_down))
    put = await sidecar.put(
        "/api/v1/desktop/keys/custom_endpoint",
        headers=_auth(),
        json={"base_url": "http://localhost:11434/v1"},
    )
    assert put.status_code == 204

    body = (await sidecar.get("/api/v1/models", headers=_auth())).json()
    assert body["available_providers"] == ["custom", "ollama"]


async def test_the_custom_endpoint_url_saves_and_reads_back(sidecar, tmp_path):
    put = await sidecar.put(
        "/api/v1/desktop/keys/custom_endpoint",
        headers=_auth(),
        json={"base_url": " http://localhost:11434/v1 "},
    )
    assert put.status_code == 204, put.text

    got = await sidecar.get("/api/v1/desktop/keys/custom_endpoint", headers=_auth())
    assert got.json() == {"base_url": "http://localhost:11434/v1"}
    stored = json.loads((tmp_path / "custom_endpoint.json").read_text(encoding="utf-8"))
    assert stored["base_url"] == "http://localhost:11434/v1"

    cleared = await sidecar.put(
        "/api/v1/desktop/keys/custom_endpoint", headers=_auth(), json={"base_url": ""}
    )
    assert cleared.status_code == 204
    got = await sidecar.get("/api/v1/desktop/keys/custom_endpoint", headers=_auth())
    assert got.json() == {"base_url": None}


async def test_a_real_provider_key_route_still_rejects_unknown_names(sidecar):
    """Moving the custom endpoint routes must not loosen the provider route beside them."""
    resp = await sidecar.put(
        "/api/v1/desktop/keys/not_a_provider", headers=_auth(), json={"key": "x"}
    )
    assert resp.status_code == 422
    assert resp.json()["detail"] == "Unknown provider."
