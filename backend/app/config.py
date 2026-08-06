"""
Application settings.

All configuration comes from environment variables (or ../.env in dev).
Startup validation fails fast on dangerous values (docs/09 §3, docs/06 §7).
"""

from functools import lru_cache
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Well-known placeholder secrets that must never reach runtime.
_PLACEHOLDER_SECRETS = {
    "change-me-to-a-long-random-secret-string-in-production",
    "changeme",
    "secret",
    "dev-secret",
}

# Providers that run without an API key (local inference), so the production
# key-presence check must not demand one for them.
_KEYLESS_PROVIDERS = {"ollama"}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file="../.env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Environment ────────────────────────────────────────────────────────────
    environment: Literal["development", "production", "test"] = "development"
    # fake = deterministic scripted LLMs + fixture retrievers (tests/CI)
    llm_mode: Literal["real", "fake"] = "real"

    # ── LLM providers (BYOK) ───────────────────────────────────────────────────
    google_api_key: str = ""
    anthropic_api_key: str = ""
    openai_api_key: str = ""

    # ── Model routing: "provider:model" (docs/04 §7) ──────────────────────────
    model_planner: str = "google:gemini-2.5-pro"
    model_executor: str = "google:gemini-2.5-flash"
    model_critic: str = "google:gemini-2.5-flash"
    model_synthesizer: str = "google:gemini-2.5-pro"
    model_chat: str = "google:gemini-2.5-flash"

    # ── Local LLM (Ollama) ─────────────────────────────────────────────────────
    # OpenAI-compatible endpoint of a local (or LAN) Ollama server. When the app
    # runs in Docker, use http://host.docker.internal:11434/v1 to reach an Ollama
    # running on the host machine (localhost inside a container is the container).
    ollama_base_url: str = "http://localhost:11434/v1"

    # ── Search retrievers ──────────────────────────────────────────────────────
    tavily_api_key: str = ""
    brave_api_key: str = ""

    # ── Data stores ────────────────────────────────────────────────────────────
    database_url: str
    redis_url: str = "redis://localhost:6379/0"

    # ── Auth ───────────────────────────────────────────────────────────────────
    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 15
    jwt_refresh_token_expire_days: int = 14
    require_email_verification: bool = False
    # Encrypts user-supplied BYOK provider keys at rest. Falls back to
    # jwt_secret_key (domain-separated via HKDF) so self-hosters need no extra
    # setup; set it explicitly to rotate JWTs without invalidating stored keys.
    encryption_key: str = ""

    # ── BYOK / usage limits ────────────────────────────────────────────────────
    # Default monthly token ceiling applied to new users (0 = unlimited). Public
    # deployments should set this so one account can't drain a shared server key.
    default_monthly_token_limit: int = 0

    # ── Agent budgets (docs/04 §6) ─────────────────────────────────────────────
    max_critic_loops: int = 2
    max_cost_per_session_usd: float = 0.50
    max_wallclock_seconds: int = 600
    # Research tasks run concurrently within a round (docs/12 M7). 1 = strictly
    # sequential, which is the only setting where budget overshoot is impossible.
    max_parallel_tasks: int = 4
    celery_task_timeout_seconds: int = 660

    # ── LangSmith (optional) ───────────────────────────────────────────────────
    langchain_tracing_v2: bool = False
    langchain_api_key: str = ""
    langchain_project: str = "multi-agent-research-assistant"

    # ── Frontend origin (dev only; prod uses the same-origin proxy) ────────────
    frontend_url: str = "http://localhost:3000"

    @model_validator(mode="after")
    def _validate_secrets(self) -> "Settings":
        secret = self.jwt_secret_key.strip()
        if len(secret) < 32 or secret.lower() in _PLACEHOLDER_SECRETS:
            raise ValueError(
                "JWT_SECRET_KEY must be >= 32 chars of real randomness "
                "(generate with: openssl rand -hex 32). "
                "Placeholder values are refused — see docs/engineering/06_Security.md §1."
            )
        if self.llm_mode == "real" and self.environment == "production":
            routed_providers = {
                m.split(":", 1)[0]
                for m in (
                    self.model_planner,
                    self.model_executor,
                    self.model_critic,
                    self.model_synthesizer,
                    self.model_chat,
                )
            }
            provider_keys = {
                "google": self.google_api_key,
                "anthropic": self.anthropic_api_key,
                "openai": self.openai_api_key,
            }
            for provider in routed_providers:
                if provider in _KEYLESS_PROVIDERS:
                    continue  # local inference (e.g. Ollama) needs no key
                if not provider_keys.get(provider, ""):
                    raise ValueError(
                        f"Model routing uses provider '{provider}' but no API key is "
                        f"configured for it. Set the key or change MODEL_* routing."
                    )
        return self

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
