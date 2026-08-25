"""
What makes a role→model routing map startable. One implementation, both hosts.

This rule had two homes and they disagreed. `app/services/model_routing.validate()` learned
to accept endpoint-defined providers — Ollama serves whatever tags you pulled, and a custom
gateway or OpenRouter fronts a catalogue that changes without us — while the desktop's
`sidecar.validate_routing()` kept demanding catalog membership for every id. The visible
result on the packaged app: an OmniRoute deployment was unselectable entirely, and the only
local routes that validated were *family* names like `ollama:deepseek-r1`, which Ollama
404s unless a `:latest` tag happens to exist.

The two copies existed for one reason — `app/services/model_routing` imports `app.config`
for `available_providers()` and `deployment_default()`, and the desktop host cannot build
`Settings`. That is a constraint on *those* functions, not on this rule, which needs only
the catalog and the role list. So it lives here, in the engine, where both hosts already
import freely and neither needs configuration.

`app.services.model_routing` re-exports `validate` and `InvalidRouting`, so existing call
sites are unchanged; `sidecar.validate_routing` delegates. Change the rule here and both
hosts move together — which is the point (AGENTS.md, "prefer extracting the shared logic
into one function over keeping two copies in step by discipline").
"""

from __future__ import annotations

from research_engine import catalog
from research_engine.runconfig import ROLES


class InvalidRouting(ValueError):
    """A routing map that must not be persisted.

    Subclasses `ValueError` because the desktop host's callers catch that, and because a
    bad routing genuinely is a bad value rather than a distinct failure mode.
    """


#: Providers whose model ids are defined by the endpoint rather than by our catalog.
#:
#: Validating these against `catalog` would reject every legitimate local tag and every
#: gateway model, so they are checked for shape only. The cost is real and accepted: spend
#: on them is not catalog-priced, so `estimate_cost()` returns 0.0 and the per-session cap
#: does not bind — the same gap `llm_factory.validate_pricing()` already allows for them.
#: Cap spend at the provider, and never render an unpriced run's cost as a measured `$0.00`.
ENDPOINT_DEFINED_PROVIDERS = ("ollama", "custom", "openrouter")


def validate(routing: dict) -> dict[str, str]:
    """Normalize and check a user-supplied routing map.

    Rejects rather than silently repairs: a routing that survives this function is
    guaranteed startable, so a run cannot fail halfway through on a model that was never
    routable. In particular an unpriced *catalogued* model is refused here, because
    accepting it would disable the per-session budget guard for that role.
    """
    if not isinstance(routing, dict):
        raise InvalidRouting("Model routing must be an object keyed by agent role.")

    unknown_roles = sorted(set(routing) - set(ROLES))
    if unknown_roles:
        raise InvalidRouting(f"Unknown agent role(s): {unknown_roles}. Valid roles: {list(ROLES)}.")
    missing_roles = sorted(set(ROLES) - set(routing))
    if missing_roles:
        raise InvalidRouting(f"Every role needs a model. Missing: {missing_roles}.")

    cleaned: dict[str, str] = {}
    for role, route in routing.items():
        if not isinstance(route, str) or ":" not in route:
            raise InvalidRouting(f"{role}: expected a 'provider:model' string, got {route!r}.")
        # Split on the FIRST colon only: `ollama:qwen2.5:7b` is provider `ollama`, model
        # `qwen2.5:7b`. A greedy split silently reroutes every tagged local model.
        provider, _, model_id = route.partition(":")
        if provider not in catalog.KNOWN_PROVIDERS:
            raise InvalidRouting(
                f"{role}: unknown provider '{provider}'. "
                f"Known: {', '.join(catalog.KNOWN_PROVIDERS)}."
            )
        if provider in ENDPOINT_DEFINED_PROVIDERS:
            if not model_id:
                raise InvalidRouting(f"{role}: '{provider}:' names no model.")
            # Kept verbatim rather than canonicalised, because the exact tag is the thing
            # that resolves at call time. An "obvious" cleanup is how a route stops naming
            # the model it was chosen for.
            cleaned[role] = route
            continue
        spec = catalog.get(model_id)
        if spec is None:
            raise InvalidRouting(f"{role}: '{model_id}' is not in the model catalog.")
        if not spec.priced:
            raise InvalidRouting(
                f"{role}: '{model_id}' has no configured price, so spending on it could "
                "not be capped. Add its price to the catalog before routing to it."
            )
        cleaned[role] = spec.route  # canonical form, so stored values stay comparable
    return cleaned
