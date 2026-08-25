"""
Discovery for a custom OpenAI-compatible endpoint (OmniRoute, LiteLLM, vLLM, a gateway).

`catalog.py` cannot describe this provider: its model list belongs to the endpoint and
changes without us, which is why `model_routing.validate()` accepts `custom:` routes on
shape alone. The cost of that is a picker with nothing to show — a deployment whose whole
routing is `custom:` (the shipped `.env` does exactly this) had no way to offer the models
its runs actually use, so the only selectable models were ones the deployment does not
route to.

This module supplies the missing fact by asking the endpoint itself, the same way
`local_llm` asks Ollama what it has. Same two rules as that module:

* **Never raises.** Every failure is "not reachable" with a message, because the caller is
  a settings screen that must stay renderable.
* **No `app.config` import.** The base URL and key come from the engine's process
  `RunConfig`, which both hosts populate. Reaching `app.config` here would build a
  `Settings` requiring `DATABASE_URL`/`JWT_SECRET_KEY` and kill the packaged desktop
  sidecar at import, which is issue #50 exactly.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import httpx
import structlog

from research_engine.llm_factory import api_key_for, map_local_host
from research_engine.runconfig import get_run_config

logger = structlog.get_logger()

#: Short, because this runs while someone waits on a settings page. A gateway that cannot
#: list its models in five seconds is reported as unreachable rather than hanging the tab.
_PROBE_TIMEOUT_SECONDS = 5.0


@dataclass
class CustomEndpointStatus:
    """What the configured endpoint is, and what it says it can serve."""

    configured_base_url: str
    reachable: bool
    #: Model ids exactly as the endpoint reports them — never canonicalised. The id is
    #: what resolves at call time, and an "obvious" cleanup (case, a stripped prefix) is
    #: how a route stops matching the thing it names.
    models: list[str] = field(default_factory=list)
    error: str | None = None
    hint: str | None = None


def configured_base_url() -> str:
    """The endpoint this deployment routes `custom:` to, or empty when none is set."""
    return api_key_for("custom_base_url")


async def probe(base_url: str | None = None) -> CustomEndpointStatus:
    """Ask the endpoint for its model list over the OpenAI-compatible `/models` route.

    `configured` is what the UI shows and what a run will use; `dial` is what this probe
    connects to. Inside a container those differ — `localhost` is the container, not the
    host running the gateway — and `map_local_host` is the single implementation of that
    rewrite, shared with `get_llm`, so the probe checks the address the pipeline will
    really call rather than one that only looks the same.
    """
    configured = base_url or configured_base_url()
    if not configured:
        return CustomEndpointStatus(
            configured_base_url="",
            reachable=False,
            hint=(
                "No custom endpoint is configured. Set CUSTOM_BASE_URL to an "
                "OpenAI-compatible base URL to route runs through it."
            ),
        )

    dial = map_local_host(configured)
    if get_run_config().enforce_ssrf_guards:
        # Same guard `get_llm` applies before calling this endpoint. A probe is a
        # server-side fetch of a user-supplied URL, so it is the same class of request and
        # gets the same check — refusing here rather than at run time also means the
        # address is rejected while someone is looking at the screen that sets it.
        from research_engine.net_guard import SSRFBlocked, validate_url

        try:
            validate_url(dial)
        except SSRFBlocked as exc:
            return CustomEndpointStatus(
                configured_base_url=configured,
                reachable=False,
                error=str(exc),
                hint="This address is blocked by the deployment's SSRF guard.",
            )

    url = f"{dial.rstrip('/')}/models"
    key = api_key_for("custom")
    headers = {"Authorization": f"Bearer {key}"} if key else {}

    try:
        async with httpx.AsyncClient(timeout=_PROBE_TIMEOUT_SECONDS) as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            payload = response.json()
    except Exception as exc:  # noqa: BLE001 — every failure reads as "not reachable"
        logger.info("custom_endpoint_probe_failed", configured=configured, error=str(exc))
        return CustomEndpointStatus(
            configured_base_url=configured,
            reachable=False,
            error=str(exc),
            hint=(
                "No OpenAI-compatible endpoint answered at this address. Check that the "
                "gateway is running and that CUSTOM_BASE_URL includes its API prefix."
            ),
        )

    # `{"data": [{"id": ...}]}` is the OpenAI shape. A gateway that answers 200 with
    # something else is reachable but useless to a picker, and saying so beats rendering an
    # empty list that looks like "this endpoint serves no models".
    entries = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(entries, list):
        return CustomEndpointStatus(
            configured_base_url=configured,
            reachable=True,
            error="The endpoint answered without an OpenAI-compatible model list.",
            hint="Enter the model id by hand — this gateway does not advertise one.",
        )

    models = sorted(
        {
            str(e["id"])
            for e in entries
            if isinstance(e, dict)
            and e.get("id")
            and "deepseek-r1" not in str(e.get("id", "")).lower()
            and (
                e.get("capabilities", {}).get("tool_calling", True)
                if isinstance(e.get("capabilities"), dict)
                else True
            )
        },
    )
    return CustomEndpointStatus(
        configured_base_url=configured,
        reachable=True,
        models=models,
        hint=(None if models else "The endpoint listed no models. Enter the model id by hand."),
    )
