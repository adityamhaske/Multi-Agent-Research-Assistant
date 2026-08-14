"""
Provider-pluggable LLM factory (docs/architecture/04_Agent_Design.md §7, docs/13 §6).

Roles are resolved from "provider:model" config strings so BYOK users can point
any role at any configured provider. Prices and per-model capabilities come from
`research_engine.catalog`; a routed model with no price fails fast at startup.

LLM_MODE=fake returns deterministic scripted models (no keys, no network).
"""

from __future__ import annotations

from contextvars import ContextVar

from langchain_core.language_models.chat_models import BaseChatModel

from research_engine import catalog
from research_engine.runconfig import RunConfig, get_run_config

# Roles → per-role generation config.
_ROLE_CONFIG = {
    "planner": {"temperature": 0.1, "max_tokens": 2000},
    "executor": {"temperature": 0.2, "max_tokens": 4000},
    "critic": {"temperature": 0.0, "max_tokens": 1000},
    "synthesizer": {"temperature": 0.2, "max_tokens": 6000},
    "chat": {"temperature": 0.3, "max_tokens": 2000},
}


# ── Per-user BYOK keys ────────────────────────────────────────────────────────
# The worker installs the running user's decrypted provider key for the duration
# of their pipeline run; get_llm reads it here. A ContextVar (not a global) keeps
# concurrent runs in the same worker process isolated from each other, and the
# key is never written to disk or logs. Empty/unset falls back to the server key.
_user_keys: ContextVar[dict[str, str] | None] = ContextVar("user_provider_keys", default=None)


def set_user_keys(keys: dict[str, str]):
    """Install per-user provider keys for this context. Returns a reset token."""
    return _user_keys.set(keys or {})


def reset_user_keys(token) -> None:
    _user_keys.reset(token)


def api_key_for(provider: str) -> str:
    """The user's BYOK key for a provider if present, else the deployment's key."""
    user_key = (_user_keys.get() or {}).get(provider, "")
    if user_key:
        return user_key
    return get_run_config().provider_keys.get(provider, "")


def model_name_for(role: str) -> str:
    """The bare model id (no provider prefix) for a role — used for pricing."""
    return get_run_config().model_for(role).split(":", 1)[-1]


def validate_pricing(cfg: RunConfig | None = None) -> None:
    """Fail fast if any routed model has no price (called at startup).

    An unpriced model is refused rather than defaulted to zero: the price feeds the budget
    guard, and a silently-zero price turns the per-session spend cap into a no-op.
    """
    cfg = cfg or get_run_config()
    if cfg.llm_mode == "fake":
        return
    missing = set()
    for role in cfg.models:
        provider, _, name = cfg.model_for(role).partition(":")
        if provider in ("custom", "openrouter"):
            continue
        spec = catalog.get(name)
        if spec is None or not spec.priced:
            missing.add(name)
    missing = sorted(missing)
    if missing:
        raise ValueError(
            f"No price for routed model(s): {missing}. Add a ModelSpec to "
            f"research_engine/catalog.py (or call catalog.register() at startup) with the "
            f"provider's published per-1M-token prices — never estimated (docs/13 §6)."
        )


def sampling_supported(model: str) -> bool:
    """Whether this model accepts temperature/top_p/top_k.

    Unknown models default to True, matching every provider's historical behaviour. The
    cost of being wrong is asymmetric but recoverable in both directions: a needless
    omission changes nothing observable, and a rejected parameter surfaces as a loud 400
    rather than a silently degraded run.
    """
    spec = catalog.get(model)
    return True if spec is None else spec.sampling_params_supported


def map_local_host(base_url: str) -> str:
    """Rewrite a localhost base URL to `host.docker.internal` when running in a container.

    Inside Docker, `localhost` is the container itself, so a model server on the host is
    unreachable under that name; outside Docker, `host.docker.internal` does not resolve
    at all. Neither literal works in both places, so the right value depends on where the
    process happens to run — which a single `.env` cannot express. Detecting the
    container at call time lets one config value serve both.

    Public (no leading underscore): `app/services/local_llm.py`'s health probe needs the
    same mapping and previously duplicated none of it — it dialled the raw configured URL
    and, inside Docker, told the user to fix it by hand instead of fixing it. One
    implementation, reused, so the two paths cannot drift out of agreement again.
    """
    for prefix in (
        "http://localhost:",
        "http://127.0.0.1:",
        "https://localhost:",
        "https://127.0.0.1:",
    ):
        if base_url.startswith(prefix):
            try:
                import socket

                socket.gethostbyname("host.docker.internal")
            except Exception:
                return base_url  # not in a container — localhost is already correct
            return base_url.replace("localhost", "host.docker.internal", 1).replace(
                "127.0.0.1", "host.docker.internal", 1
            )
    return base_url


def _build(provider: str, model: str, role: str) -> BaseChatModel:
    cfg = _ROLE_CONFIG[role]
    key = api_key_for(provider)
    # Ollama and local custom endpoints run locally and can operate without a key.
    if not key and provider not in ("ollama", "custom"):
        # Fail with an actionable message rather than a provider-side 401 buried
        # in a stack trace — this is what a BYOK user sees if they haven't added
        # a key and the deployment has none configured.
        raise ValueError(
            f"No API key available for provider '{provider}'. Add your own key in "
            f"Settings, or configure {provider.upper()}_API_KEY on the server."
        )

    if provider == "google":
        from langchain_google_genai import ChatGoogleGenerativeAI

        return ChatGoogleGenerativeAI(
            model=model,
            google_api_key=key,
            temperature=cfg["temperature"],
            max_output_tokens=cfg["max_tokens"],
        )

    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        # Newer tiers reject temperature/top_p/top_k with a 400; omit them there so
        # structured output and tool calls still work. `max_tokens` (the output cap) is
        # accepted everywhere. Which models reject is a catalog fact, not a prefix guess —
        # the old prefix tuple is what let `claude-opus-5` slip through (docs/12 M8).
        kwargs: dict = {"model": model, "api_key": key, "max_tokens": cfg["max_tokens"]}
        if sampling_supported(model):
            kwargs["temperature"] = cfg["temperature"]
        return ChatAnthropic(**kwargs)

    if provider == "openai":
        from langchain_openai import ChatOpenAI

        kwargs = {"model": model, "api_key": key, "max_tokens": cfg["max_tokens"]}
        if sampling_supported(model):
            kwargs["temperature"] = cfg["temperature"]
        return ChatOpenAI(**kwargs)

    if provider == "openrouter":
        # OpenRouter speaks the OpenAI wire protocol, so one base-URL override buys access
        # to most frontier models on a single key — the largest BYOK ergonomics win
        # available (docs/13 §6). Model ids are namespaced, e.g. "anthropic/claude-opus-5".
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=model,
            api_key=key,
            base_url="https://openrouter.ai/api/v1",
            max_tokens=cfg["max_tokens"],
            temperature=cfg["temperature"],
        )

    if provider == "ollama":
        # Local inference, also OpenAI-compatible. This is offline tier 2 (docs/13 §8):
        # no key, no inference egress. The endpoint is overridable for a remote box.
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=model,
            api_key=key or "ollama",  # the client requires a non-empty value; unused
            base_url=map_local_host(get_run_config().ollama_base_url),
            max_tokens=cfg["max_tokens"],
            temperature=cfg["temperature"],
        )

    if provider == "custom":
        from langchain_openai import ChatOpenAI

        base_url = api_key_for("custom_base_url")
        if get_run_config().enforce_ssrf_guards and base_url:
            from research_engine.net_guard import SSRFBlocked, validate_url

            try:
                validate_url(base_url)
            except SSRFBlocked as e:
                raise ValueError(f"Blocked by SSRF guard: {e}") from e

        base_url = map_local_host(base_url) if base_url else base_url

        kwargs = {"model": model, "api_key": key or "custom", "max_tokens": cfg["max_tokens"]}
        if base_url:
            kwargs["base_url"] = base_url
        if sampling_supported(model):
            kwargs["temperature"] = cfg["temperature"]
        return ChatOpenAI(**kwargs)

    raise ValueError(
        f"Unknown LLM provider '{provider}' for role '{role}'. "
        f"Known providers: {', '.join(catalog.KNOWN_PROVIDERS)}."
    )


def get_llm(role: str) -> BaseChatModel:
    """Return the chat model for an agent role."""
    cfg = get_run_config()
    if cfg.llm_mode == "fake":
        from research_engine.fakes import fake_model

        return fake_model()
    provider, _, model = cfg.model_for(role).partition(":")
    return _build(provider, model, role)


def text_of(message_or_chunk) -> str:
    """Extract plain text from a model response.

    Modern LangChain returns `.content` either as a plain string (Gemini 2.5,
    most providers) or as a list of typed content blocks (Gemini 3.x, and any
    model emitting thinking + text parts). Treating the list case with str()
    would splice a Python repr into the report, and ignoring it would drop the
    text entirely — so normalize both shapes here and use this everywhere.
    """
    content = getattr(message_or_chunk, "content", message_or_chunk)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                # Only user-visible text; thinking/reasoning blocks are skipped.
                if block.get("type") in (None, "text") and isinstance(block.get("text"), str):
                    parts.append(block["text"])
        return "".join(parts)
    return ""


def estimate_cost(response, role: str) -> float:
    """Cost of one response from its usage_metadata and the role's model price.

    An unknown or unpriced model contributes 0. That is safe only because
    `validate_pricing()` refuses to start a real run in that state — without that check
    this fallback would quietly disable the budget guard.
    """
    usage = getattr(response, "usage_metadata", None) or {}
    in_tok = usage.get("input_tokens", 0)
    out_tok = usage.get("output_tokens", 0)
    spec = catalog.get(model_name_for(role))
    if spec is None or not spec.priced:
        return 0.0
    return (in_tok / 1_000_000 * spec.input_per_mtok) + (out_tok / 1_000_000 * spec.output_per_mtok)


def token_counts(response) -> tuple[int, int]:
    usage = getattr(response, "usage_metadata", None) or {}
    return usage.get("input_tokens", 0), usage.get("output_tokens", 0)
