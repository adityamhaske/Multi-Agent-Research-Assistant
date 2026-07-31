"""
Model catalog and per-user routing endpoints (docs/12 M8).

`GET /models` is what the picker renders: every routable model with its price, context
window, and capabilities, plus the presets, plus which providers this user can actually
reach. Models the user has no key for are returned *marked unavailable* rather than
omitted — hiding them would make adding a key feel like the app changed, and the price
comparison is most of the point.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.models.user import User
from app.services import model_routing
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


class RoutingRequest(BaseModel):
    routing: dict[str, str]


class RoutingResponse(BaseModel):
    routing: dict[str, str] | None
    effective_routing: dict[str, str]


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

    return CatalogResponse(
        roles=list(ROLES),
        models=models,
        presets=catalog.PRESETS,
        preset_names=list(catalog.PRESET_NAMES),
        available_providers=usable,
        effective_routing=model_routing.resolve(session_routing=None, user_routing=user_routing),
        user_routing=user_routing,
        deployment_routing=deployment,
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
