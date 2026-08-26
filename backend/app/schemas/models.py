"""
Response and request bodies for the model-routing surface.

**Why these live in `app/schemas/` rather than beside the routes.** Both hosts serve
`/models`, `/models/routing`, `/models/local/status`, `/models/custom/status` and
`/models/providers/test`, and a shared route returning a different shape on one host is a
UI that renders correctly in the web build and wrongly in the desktop build with nothing
failing in between (AGENTS.md, "two hosts, one contract").

The desktop could not declare these models while they sat in `app/api/v1/models.py`: that
module imports `app.config`, and `Settings` requires `database_url` and `jwt_secret_key`,
neither of which an installed app has. The packaged sidecar dies at import if it reaches
them (#50). So the shapes moved here — pure pydantic, no configuration — and the route
module re-exports them. Same relocation, and same reason, as `app/schemas/runs.py` and
`app/services/document_headers.py`.

Nothing in this module may import `app.config`, `app.db`, or anything reaching them;
`tests/workflow/test_sidecar_startup.py` fails if that changes.
"""

from __future__ import annotations

from typing import Literal

from pydantic import AnyHttpUrl, BaseModel, Field


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
