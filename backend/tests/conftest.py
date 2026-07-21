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
