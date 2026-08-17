"""
Application settings.

All configuration comes from environment variables (or ../.env in dev).
Startup validation fails fast on dangerous values (docs/09 §3, docs/06 §7).
"""

from functools import lru_cache
from pathlib import Path
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
_KEYLESS_PROVIDERS = {"ollama", "custom"}


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
    openrouter_api_key: str = ""
    custom_api_key: str = ""
    custom_base_url: str = ""

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

    # ── Project memory / embeddings (docs/14 §4) ───────────────────────────────
    # Which provider turns approved reports into vectors. "auto" prefers a local
    # Ollama — free, no egress, and the reason a fully local deployment can still
    # do private retrieval — and falls back to whichever hosted provider has a key.
    # "none" disables ingestion and project chat rather than degrading them.
    embeddings_provider: Literal["auto", "ollama", "google", "openai", "none"] = "auto"
    # Blank means the provider's documented default. Changing this makes existing
    # chunks invisible until they are re-indexed: vectors from different models are
    # not comparable even at equal width, so retrieval filters on the model that
    # produced them. `GET /projects/{id}/memory/status` reports the mismatch.
    embeddings_model: str = ""

    # ── Search retrievers ──────────────────────────────────────────────────────
    tavily_api_key: str = ""
    brave_api_key: str = ""

    # ── Data stores ────────────────────────────────────────────────────────────
    database_url: str
    redis_url: str = "redis://localhost:6379/0"
    # Relative by default, which is fine in Docker (WORKDIR is fixed) and a trap outside
    # it: resolved against the process working directory, running from the repo root and
    # from `backend/` produced two different corpus roots, so a document uploaded by one
    # was invisible to the other. Read it through `corpus_path` below, never directly.
    corpus_dir: str = "data/corpus"

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
    # 0 = unlimited, for all three (docs/04 §6) — the same convention as the rate limits.
    # Unlimited by default: the dollar cap cannot act as a backstop on openrouter/custom,
    # where `estimate_cost()` returns 0.0, so a shipped default only ever killed runs on
    # the providers it *could* measure. Set these when a deployment wants a hard stop; cap
    # real spend at the provider. Mirrored in `research_engine/local.py` — change both.
    max_critic_loops: int = 2
    max_cost_per_session_usd: float = 0.0
    max_wallclock_seconds: int = 0
    max_input_tokens: int = 0
    # Research tasks run concurrently within a round (docs/12 M7). 1 = strictly
    # sequential, which is the only setting where budget overshoot is impossible.
    max_parallel_tasks: int = 4
    celery_task_timeout_seconds: int = 660

    # ── Per-user usage limits (docs/06 §2) ─────────────────────────────────────
    # 0 = unlimited, and unlimited is the default. These are abuse guards for a
    # multi-tenant deployment, not safety limits: this ships as a self-hosted,
    # single-tenant app where the operator is the only user and pays their own
    # provider bill, so throttling them protects nobody. A public demo should set
    # both to a positive number.
    #
    # Deliberately NOT covering login/register — those limits are brute-force
    # protection, a different concern, and stay on unconditionally.
    research_rate_limit_per_hour: int = 0
    chat_rate_limit_per_hour: int = 0

    # ── LangSmith (optional) ───────────────────────────────────────────────────
    langchain_tracing_v2: bool = False
    langchain_api_key: str = ""
    langchain_project: str = "multi-agent-research-assistant"

    # ── Frontend origin (dev only; prod uses the same-origin proxy) ────────────
    frontend_url: str = "http://localhost:3031"

    @model_validator(mode="after")
    def _validate_secrets(self) -> "Settings":
        secret = self.jwt_secret_key.strip()
        if len(secret) < 32 or secret.lower() in _PLACEHOLDER_SECRETS:
            raise ValueError(
                "JWT_SECRET_KEY must be >= 32 chars of real randomness "
                "(generate with: openssl rand -hex 32). "
                "Placeholder values are refused — see docs/architecture/06-security.md §1."
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
                "openrouter": self.openrouter_api_key,
                "custom": self.custom_api_key,
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

    @property
    def corpus_path(self) -> Path:
        """Where per-project corpus databases live, as an absolute path.

        A relative `corpus_dir` is anchored to the backend package root rather than the
        process working directory, so the answer does not depend on where the server
        happened to be started from. An absolute setting is honoured as given.

        This is a data-location bug, which is the expensive kind: nothing errors, the
        upload succeeds, and the document is simply not there when the next process looks
        for it under a different root.
        """
        configured = Path(self.corpus_dir)
        if configured.is_absolute():
            return configured
        # config.py lives at <backend>/app/config.py, so parents[1] is <backend>.
        return Path(__file__).resolve().parents[1] / configured


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
