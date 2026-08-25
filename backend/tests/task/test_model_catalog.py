"""
Model catalog and provider routing (docs/12 M8, docs/13 §6).

The regression this file exists for: `claude-opus-5` was absent from both the old flat
price table and the old `_ANTHROPIC_NO_SAMPLING` prefix tuple, so selecting it failed twice
over — `validate_pricing()` refused to boot, and had it booted, every request would have
sent a `temperature` and taken a 400 from the provider.

The deeper fix is structural: which models reject sampling parameters is now a catalog
fact rather than a hand-maintained prefix list, so the next model can't slip through the
same gap. These tests pin both the specific model and the general property.
"""

from __future__ import annotations

import pytest

from research_engine import catalog, llm_factory
from research_engine.runconfig import ROLES, RunConfig, reset_run_config, set_run_config

# ── The Opus 5 regression ──────────────────────────────────────────────────────────


def test_opus_5_is_in_the_catalog_and_priced():
    spec = catalog.get("claude-opus-5")
    assert spec is not None, "claude-opus-5 missing from the catalog"
    assert spec.priced
    assert (spec.input_per_mtok, spec.output_per_mtok) == (5.00, 25.00)
    assert spec.context_window == 1_000_000


def test_opus_5_rejects_sampling_params():
    assert llm_factory.sampling_supported("claude-opus-5") is False


def test_routing_to_opus_5_passes_pricing_validation():
    cfg = RunConfig(
        llm_mode="real",
        models={r: "anthropic:claude-opus-5" for r in ROLES},
        provider_keys={"anthropic": "sk-test"},
    )
    llm_factory.validate_pricing(cfg)  # must not raise


def test_opus_5_client_is_built_without_a_temperature():
    """The end of the bug: a temperature on Opus 5 is a 400 from the provider."""
    cfg = RunConfig(
        llm_mode="real",
        models={r: "anthropic:claude-opus-5" for r in ROLES},
        provider_keys={"anthropic": "sk-test"},
    )
    token = set_run_config(cfg)
    try:
        model = llm_factory.get_llm("synthesizer")
    finally:
        reset_run_config(token)

    # langchain-anthropic leaves an unset temperature as None.
    assert getattr(model, "temperature", None) is None
    assert model.model == "claude-opus-5"


def test_a_sampling_capable_model_still_gets_its_temperature():
    """The omission must be targeted, not a blanket removal."""
    cfg = RunConfig(
        llm_mode="real",
        models={r: "anthropic:claude-haiku-4-5" for r in ROLES},
        provider_keys={"anthropic": "sk-test"},
    )
    token = set_run_config(cfg)
    try:
        model = llm_factory.get_llm("critic")
    finally:
        reset_run_config(token)

    assert model.temperature == 0.0  # the critic's configured value


# ── Catalog invariants ─────────────────────────────────────────────────────────────


def test_every_catalog_entry_is_self_consistent():
    for model_id, spec in catalog.CATALOG.items():
        assert spec.model_id == model_id, f"{model_id} keyed under the wrong id"
        assert spec.provider in catalog.KNOWN_PROVIDERS, f"{model_id}: unknown provider"
        assert spec.display_name, f"{model_id}: no display name"
        assert spec.route == f"{spec.provider}:{spec.model_id}"


def test_no_catalog_entry_carries_a_guessed_price():
    """A price of 0 is only honest for local inference; elsewhere it must be a real number
    or None. A stray 0.0 would silently disable the budget guard for that model."""
    for model_id, spec in catalog.CATALOG.items():
        if spec.provider == "ollama":
            assert spec.input_per_mtok == 0.0, f"{model_id}: local models are free"
            continue
        if spec.priced:
            assert spec.input_per_mtok > 0, f"{model_id}: zero price on a hosted model"
            assert spec.output_per_mtok > 0, f"{model_id}: zero price on a hosted model"


def test_newer_anthropic_tiers_reject_sampling_and_older_ones_accept_it():
    """Pins the split rather than one model, so a wrong entry shows up as a failure."""
    rejects = {
        "claude-opus-5",
        "claude-opus-4-8",
        "claude-opus-4-7",
        "claude-sonnet-5",
        "claude-fable-5",
    }
    accepts = {"claude-opus-4-6", "claude-sonnet-4-6", "claude-haiku-4-5"}

    for model_id in rejects:
        assert llm_factory.sampling_supported(model_id) is False, model_id
    for model_id in accepts:
        assert llm_factory.sampling_supported(model_id) is True, model_id


def test_unknown_model_defaults_to_allowing_sampling():
    assert llm_factory.sampling_supported("some-model-we-have-never-seen") is True


def test_unpriced_routed_model_refuses_to_boot():
    cfg = RunConfig(
        llm_mode="real",
        models={r: "openai:gpt-not-in-catalog" for r in ROLES},
        provider_keys={"openai": "sk-test"},
    )
    with pytest.raises(ValueError) as excinfo:
        llm_factory.validate_pricing(cfg)

    message = str(excinfo.value)
    assert "gpt-not-in-catalog" in message
    assert "never estimated" in message, "the error should say prices aren't guessed"


def test_fake_mode_skips_pricing_validation():
    cfg = RunConfig(llm_mode="fake", models={r: "openai:whatever" for r in ROLES})
    llm_factory.validate_pricing(cfg)  # must not raise


def test_openrouter_and_custom_providers_bypass_pricing_validation():
    """Docs/12 M9: These providers carry $0 catalog price, so usage tracks counts without throwing validation errors."""
    cfg = RunConfig(
        llm_mode="real",
        models={r: "custom:anything-here" for r in ROLES},
        provider_keys={"custom": "sk-test"},
    )
    llm_factory.validate_pricing(cfg)  # must not raise

    cfg = RunConfig(
        llm_mode="real",
        models={r: "openrouter:some/model" for r in ROLES},
        provider_keys={"openrouter": "sk-test"},
    )
    llm_factory.validate_pricing(cfg)  # must not raise


def test_register_adds_a_model_at_runtime():
    """The escape hatch for a model the catalog doesn't ship."""
    spec = catalog.ModelSpec(
        provider="openrouter",
        model_id="test/registered-model",
        display_name="Registered",
        input_per_mtok=1.0,
        output_per_mtok=2.0,
    )
    catalog.register(spec)
    try:
        assert catalog.get("test/registered-model") is spec
        cfg = RunConfig(
            llm_mode="real",
            models={r: "openrouter:test/registered-model" for r in ROLES},
            provider_keys={"openrouter": "sk-test"},
        )
        llm_factory.validate_pricing(cfg)  # now priced, so it boots
    finally:
        catalog.CATALOG.pop("test/registered-model", None)


# ── Providers ──────────────────────────────────────────────────────────────────────


def test_ollama_needs_no_api_key():
    """Local inference has no key to require — demanding one would block offline tier 2."""
    cfg = RunConfig(
        llm_mode="real",
        models={r: "ollama:llama3.3" for r in ROLES},
        provider_keys={},  # deliberately empty
    )
    token = set_run_config(cfg)
    try:
        model = llm_factory.get_llm("planner")
    finally:
        reset_run_config(token)

    assert model.model_name == "llama3.3"
    assert "11434" in str(model.openai_api_base), "should point at the local Ollama server"


def test_ollama_base_url_is_overridable():
    cfg = RunConfig(
        llm_mode="real",
        models={r: "ollama:llama3.3" for r in ROLES},
        ollama_base_url="http://gpu-box.local:11434/v1",
    )
    token = set_run_config(cfg)
    try:
        model = llm_factory.get_llm("planner")
    finally:
        reset_run_config(token)

    assert "gpu-box.local" in str(model.openai_api_base)


def test_openrouter_routes_through_its_own_endpoint():
    cfg = RunConfig(
        llm_mode="real",
        models={r: "openrouter:anthropic/claude-opus-5" for r in ROLES},
        provider_keys={"openrouter": "sk-or-test"},
    )
    token = set_run_config(cfg)
    try:
        model = llm_factory.get_llm("planner")
    finally:
        reset_run_config(token)

    assert "openrouter.ai" in str(model.openai_api_base)
    assert model.model_name == "anthropic/claude-opus-5"


def test_hosted_provider_without_a_key_gives_an_actionable_error():
    cfg = RunConfig(
        llm_mode="real",
        models={r: "anthropic:claude-opus-5" for r in ROLES},
        provider_keys={},
    )
    token = set_run_config(cfg)
    try:
        with pytest.raises(ValueError) as excinfo:
            llm_factory.get_llm("planner")
    finally:
        reset_run_config(token)

    message = str(excinfo.value)
    assert "anthropic" in message
    assert "Settings" in message, "should tell a BYOK user where to add their key"


def test_unknown_provider_lists_the_known_ones():
    cfg = RunConfig(
        llm_mode="real",
        models={r: "notaprovider:some-model" for r in ROLES},
        provider_keys={"notaprovider": "x"},
    )
    token = set_run_config(cfg)
    try:
        with pytest.raises(ValueError) as excinfo:
            llm_factory.get_llm("planner")
    finally:
        reset_run_config(token)

    assert "ollama" in str(excinfo.value)


# ── Presets ────────────────────────────────────────────────────────────────────────


def test_every_preset_covers_every_role_with_a_real_catalog_model():
    for provider, presets in catalog.PRESETS.items():
        assert set(presets) == set(catalog.PRESET_NAMES), f"{provider}: preset names differ"
        for name, mapping in presets.items():
            assert set(mapping) == set(ROLES), f"{provider}/{name}: roles missing"
            for role, route in mapping.items():
                route_provider, _, model_id = route.partition(":")
                assert route_provider == provider, f"{provider}/{name}/{role}: wrong provider"
                assert catalog.get(model_id) is not None, (
                    f"{provider}/{name}/{role}: {model_id} is not in the catalog"
                )


def test_presets_are_ordered_by_cost():
    """fast ≤ balanced ≤ best on total per-1M output price — otherwise the labels lie."""
    for provider, presets in catalog.PRESETS.items():
        if provider == "ollama":
            continue  # local models are all free; ordering is meaningless
        totals = {}
        for name, mapping in presets.items():
            totals[name] = sum(
                catalog.get(route.partition(":")[2]).output_per_mtok for route in mapping.values()
            )
        assert totals["fast"] <= totals["balanced"] <= totals["best"], (
            f"{provider}: preset cost ordering is wrong: {totals}"
        )


def test_preset_lookup_returns_none_for_unknown_pairs():
    assert catalog.preset("anthropic", "balanced") is not None
    assert catalog.preset("anthropic", "nonexistent") is None
    assert catalog.preset("nonexistent", "balanced") is None


def test_a_preset_can_be_installed_as_a_run_config():
    """The end-to-end shape the UI will use: pick a preset → RunConfig → get_llm."""
    mapping = catalog.preset("anthropic", "best")
    cfg = RunConfig(llm_mode="real", models=dict(mapping), provider_keys={"anthropic": "sk-test"})
    llm_factory.validate_pricing(cfg)

    token = set_run_config(cfg)
    try:
        assert llm_factory.get_llm("synthesizer").model == "claude-opus-5"
        assert llm_factory.get_llm("executor").model == "claude-sonnet-5"
    finally:
        reset_run_config(token)
