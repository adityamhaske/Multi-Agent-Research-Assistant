"""
Test configuration.

Environment variables are set BEFORE any app import so pydantic-settings never
depends on a developer's local .env (CI has none).
"""

import os

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("LLM_MODE", "fake")
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://research_user:research_pass@localhost:5432/research_test_db",
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/1")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-" + "a" * 32)

# `app.agent` no longer reads `app.config` (docs/13 §2), so the engine's config must be
# installed by a host. Tests are a host: without this, the graph would run in real mode.
from app.runtime import install_process_default  # noqa: E402

install_process_default()
