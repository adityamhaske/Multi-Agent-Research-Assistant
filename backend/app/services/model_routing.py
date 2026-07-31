"""
Per-user and per-session model routing (docs/12 M8).

Three layers, most specific wins:

1. the session's snapshot — what this run was started with,
2. the user's saved preference,
3. the deployment's `MODEL_*` environment routing.

Kept in a service rather than the endpoint because the worker resolves the same thing
when it builds a run's `RunConfig`, and the two must not drift.
"""

from __future__ import annotations

from app.config import settings
from app.models.user import User
from research_engine import catalog
from research_engine.runconfig import ROLES


class InvalidRouting(ValueError):
    """A routing map that must not be persisted."""


def validate(routing: dict) -> dict[str, str]:
    """Normalize and check a user-supplied routing map.

    Rejects rather than silently repairs: a routing that survives this function is
    guaranteed startable, so a run can't fail halfway through on a model that was never
    routable. In particular an unpriced model is refused here, because accepting it would
    disable the per-session budget guard for that role.
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
        provider, _, model_id = route.partition(":")
        if provider not in catalog.KNOWN_PROVIDERS:
            raise InvalidRouting(
                f"{role}: unknown provider '{provider}'. "
                f"Known: {', '.join(catalog.KNOWN_PROVIDERS)}."
            )
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


def available_providers(user: User) -> list[str]:
    """Providers this user can actually reach right now.

    A provider is usable when the user has their own key for it, when the deployment has
    a server key, or when it needs no key at all (local models). The UI uses this to mark
    a model as selectable rather than hiding it — a user who adds a key should see the
    same list they saw before, now enabled.
    """
    usable: set[str] = {"ollama"}  # local inference needs no key

    if user.api_key_provider:
        usable.add(user.api_key_provider)

    for provider, server_key in (
        ("google", settings.google_api_key),
        ("anthropic", settings.anthropic_api_key),
        ("openai", settings.openai_api_key),
    ):
        if server_key:
            usable.add(provider)

    return sorted(usable)


def deployment_default() -> dict[str, str]:
    """The routing a run uses when neither the session nor the user specifies one."""
    return {
        "planner": settings.model_planner,
        "executor": settings.model_executor,
        "critic": settings.model_critic,
        "synthesizer": settings.model_synthesizer,
        "chat": settings.model_chat,
    }


def resolve(*, session_routing: dict | None, user_routing: dict | None) -> dict[str, str]:
    """Session snapshot → user preference → deployment default."""
    return session_routing or user_routing or deployment_default()
