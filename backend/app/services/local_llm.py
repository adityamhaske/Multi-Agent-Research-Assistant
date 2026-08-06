"""
Local LLM (Ollama) discovery and health probe (docs/12 M15).

`model_routing.available_providers()` reports Ollama as usable unconditionally, because
local inference needs no API key. That is true about *keys* and misleading about
*reality*: with no server running, the user picks a local model in the UI and the failure
only surfaces minutes later, inside a run. This module supplies the missing fact — is a
server actually there, and which models does it have — so the UI can tell the truth
before a run is started.

Kept deliberately dependency-free (plain httpx against Ollama's REST API) so a probe
never drags in a model client or costs a token.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import httpx
import structlog

from app.config import settings
from research_engine import catalog

logger = structlog.get_logger()

# A probe must never make the settings page feel slow: a local server answers in
# milliseconds, and anything slower is functionally "not there" for our purposes.
_PROBE_TIMEOUT_SECONDS = 3.0

# Smallest parameter count (in billions) we expect to survive the executor's structured
# evidence step. Measured 2026-08-06: qwen2.5:7b plans and calls the search tool
# correctly, then fails to return parsable evidence (`no_parsable_evidence`), because
# small models are weak at strict JSON schemas and tool-calling. Surfacing this in the UI
# is the difference between a feature and a support burden (docs/12 M15).
_MIN_RESEARCH_PARAMS_B = 14.0

# Parameter count in a tag: "qwen2.5:7b" → 7, "deepseek-r1:14b" → 14, "llama3.3:70b" → 70.
# The leading boundary matters — a naive "4b" substring search matches *inside* "14b" and
# mislabels a capable model as underpowered (caught in live testing, hence the regex).
_PARAM_RE = re.compile(r"(?:^|[^0-9.])(\d+(?:\.\d+)?)\s*b(?![a-z0-9])", re.IGNORECASE)

# Qualitative size markers used when a tag carries no explicit parameter count.
_SMALL_WORDS = ("mini", "small", "tiny")

# Embedding models cannot chat or call tools at all — routing one to an agent role fails
# immediately, so they are labelled rather than silently offered as a choice.
_EMBEDDING_HINTS = ("embed", "bge-", "gte-", "minilm")


@dataclass
class LocalModel:
    """One model installed on the local server."""

    name: str  # the Ollama tag, e.g. "qwen2.5:7b"
    size_bytes: int | None = None
    # The "provider:model" route to use for this model, when it maps to a catalog entry.
    route: str | None = None
    in_catalog: bool = False
    # True when the name suggests a parameter count the pipeline handles poorly.
    likely_underpowered: bool = False
    # True for embedding models — usable for retrieval, never for an agent role.
    is_embedding: bool = False
    # Parsed parameter count in billions, when the tag states one.
    params_b: float | None = None


@dataclass
class LocalLLMStatus:
    """Everything the settings UI needs to describe the local-LLM connection."""

    configured_base_url: str
    reachable: bool
    models: list[LocalModel] = field(default_factory=list)
    error: str | None = None
    # Actionable next step, phrased for a user rather than an operator.
    hint: str | None = None

    @property
    def usable(self) -> bool:
        return self.reachable and bool(self.models)


def _api_root(base_url: str) -> str:
    """Ollama's REST root from the OpenAI-compatible base URL.

    Config holds `.../v1` because that is what the chat client needs; discovery lives at
    `/api/tags` on the same host, so strip the OpenAI suffix rather than making the user
    configure two URLs that must agree.
    """
    return base_url.rstrip("/").removesuffix("/v1")


def _parse_params_b(name: str) -> float | None:
    """Parameter count in billions from an Ollama tag, or None when unstated."""
    match = _PARAM_RE.search(name)
    return float(match.group(1)) if match else None


def _is_embedding(name: str) -> bool:
    lowered = name.lower()
    return any(hint in lowered for hint in _EMBEDDING_HINTS)


def _is_underpowered(name: str) -> bool:
    """Whether this model is likely too weak for the research pipeline.

    Judged on the stated parameter count, falling back to qualitative words. A tag with
    no size at all is NOT flagged: guessing wrong in that direction would warn users off
    perfectly capable models, and the run itself will tell them soon enough.
    """
    lowered = name.lower()
    params = _parse_params_b(lowered)
    if params is not None:
        return params < _MIN_RESEARCH_PARAMS_B
    return any(word in lowered for word in _SMALL_WORDS)


def _match_catalog_route(name: str) -> tuple[str | None, bool]:
    """Map an installed Ollama tag to a catalog route.

    Ollama tags carry a version suffix ("qwen2.5:7b", "llama3.3:latest") while the catalog
    keys the family ("qwen2.5"). Match on the family so a user who pulled any tag of a
    known model still gets a routable entry, and fall back to the raw tag — which the
    factory accepts, since `provider:model` splits on the first colon only.
    """
    family = name.split(":", 1)[0]
    spec = catalog.get(family)
    if spec is not None and spec.provider == "ollama":
        return spec.route, True
    return f"ollama:{name}", False


async def probe(base_url: str | None = None) -> LocalLLMStatus:
    """Ask the configured Ollama server what it has. Never raises."""
    configured = base_url or settings.ollama_base_url
    url = f"{_api_root(configured)}/api/tags"

    try:
        async with httpx.AsyncClient(timeout=_PROBE_TIMEOUT_SECONDS) as client:
            response = await client.get(url)
            response.raise_for_status()
            payload = response.json()
    except Exception as exc:  # noqa: BLE001 — every failure is "not reachable" to a user
        logger.info("local_llm_probe_failed", url=url, error=str(exc))
        return LocalLLMStatus(
            configured_base_url=configured,
            reachable=False,
            error=str(exc),
            hint=(
                "No local model server answered at this address. Start Ollama with "
                "`ollama serve`, then reload. If the app runs in Docker, the address "
                "must be http://host.docker.internal:11434/v1 — inside a container, "
                "localhost is the container itself."
            ),
        )

    models: list[LocalModel] = []
    for entry in payload.get("models", []) or []:
        name = entry.get("name") or entry.get("model") or ""
        if not name:
            continue
        route, in_catalog = _match_catalog_route(name)
        embedding = _is_embedding(name)
        models.append(
            LocalModel(
                name=name,
                size_bytes=entry.get("size"),
                route=route,
                in_catalog=in_catalog,
                # An embedding model is not "underpowered" for chat — it cannot chat.
                likely_underpowered=(not embedding and _is_underpowered(name)),
                is_embedding=embedding,
                params_b=_parse_params_b(name),
            )
        )
    models.sort(key=lambda m: m.name)

    chat_models = [m for m in models if not m.is_embedding]

    hint = None
    if not models:
        hint = (
            "The server is running but has no models. Pull one first, for example "
            "`ollama pull qwen2.5:14b`."
        )
    elif not chat_models:
        hint = (
            "Only embedding models are installed. Those power retrieval, not the agents — "
            "pull a chat model too, for example `ollama pull qwen2.5:14b`."
        )
    elif all(m.likely_underpowered for m in chat_models):
        hint = (
            f"Every installed chat model looks small (under {_MIN_RESEARCH_PARAMS_B:.0f}B). "
            "Those are fine for chat but usually fail the research pipeline's "
            "structured-evidence step — pull a larger model for research runs."
        )

    return LocalLLMStatus(configured_base_url=configured, reachable=True, models=models, hint=hint)
