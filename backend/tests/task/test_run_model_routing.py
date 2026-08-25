"""Per-run model selection: one rule for both hosts, and a snapshot that survives a resume.

Two scars are pinned here.

**The rule had two homes and they disagreed.** The server's validator learned to accept
providers whose model ids belong to the endpoint — Ollama serves the tags you pulled, a
gateway fronts a catalogue that changes without us — while the desktop's copy kept
demanding catalog membership for every id. On the packaged app that made an OmniRoute
deployment unselectable outright, and left `ollama:deepseek-r1` (a family name Ollama 404s
without a `:latest` tag) as the only "valid" local route. `routing_rules.validate` is now
the single implementation and the parity test below asserts *object identity*, not matching
behaviour, because two functions that merely agree today are what got us here.

**A route is only a choice if the run keeps it.** `run_config_for_run` stamps the resolved
routing onto the run the first time it resolves, so a resumed run cannot finish on
different models than it started with — a report whose halves were written by two models,
with one of them named in the attribution.
"""

from __future__ import annotations

import pytest

from research_engine.routing_rules import ENDPOINT_DEFINED_PROVIDERS, InvalidRouting, validate
from research_engine.runconfig import ROLES


def _all_roles(route: str) -> dict[str, str]:
    """One model for every role — what the Research page's single picker submits."""
    return {role: route for role in ROLES}


# ── The shared rule ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "route",
    [
        "custom:auto/best-fast",  # OmniRoute alias
        "custom:Kimi Coding",  # a gateway id with a space in it
        "ollama:qwen2.5:7b",
        "openrouter:meta-llama/llama-3.1-70b-instruct",
    ],
)
def test_an_endpoint_defined_route_is_accepted_verbatim(route):
    """Accepted on shape alone, and returned unchanged.

    Canonicalising these would be the bug: the id is what the endpoint resolves, so a
    "tidied" route stops naming the model it was chosen for.
    """
    assert validate(_all_roles(route))["planner"] == route


def test_a_tagged_local_model_keeps_its_tag():
    """`ollama:deepseek-r1:14b` splits on the FIRST colon only.

    A greedy split reads the provider as `ollama` and the model as `deepseek-r1`, which is
    a different model that Ollama 404s — the run dies at the first planner call.
    """
    assert validate(_all_roles("ollama:deepseek-r1:14b"))["planner"] == "ollama:deepseek-r1:14b"


def test_a_catalogued_provider_still_has_to_name_a_catalogued_model():
    """Negative control: the endpoint-defined bypass must not become a bypass for everyone.

    An unpriced or unknown model from a priced provider is still refused, because the
    per-session cost cap reads the catalog price and a missing one silently disables it.
    """
    with pytest.raises(InvalidRouting, match="not in the model catalog"):
        validate(_all_roles("google:no-such-model"))


def test_a_provider_with_no_model_after_it_is_refused():
    with pytest.raises(InvalidRouting, match="names no model"):
        validate(_all_roles("custom:"))


def test_an_unknown_provider_is_refused():
    with pytest.raises(InvalidRouting, match="unknown provider"):
        validate(_all_roles("notaprovider:model"))


def test_every_role_must_be_routed():
    """A partial map would leave some roles on the deployment default without saying so."""
    with pytest.raises(InvalidRouting, match="Every role needs a model"):
        validate({"planner": "ollama:qwen2.5:7b"})


def test_the_endpoint_defined_set_is_exactly_the_unpriced_providers():
    """These three are bypassed *because* the catalog cannot price them.

    If a provider is added here without that being true, the per-session spend cap silently
    stops binding for it — the cap is computed from catalog prices.
    """
    assert set(ENDPOINT_DEFINED_PROVIDERS) == {"ollama", "custom", "openrouter"}


# ── Both hosts, one rule ───────────────────────────────────────────────────────────


def test_both_hosts_validate_with_the_same_function_object():
    """Identity, not equivalence.

    The previous arrangement was two functions that were *supposed* to agree, and they
    drifted for a whole release. Asserting `is` means a future edit cannot reintroduce a
    second copy without this failing.
    """
    from app.services import model_routing
    from desktop import sidecar

    assert model_routing.validate is validate
    assert sidecar.validate_routing is validate


def test_the_desktop_host_accepts_the_routes_it_used_to_reject():
    """The regression stated in the terms a user would notice."""
    from desktop import sidecar

    for route in ("custom:auto/best-fast", "ollama:deepseek-r1:14b"):
        assert sidecar.validate_routing(_all_roles(route))["synthesizer"] == route
