"""
Provider-pluggable LLM factory (docs/04_Agent_Design.md §7).

Roles are resolved from "provider:model" config strings so BYOK users can point
any role at any configured provider. A versioned price table drives cost
accounting; a routed model with no price entry fails fast at startup.

LLM_MODE=fake returns deterministic scripted models (no keys, no network).
"""

from __future__ import annotations

from langchain_core.language_models.chat_models import BaseChatModel

from app.config import settings

# $ per 1M tokens. Review when models change (docs/03 upgrade policy).
PRICE_TABLE: dict[str, dict[str, float]] = {
    "gemini-2.5-pro": {"input": 1.25, "output": 5.00},
    "gemini-2.5-flash": {"input": 0.075, "output": 0.30},
    # Legacy fallbacks kept priced so mixed configs still boot.
    "gemini-1.5-pro": {"input": 1.25, "output": 5.00},
    "gemini-1.5-flash": {"input": 0.075, "output": 0.30},
}

# Roles → per-role generation config.
_ROLE_CONFIG = {
    "planner": {"temperature": 0.1, "max_tokens": 2000},
    "executor": {"temperature": 0.2, "max_tokens": 4000},
    "critic": {"temperature": 0.0, "max_tokens": 1000},
    "synthesizer": {"temperature": 0.4, "max_tokens": 6000},
    "chat": {"temperature": 0.3, "max_tokens": 2000},
}


def _routing() -> dict[str, str]:
    return {
        "planner": settings.model_planner,
        "executor": settings.model_executor,
        "critic": settings.model_critic,
        "synthesizer": settings.model_synthesizer,
        "chat": settings.model_chat,
    }


def model_name_for(role: str) -> str:
    """The bare model id (no provider prefix) for a role — used for pricing."""
    return _routing()[role].split(":", 1)[-1]


def validate_pricing() -> None:
    """Fail fast if any routed model lacks a price entry (called at startup)."""
    if settings.llm_mode == "fake":
        return
    missing = {name for name in (model_name_for(r) for r in _routing()) if name not in PRICE_TABLE}
    if missing:
        raise ValueError(
            f"No price-table entry for routed model(s): {sorted(missing)}. "
            f"Add them to app/agent/llm_factory.PRICE_TABLE (docs/04 §7)."
        )


def _build(provider: str, model: str, role: str) -> BaseChatModel:
    cfg = _ROLE_CONFIG[role]
    if provider == "google":
        from langchain_google_genai import ChatGoogleGenerativeAI

        return ChatGoogleGenerativeAI(
            model=model,
            google_api_key=settings.google_api_key,
            temperature=cfg["temperature"],
            max_output_tokens=cfg["max_tokens"],
        )
    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(
            model=model,
            api_key=settings.anthropic_api_key,
            temperature=cfg["temperature"],
            max_tokens=cfg["max_tokens"],
        )
    if provider == "openai":
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=model,
            api_key=settings.openai_api_key,
            temperature=cfg["temperature"],
            max_tokens=cfg["max_tokens"],
        )
    raise ValueError(f"Unknown LLM provider '{provider}' for role '{role}'")


def get_llm(role: str) -> BaseChatModel:
    """Return the chat model for an agent role."""
    if settings.llm_mode == "fake":
        from app.agent.fakes import fake_model

        return fake_model()
    provider, _, model = _routing()[role].partition(":")
    return _build(provider, model, role)


def estimate_cost(response, role: str) -> float:
    """Cost of one response from its usage_metadata and the role's model price."""
    usage = getattr(response, "usage_metadata", None) or {}
    in_tok = usage.get("input_tokens", 0)
    out_tok = usage.get("output_tokens", 0)
    price = PRICE_TABLE.get(model_name_for(role), {"input": 0.0, "output": 0.0})
    return (in_tok / 1_000_000 * price["input"]) + (out_tok / 1_000_000 * price["output"])


def token_counts(response) -> tuple[int, int]:
    usage = getattr(response, "usage_metadata", None) or {}
    return usage.get("input_tokens", 0), usage.get("output_tokens", 0)
