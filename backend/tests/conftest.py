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

# Pin model routing so tests never inherit the operator's .env choice (e.g. a local
# Ollama route priced at $0 would break the cost-accounting assertions). Priced
# catalog models keep fake-mode cost estimates deterministic and non-zero.
for _role in ("PLANNER", "EXECUTOR", "CRITIC", "SYNTHESIZER", "CHAT"):
    os.environ[f"MODEL_{_role}"] = "google:gemini-2.5-flash"

# `research_engine` no longer reads `app.config` (docs/13 §2), so the engine's config must be
# installed by a host. Tests are a host: without this, the graph would run in real mode.
from app.runtime import install_process_default  # noqa: E402

install_process_default()


# ── Real-database fixtures ─────────────────────────────────────────────────────────
#
# Most of this suite is unit-level and needs no database. Project memory is not: its
# Definition of Done is about what SQL returns — cross-project isolation, rejected drafts
# staying out of retrieval, no orphan vectors after a delete (docs/14 §9). Asserting those
# against a mock would prove the mock behaves, which is exactly the class of test docs/00
# says the previous iteration of this project died of.
#
# So these tests run against a real Postgres with pgvector, and skip loudly when there
# isn't one. CI always has it (both `postgres` services are pinned to
# pgvector/pgvector:pg16); a developer without one gets a skip and a reason, not a
# failure they have to interpret.

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402


def _postgres_dsn() -> str:
    return os.environ["DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://")


def _database_ready() -> tuple[bool, str]:
    """Whether a Postgres with pgvector is reachable, and why not when it isn't."""
    try:
        import psycopg
    except ImportError:  # pragma: no cover
        return False, "psycopg is not installed"
    try:
        with psycopg.connect(_postgres_dsn(), connect_timeout=3) as conn:
            installed = conn.execute(
                "SELECT 1 FROM pg_available_extensions WHERE name = 'vector'"
            ).fetchone()
    except Exception as exc:  # noqa: BLE001
        return False, f"no Postgres at DATABASE_URL ({type(exc).__name__})"
    if not installed:
        return False, "Postgres has no pgvector extension available (use pgvector/pgvector:pgNN)"
    return True, ""


_DB_READY, _DB_REASON = _database_ready()

requires_db = pytest.mark.skipif(not _DB_READY, reason=f"needs Postgres + pgvector: {_DB_REASON}")

# Every table a test can dirty. Truncating `users` cascades to projects, sessions and
# their children, but chat threads hang off projects and memory off both — listing them
# explicitly keeps the reset honest if a future FK stops cascading the way it does today.
_TRUNCATE = (
    "TRUNCATE TABLE memory_chunks, chat_messages, chat_threads, agent_logs, "
    "audit_log, refresh_tokens, sessions, projects, users RESTART IDENTITY CASCADE"
)


@pytest.fixture(scope="session")
def migrated_database():
    """Bring the test database to head once per session."""
    if not _DB_READY:
        pytest.skip(_DB_REASON)
    import subprocess
    import sys
    from pathlib import Path

    backend = Path(__file__).resolve().parents[1]
    # `-m alembic` rather than the console script: the interpreter running the tests is
    # the one with the dependencies, and its bin/ is not necessarily on PATH.
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=backend,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:  # pragma: no cover - surfaced as a fixture error
        raise RuntimeError(f"alembic upgrade head failed:\n{result.stdout}\n{result.stderr}")
    return True


@pytest_asyncio.fixture
async def db(migrated_database):  # noqa: ARG001 - ordering dependency
    """A clean database and one session against it, per test.

    The engine is disposed on teardown, not just the session. `app.db.base.engine` is a
    module-level singleton with a connection pool, while pytest-asyncio gives each test
    its own event loop — so a pooled connection created under test A is bound to a loop
    that is closed by the time test B reuses it ("Event loop is closed", raised from the
    garbage collector, which makes it look like an unrelated flake).
    """
    from sqlalchemy import text

    from app.db.base import AsyncSessionLocal, engine

    async with AsyncSessionLocal() as session:
        await session.execute(text(_TRUNCATE))
        await session.commit()
        try:
            yield session
        finally:
            await session.rollback()
    await engine.dispose()
