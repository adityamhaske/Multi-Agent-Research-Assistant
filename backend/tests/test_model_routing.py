"""
Per-user model routing: validation and resolution (docs/12 M8).

Validation runs on write, not on run. That ordering is the point: a preference that
survives `validate()` is guaranteed startable, so a research run can never fail partway
through on a model that could have been rejected the moment the user picked it.
"""

from __future__ import annotations

import pytest

from app.services import model_routing
from app.services.model_routing import InvalidRouting
from research_engine import catalog
from research_engine.runconfig import ROLES


def _valid() -> dict[str, str]:
    return dict(catalog.preset("anthropic", "balanced"))


class _FakeUser:
    """Just the fields the service reads — avoids needing a DB for pure logic."""

    def __init__(self, api_key_provider=None, model_routing=None):
        self.api_key_provider = api_key_provider
        self.model_routing = model_routing


# ── Validation ─────────────────────────────────────────────────────────────────────


def test_a_preset_validates():
    assert model_routing.validate(_valid()) == _valid()


def test_routing_must_cover_every_role():
    partial = _valid()
    del partial["critic"]
    with pytest.raises(InvalidRouting) as e:
        model_routing.validate(partial)
    assert "critic" in str(e.value)


def test_unknown_role_is_rejected():
    extra = _valid() | {"summarizer": "anthropic:claude-opus-5"}
    with pytest.raises(InvalidRouting) as e:
        model_routing.validate(extra)
    assert "summarizer" in str(e.value)


def test_route_must_be_provider_colon_model():
    bad = _valid() | {"planner": "claude-opus-5"}  # no provider prefix
    with pytest.raises(InvalidRouting) as e:
        model_routing.validate(bad)
    assert "provider:model" in str(e.value)


def test_unknown_provider_is_rejected():
    bad = _valid() | {"planner": "skynet:claude-opus-5"}
    with pytest.raises(InvalidRouting) as e:
        model_routing.validate(bad)
    assert "skynet" in str(e.value)


def test_model_outside_the_catalog_is_rejected():
    bad = _valid() | {"planner": "anthropic:claude-imaginary-9"}
    with pytest.raises(InvalidRouting) as e:
        model_routing.validate(bad)
    assert "claude-imaginary-9" in str(e.value)


def test_unpriced_model_is_rejected_because_it_would_break_the_budget_guard():
    spec = catalog.ModelSpec(
        provider="openrouter",
        model_id="test/unpriced",
        display_name="Unpriced",
        input_per_mtok=None,
        output_per_mtok=None,
    )
    catalog.register(spec)
    try:
        bad = _valid() | {"planner": "openrouter:test/unpriced"}
        with pytest.raises(InvalidRouting) as e:
            model_routing.validate(bad)
        assert "price" in str(e.value).lower()
    finally:
        catalog.CATALOG.pop("test/unpriced", None)


def test_non_dict_is_rejected():
    with pytest.raises(InvalidRouting):
        model_routing.validate(["anthropic:claude-opus-5"])


def test_validate_returns_canonical_routes():
    """Stored values stay comparable, so a later equality check is meaningful."""
    cleaned = model_routing.validate(_valid())
    for role, route in cleaned.items():
        spec = catalog.get(route.partition(":")[2])
        assert route == spec.route, role


# ── Availability ───────────────────────────────────────────────────────────────────


def test_local_models_are_always_available():
    """Ollama needs no key, so it must never be gated behind one."""
    assert "ollama" in model_routing.available_providers(_FakeUser())


def test_a_users_own_key_makes_that_provider_available():
    user = _FakeUser(api_key_provider="anthropic")
    assert "anthropic" in model_routing.available_providers(user)


def test_availability_is_sorted_and_deduplicated():
    user = _FakeUser(api_key_provider="ollama")  # already implicitly available
    providers = model_routing.available_providers(user)
    assert providers == sorted(set(providers))


# ── Resolution ─────────────────────────────────────────────────────────────────────


def test_resolution_prefers_session_then_user_then_deployment():
    session_routing = {r: "anthropic:claude-opus-5" for r in ROLES}
    user_routing = {r: "anthropic:claude-haiku-4-5" for r in ROLES}

    assert (
        model_routing.resolve(session_routing=session_routing, user_routing=user_routing)
        is session_routing
    )
    assert model_routing.resolve(session_routing=None, user_routing=user_routing) is user_routing
    assert (
        model_routing.resolve(session_routing=None, user_routing=None)
        == model_routing.deployment_default()
    )


def test_deployment_default_covers_every_role():
    assert set(model_routing.deployment_default()) == set(ROLES)


def test_a_resolved_routing_is_startable():
    """The contract the whole layer exists to keep: resolve → validate_pricing passes."""
    from dataclasses import replace

    from app.runtime import run_config_from_settings
    from research_engine import llm_factory

    routing = model_routing.resolve(
        session_routing=None, user_routing=dict(catalog.preset("anthropic", "best"))
    )
    cfg = replace(
        run_config_from_settings(),
        llm_mode="real",
        models=routing,
        provider_keys={"anthropic": "sk-test"},
    )
    llm_factory.validate_pricing(cfg)  # must not raise
