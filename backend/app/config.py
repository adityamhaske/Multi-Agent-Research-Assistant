from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file="../.env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # LLM API Keys
    openai_api_key: str = ""   # No longer required — using Gemini
    google_api_key: str        # Required: get from https://aistudio.google.com/apikey

    # Database
    database_url: str  # postgresql+asyncpg://...

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Auth
    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 60
    jwt_refresh_token_expire_days: int = 30

    # Agent settings
    max_critic_loops: int = 3
    max_cost_per_session_usd: float = 0.50
    celery_task_timeout_seconds: int = 660

    # LangSmith (optional)
    langchain_tracing_v2: bool = False
    langchain_api_key: str = ""
    langchain_project: str = "multi-agent-research-assistant"

    # CORS
    frontend_url: str = "http://localhost:3000"

@lru_cache()
def get_settings() -> Settings:
    return Settings()

settings = get_settings()
