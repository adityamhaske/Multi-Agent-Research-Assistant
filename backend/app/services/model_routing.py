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

# The rule itself lives in the engine so the desktop host can apply the identical one —
# `sidecar.validate_routing` had its own copy, which never learned to accept
# endpoint-defined providers and so rejected every OmniRoute and tagged-Ollama route on
# the packaged app. Re-exported here because this is where the server's call sites have
# always referred to it.
from research_engine.routing_rules import (  # noqa: F401  (re-export)
    ENDPOINT_DEFINED_PROVIDERS,
    InvalidRouting,
    validate,
)


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
        ("openrouter", settings.openrouter_api_key),
    ):
        if server_key:
            usable.add(provider)

    # A custom OpenAI-compatible endpoint is configured by its URL rather than by a key —
    # a local proxy commonly needs no key at all — so its presence is what makes it usable.
    #
    # Neither this provider nor `openrouter` has catalog entries, because their model lists
    # belong to the endpoint and change without us. That is exactly why they have to be
    # named here: a deployment whose whole routing is `custom:` (the shipped `.env` does
    # this) otherwise reports no custom provider available and the picker cannot offer the
    # models the run will actually use.
    if settings.custom_base_url:
        usable.add("custom")

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
