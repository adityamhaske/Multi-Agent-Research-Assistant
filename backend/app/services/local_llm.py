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

import json
import re
import shutil
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import httpx
import structlog

# The default Ollama URL is read from the engine's process RunConfig, not from
# `app.config.settings`. Both are the same value on the server — `app/runtime.py` copies
# `settings.ollama_base_url` straight into the process default — but `app.config` builds a
# `Settings` requiring `DATABASE_URL` and `JWT_SECRET_KEY` at import, which the desktop
# host does not have. Importing it here killed the packaged sidecar at startup (#50), and
# a lazy import would only have moved the crash to the first Settings-page probe, since
# the sidecar calls `probe()`/`pull()` with no explicit base_url.
from research_engine import catalog
from research_engine.llm_factory import map_local_host
from research_engine.runconfig import get_run_config

logger = structlog.get_logger()


def _log_probe_failure(event: str, **fields: object) -> None:
    """Best-effort structured log for a `probe()`/`pull()` failure.

    Both callers promise never to raise, and this call sits inside the one except-block
    standing between an already-caught transport failure and that clean return — so a
    broken log sink would break the promise instead of just losing a diagnostic line.
    Observed on Windows: unlike stdlib `logging` (which swallows a handler's own I/O
    failure by design, via `Handler.handleError`), structlog's sink writes straight to
    `sys.stdout`/`sys.stderr` with no such protection, and that write has been seen to
    raise there. The information isn't lost either way — `error=str(exc)` still reaches
    the caller through the returned status/event — so dropping the log line is the
    correct trade, not a "never swallow" violation.
    """
    try:
        logger.info(event, **fields)
    except Exception:  # noqa: BLE001 — the log call itself must never be why probe()/pull() raise
        pass


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


# Models known not to support tool calling in Ollama.
_NO_TOOL_HINTS = ("deepseek-r1", "deepseek-coder", "phi3:mini", "tinyllama")


def _supports_tools(name: str) -> bool:
    lowered = name.lower()
    return not any(hint in lowered for hint in _NO_TOOL_HINTS)


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
    # True if the model supports tool calling (required for Executor role).
    supports_tools: bool = True
    # Parsed parameter count in billions, when the tag states one.
    params_b: float | None = None


#: "Not detected" used to conflate two states with different fixes: no Ollama
#: installed needs the installer link, Ollama installed but not running needs the
#: one-click Start button (docs/07 §2, Phase 2b). Both looked identical over HTTP.
InstallState = Literal["running", "installed_not_running", "not_installed"]

# Installer locations the platform installer sometimes doesn't add to PATH.
_OLLAMA_BINARY_CANDIDATES = (
    "/usr/local/bin/ollama",
    "/opt/homebrew/bin/ollama",
    "/usr/bin/ollama",
    "/Applications/Ollama.app/Contents/Resources/ollama",
)


def resolve_binary() -> str | None:
    """The `ollama` executable's path on this machine, checked beyond PATH — the
    macOS/Windows installers do not always add it there. `None` when nothing is found.
    Public: `sidecar.py::start_local_server` needs the actual path to spawn, not just
    whether one exists.
    """
    on_path = shutil.which("ollama")
    if on_path:
        return on_path
    windows_candidate = Path.home() / "AppData" / "Local" / "Programs" / "Ollama" / "ollama.exe"
    for candidate in (*_OLLAMA_BINARY_CANDIDATES, str(windows_candidate)):
        if Path(candidate).exists():
            return candidate
    return None


def _binary_installed() -> bool:
    """Whether an `ollama` executable exists on this machine, beyond just PATH."""
    return resolve_binary() is not None


@dataclass
class LocalLLMStatus:
    """Everything the settings UI needs to describe the local-LLM connection."""

    configured_base_url: str
    reachable: bool
    models: list[LocalModel] = field(default_factory=list)
    error: str | None = None
    # Actionable next step, phrased for a user rather than an operator.
    hint: str | None = None
    install_state: InstallState = "not_installed"

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


def _match_catalog_route(name: str) -> tuple[str, bool]:
    """Route for an installed Ollama tag, plus whether its family is in the catalog.

    The route is always the **exact installed tag**. Returning the catalog's family route
    instead collapsed distinct models onto one entry and then failed to run them: picking
    `deepseek-r1:1.5b` or `deepseek-r1:14b` both produced `ollama:deepseek-r1`, which
    Ollama 404s because no `deepseek-r1:latest` exists — and picking `qwen2.5:7b` produced
    `ollama:qwen2.5`, which silently ran `qwen2.5:latest`, a different model than the one
    the user selected. Silently running the wrong model is the worse of the two.

    Catalog membership is still reported: it is what tells the UI a model has known
    pricing and capabilities. It just no longer decides what gets dialled.
    """
    family = name.split(":", 1)[0]
    spec = catalog.get(family)
    in_catalog = spec is not None and spec.provider == "ollama"
    return f"ollama:{name}", in_catalog


async def probe(base_url: str | None = None) -> LocalLLMStatus:
    """Ask the configured Ollama server what it has. Never raises.

    `configured` is what the UI displays and what a native run actually uses; `dial_url`
    is what this probe connects to. Inside Docker those must differ — `localhost` there is
    the container, not the host running Ollama — and until this call they didn't: the
    probe dialled the raw configured value and, on failure, told the user to retype it as
    `host.docker.internal` by hand. `llm_factory.get_llm` already made that same
    substitution automatically for the actual pipeline calls; the health check now agrees
    with the thing it's supposed to be checking.
    """
    configured = base_url or get_run_config().ollama_base_url
    dial_url = map_local_host(configured)
    url = f"{_api_root(dial_url)}/api/tags"

    try:
        async with httpx.AsyncClient(timeout=_PROBE_TIMEOUT_SECONDS) as client:
            response = await client.get(url)
            response.raise_for_status()
            payload = response.json()
    except Exception as exc:  # noqa: BLE001 — every failure is "not reachable" to a user
        _log_probe_failure(
            "local_llm_probe_failed", configured=configured, dial_url=url, error=str(exc)
        )
        # The Docker/localhost rewrite already happened above, so a stale "retype the
        # address as host.docker.internal" instruction here would tell the user to do by
        # hand what the code just did for them and failed at anyway — worse than no hint.
        installed = _binary_installed()
        return LocalLLMStatus(
            configured_base_url=configured,
            reachable=False,
            error=str(exc),
            hint=(
                "Ollama is installed but not running. Start it, then reload."
                if installed
                else "No local model server answered at this address. Start Ollama with "
                "`ollama serve`, then reload."
            ),
            install_state="installed_not_running" if installed else "not_installed",
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
                supports_tools=_supports_tools(name),
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
            "The server is running but has no models. Pull an embedding model for "
            "corpus retrieval, e.g. `ollama pull nomic-embed-text`. For research "
            "runs, use a hosted provider (Anthropic, Google, or OpenAI)."
        )
    elif not chat_models:
        hint = (
            "Only embedding models are installed — that is the recommended setup. "
            "Embedding models power corpus retrieval locally. For the research "
            "pipeline and chat, use a hosted provider for best quality."
        )
    elif all(m.likely_underpowered for m in chat_models):
        hint = (
            f"Every installed chat model looks small (under {_MIN_RESEARCH_PARAMS_B:.0f}B). "
            "Local models at this size usually fail the research pipeline's "
            "structured-evidence step. Use a hosted provider (Anthropic, Google, "
            "or OpenAI) for research runs."
        )

    return LocalLLMStatus(
        configured_base_url=configured,
        reachable=True,
        models=models,
        hint=hint,
        install_state="running",
    )


@dataclass
class PullProgress:
    """One line of Ollama's streaming `/api/pull` response."""

    status: str
    completed: int | None = None
    total: int | None = None
    error: str | None = None


async def pull(model: str, base_url: str | None = None) -> AsyncIterator[PullProgress]:
    """Stream Ollama's pull progress for `model` (docs/07 §2, Phase 2b: "recommended-
    model one-click pull with progress"). Never raises — a transport failure or a
    non-200 response yields one `PullProgress(status="error")` instead of propagating,
    matching `probe`'s "every failure becomes a status a user can act on" contract.
    """
    configured = base_url or get_run_config().ollama_base_url
    dial_url = map_local_host(configured)
    url = f"{_api_root(dial_url)}/api/pull"

    try:
        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream("POST", url, json={"name": model, "stream": True}) as resp:
                if resp.status_code != 200:
                    body = await resp.aread()
                    yield PullProgress(
                        status="error",
                        error=f"HTTP {resp.status_code}: {body.decode(errors='replace')[:200]}",
                    )
                    return
                async for line in resp.aiter_lines():
                    if not line.strip():
                        continue
                    try:
                        payload = json.loads(line)
                    except Exception:  # noqa: BLE001 — a stray non-JSON line is not fatal
                        continue
                    yield PullProgress(
                        status=payload.get("status", ""),
                        completed=payload.get("completed"),
                        total=payload.get("total"),
                        error=payload.get("error"),
                    )
    except Exception as exc:  # noqa: BLE001 — every transport failure is "no response"
        _log_probe_failure("local_llm_pull_failed", model=model, error=str(exc))
        yield PullProgress(status="error", error=str(exc))
