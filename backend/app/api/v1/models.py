"""
Model catalog and per-user routing endpoints (docs/12 M8).

`GET /models` is what the picker renders: every routable model with its price, context
window, and capabilities, plus the presets, plus which providers this user can actually
reach. Models the user has no key for are returned *marked unavailable* rather than
omitted — hiding them would make adding a key feel like the app changed, and the price
comparison is most of the point.
"""

from __future__ import annotations

import json
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from pydantic import AnyHttpUrl, BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.dependencies import get_current_user, get_db
from app.models.user import User
from app.schemas.auth import ConnectionVerdict
from app.services import crypto, custom_endpoint, local_llm, model_routing, provider_health
from research_engine import catalog
from research_engine.runconfig import ROLES

router = APIRouter(prefix="/models", tags=["Models"])


class ModelInfo(BaseModel):
    route: str
    provider: str
    model_id: str
    display_name: str
    input_per_mtok: float | None
    output_per_mtok: float | None
    context_window: int | None
    max_output_tokens: int | None
    supports_tools: bool
    supports_structured_output: bool
    notes: str
    available: bool = Field(description="Whether this user currently has a usable key.")


class CatalogResponse(BaseModel):
    roles: list[str]
    models: list[ModelInfo]
    presets: dict[str, dict[str, dict[str, str]]]
    preset_names: list[str]
    available_providers: list[str]
    # What this user's runs use today: their saved preference, else the deployment's.
    effective_routing: dict[str, str]
    # None when the user has no preference of their own and is on the deployment default.
    user_routing: dict[str, str] | None
    deployment_routing: dict[str, str]


class LocalModelInfo(BaseModel):
    name: str
    size_bytes: int | None
    route: str | None
    in_catalog: bool
    likely_underpowered: bool
    is_embedding: bool
    params_b: float | None


class LocalLLMStatusResponse(BaseModel):
    configured_base_url: str
    reachable: bool
    usable: bool
    models: list[LocalModelInfo]
    error: str | None
    hint: str | None
    # "Not detected" used to conflate two states with different fixes (docs/07 §2,
    # Phase 2b): install vs. start.
    install_state: Literal["running", "installed_not_running", "not_installed"]


class CustomEndpointStatusResponse(BaseModel):
    """What the configured OpenAI-compatible endpoint says it can serve.

    `models` is a bare list of ids rather than `ModelInfo`, and deliberately so: this
    provider has no catalog entry, so there is no price, context window or capability flag
    to report. Dressing the ids up in the same shape as catalogued models would invent
    fields whose only honest value is null — and a `0.0` price here would silently read as
    "free" for a gateway that bills.
    """

    configured_base_url: str
    reachable: bool
    models: list[str]
    error: str | None
    hint: str | None


class ReadinessResponse(BaseModel):
    """Whether this user can run research at all right now (docs/17 §8a)."""

    ready: bool
    # Which half is satisfied, so the UI can say something specific rather than
    # "not configured" — the two have completely different next steps.
    has_cloud_key: bool
    local_reachable: bool
    local_chat_models: int


class ProviderTestRequest(BaseModel):
    """A key to probe before it is stored (docs/07 §2, Phase 2a)."""

    model_config = {"str_strip_whitespace": True}

    provider: Literal["google", "anthropic", "openai", "openrouter", "custom"]
    api_key: str = Field(min_length=8, max_length=500)
    api_base_url: AnyHttpUrl | None = Field(default=None)


class RoutingRequest(BaseModel):
    routing: dict[str, str]


class RoutingResponse(BaseModel):
    routing: dict[str, str] | None
    effective_routing: dict[str, str]


async def _ollama_presets_from_installed() -> dict[str, dict[str, str]] | None:
    """Ollama presets built from the models this machine actually has, or None.

    The static presets in `catalog.PRESETS` name specific tags (`llama3.3`), so choosing
    "Local" on a machine without that exact tag pulled produced a routing that 404s on the
    first planner call — every time, for every role. The failure surfaced as a provider
    error mid-run, long after the click that caused it, which is the worst possible place
    to learn the model does not exist.

    Selection mirrors what the settings card already tells the user: skip embedding models
    (they cannot chat), prefer one big enough for the structured-evidence step for
    `balanced`/`best`, and let `fast` be the smallest chat model available. Returns None
    when nothing usable is installed, so the caller keeps the static defaults rather than
    serving an empty preset.
    """
    try:
        status_ = await local_llm.probe()
    except Exception:  # noqa: BLE001 — a catalog request must not fail on a dead probe
        return None
    chat_models = [
        m for m in status_.models if not m.is_embedding and getattr(m, "supports_tools", True)
    ]
    if not chat_models:
        return None

    def size(m) -> float:
        return m.params_b if m.params_b is not None else (m.size_bytes or 0) / 1e9

    smallest = min(chat_models, key=size)
    research_ready = [m for m in chat_models if not m.likely_underpowered]
    strongest = max(research_ready or chat_models, key=size)

    # The exact installed tag, not the catalog's family route. `LocalModel.route` maps a
    # tag onto its catalog family (`deepseek-r1:14b` → `ollama:deepseek-r1`), and Ollama
    # resolves a bare family only when a `:latest` tag happens to exist for it — which for
    # `deepseek-r1` it does not. Routing at the family reproduced the exact 404 this
    # function exists to prevent, so route at what is actually pulled.
    def route_of(m) -> str:
        return f"ollama:{m.name}"

    return {
        "fast": dict.fromkeys(ROLES, route_of(smallest)),
        "balanced": dict.fromkeys(ROLES, route_of(strongest)),
        "best": dict.fromkeys(ROLES, route_of(strongest)),
    }


@router.get("/readiness", response_model=ReadinessResponse)
async def get_readiness(current_user: User = Depends(get_current_user)):
    """Can this user run research right now? (docs/17 §8a)

    Deliberately computed on every request rather than stored as a
    "has-completed-onboarding" flag. A stored flag desynchronises from reality — it stays
    true after a key is revoked and false after Ollama starts — whereas this answer is
    always the current truth and stops being shown the moment a model exists.

    `available_providers()` cannot answer this: it lists ollama unconditionally, because
    local inference needs no key, so it is never empty and would report every user as
    ready. Reachability is the thing that matters here, not permission.
    """
    has_cloud_key = bool(
        current_user.api_key_provider
        or settings.google_api_key
        or settings.anthropic_api_key
        or settings.openai_api_key
        or settings.openrouter_api_key
        or settings.custom_api_key
    )

    local_reachable = False
    chat_models = 0
    try:
        status_ = await local_llm.probe()
        local_reachable = status_.reachable
        chat_models = sum(1 for m in status_.models if not m.is_embedding)
    except Exception:  # noqa: BLE001 — a dead probe means "no local models", not an error
        pass

    return ReadinessResponse(
        # An embedding-only Ollama cannot fill an agent role, so a reachable server with
        # no chat model is not readiness — that distinction is the whole reason this
        # counts chat models rather than trusting `reachable`.
        ready=has_cloud_key or chat_models > 0,
        has_cloud_key=has_cloud_key,
        local_reachable=local_reachable,
        local_chat_models=chat_models,
    )


@router.get("", response_model=CatalogResponse)
async def get_catalog(current_user: User = Depends(get_current_user)):
    usable = model_routing.available_providers(current_user)
    deployment = model_routing.deployment_default()
    user_routing = current_user.model_routing or None

    models = [
        ModelInfo(
            route=spec.route,
            provider=spec.provider,
            model_id=spec.model_id,
            display_name=spec.display_name,
            input_per_mtok=spec.input_per_mtok,
            output_per_mtok=spec.output_per_mtok,
            context_window=spec.context_window,
            max_output_tokens=spec.max_output_tokens,
            supports_tools=spec.supports_tools,
            supports_structured_output=spec.supports_structured_output,
            notes=spec.notes,
            available=spec.provider in usable,
        )
        # Cheapest first: the picker reads as a cost ladder, and the free local models
        # sort to the top where a cost-conscious user will find them.
        for spec in sorted(
            catalog.CATALOG.values(),
            key=lambda s: (s.provider, s.output_per_mtok if s.priced else float("inf")),
        )
    ]

    # Serve the local presets that this machine can actually run, falling back to the
    # static table when nothing is installed (or the probe is down).
    presets = dict(catalog.PRESETS)
    installed = await _ollama_presets_from_installed()
    if installed:
        presets["ollama"] = installed

    return CatalogResponse(
        roles=list(ROLES),
        models=models,
        presets=presets,
        preset_names=list(catalog.PRESET_NAMES),
        available_providers=usable,
        effective_routing=model_routing.resolve(session_routing=None, user_routing=user_routing),
        user_routing=user_routing,
        deployment_routing=deployment,
    )


@router.get("/local/status", response_model=LocalLLMStatusResponse)
async def local_llm_status(_current_user: User = Depends(get_current_user)):
    """Probe the configured local model server (docs/12 M15).

    Separate from `GET /models` because it does live I/O: the catalog must stay instant
    and always renderable, while this can legitimately time out when nothing is running.
    """
    status_ = await local_llm.probe()
    return LocalLLMStatusResponse(
        configured_base_url=status_.configured_base_url,
        reachable=status_.reachable,
        usable=status_.usable,
        models=[
            LocalModelInfo(
                name=m.name,
                size_bytes=m.size_bytes,
                route=m.route,
                in_catalog=m.in_catalog,
                likely_underpowered=m.likely_underpowered,
                is_embedding=m.is_embedding,
                params_b=m.params_b,
            )
            for m in status_.models
        ],
        error=status_.error,
        hint=status_.hint,
        install_state=status_.install_state,
    )


@router.get("/custom/status", response_model=CustomEndpointStatusResponse)
async def custom_endpoint_status(_current_user: User = Depends(get_current_user)):
    """Ask the configured custom endpoint what it serves (see `services/custom_endpoint`).

    Split from `GET /models` for the same reason `/local/status` is: this does live I/O
    against an address that can legitimately be down, and the catalog must stay instant and
    always renderable. Both probes answer the same question for the two providers whose
    model lists this codebase cannot know — the endpoint owns them, not the catalog.
    """
    status_ = await custom_endpoint.probe()
    return CustomEndpointStatusResponse(
        configured_base_url=status_.configured_base_url,
        reachable=status_.reachable,
        models=status_.models,
        error=status_.error,
        hint=status_.hint,
    )


@router.post("/providers/test", response_model=ConnectionVerdict)
async def test_provider(
    payload: ProviderTestRequest, _current_user: User = Depends(get_current_user)
):
    """Probe a submitted key BEFORE it is stored (docs/07 §2, Phase 2a) — the picker's
    "test connection" action, separate from saving.

    Live I/O, same reason `/local/status` is split from `GET /models`: it can
    legitimately be slow or time out, and the catalog must stay instant either way.
    """
    verdict = await provider_health.probe(
        payload.provider,
        payload.api_key,
        str(payload.api_base_url) if payload.api_base_url else None,
    )
    return ConnectionVerdict(
        state=verdict.state,
        reason=verdict.reason,
        checked_at=verdict.checked_at,
        model_count=verdict.model_count,
    )


@router.get("/providers/health", response_model=ConnectionVerdict)
async def provider_health_check(current_user: User = Depends(get_current_user)):
    """Re-probe this user's own stored BYOK key on demand (docs/07 §2, Phase 2a).

    404s when there is no key to check — a settings page with no key stored already
    says so in prose; this endpoint has nothing of the user's own to verify, and a
    "degraded: no key" verdict here would be a second, redundant way to say the same
    thing the empty-state text already covers.
    """
    if not current_user.api_key_provider or not current_user.api_key_encrypted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="No key stored to check.")

    key = crypto.decrypt(current_user.api_key_encrypted)
    verdict = (
        provider_health.failed_verdict("The stored key could not be decrypted — save it again.")
        if not key
        else await provider_health.probe(
            current_user.api_key_provider, key, current_user.api_key_base_url
        )
    )
    return ConnectionVerdict(
        state=verdict.state,
        reason=verdict.reason,
        checked_at=verdict.checked_at,
        model_count=verdict.model_count,
    )


@router.post("/local/pull")
async def pull_local_model(request: Request, _current_user: User = Depends(get_current_user)):
    """Stream download progress for a recommended model (docs/07 §2, Phase 2b).

    Unlike `/local/start` (spawning a server process), pulling a model is just an
    HTTP call to an already-running Ollama — no local process access required, so
    this works on the web build too wherever `/local/status` already does, not only
    on desktop. Newline-delimited JSON, one `PullProgress` per line.
    """
    body = await request.json()
    model = (body.get("model") or "").strip()
    if not model:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="No model given.")

    async def gen():
        async for progress in local_llm.pull(model):
            yield (
                json.dumps(
                    {
                        "status": progress.status,
                        "completed": progress.completed,
                        "total": progress.total,
                        "error": progress.error,
                    }
                )
                + "\n"
            )

    return StreamingResponse(gen(), media_type="application/x-ndjson")


@router.get("/routing", response_model=RoutingResponse)
async def get_routing(current_user: User = Depends(get_current_user)):
    """This user's saved routing, and what a run would actually dial.

    The read half of a trio that shipped write-only: PUT and DELETE existed, GET did not,
    and `frontend/hooks/queries.ts` was already fetching it — so every dashboard load
    logged a 405 and `useModelRouting()` never resolved. Nothing failed loudly; the
    project hub's model panel just stayed empty.

    `routing` is null when the user has expressed no preference. That is deliberately
    distinct from `effective_routing`, which is never null because a run always dials
    *something*: collapsing them would make "I have not chosen" read identically to "I
    chose exactly the deployment defaults", and only one of those should survive an
    operator changing MODEL_*.

    No database write and no live provider call, so it stays as cheap as `GET /models`.
    """
    return RoutingResponse(
        routing=current_user.model_routing,
        effective_routing=model_routing.resolve(
            session_routing=None, user_routing=current_user.model_routing
        ),
    )


@router.put("/routing", response_model=RoutingResponse)
async def set_routing(
    payload: RoutingRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Save this user's per-role routing.

    Validated against the catalog before it is stored, so a saved preference is always
    startable — a run should never fail on a model that could have been rejected here.
    """
    try:
        cleaned = model_routing.validate(payload.routing)
    except model_routing.InvalidRouting as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)) from e

    current_user.model_routing = cleaned
    await db.commit()
    await db.refresh(current_user)

    return RoutingResponse(
        routing=current_user.model_routing,
        effective_routing=model_routing.resolve(
            session_routing=None, user_routing=current_user.model_routing
        ),
    )


@router.delete("/routing", response_model=RoutingResponse)
async def clear_routing(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Drop the preference and fall back to the deployment's MODEL_* routing."""
    current_user.model_routing = None
    await db.commit()
    await db.refresh(current_user)

    return RoutingResponse(
        routing=None,
        effective_routing=model_routing.resolve(session_routing=None, user_routing=None),
    )
