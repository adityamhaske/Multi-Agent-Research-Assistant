"""
The local host's adapters (docs/13 §4, docs/12 M6 step 4).

The server's implementations of the engine's ports live in `app/adapters.py` and speak
Postgres and Redis. These are their laptop equivalents: a SQLite search cache and an
in-process event sink. Together with LangGraph's `AsyncSqliteSaver` they are everything
needed to run the full pipeline — gate included — on a machine with no Docker, no
Postgres, no Redis, and no login.

Shipped inside the engine package rather than a separate host because they are the
*reference* local host: `research_engine.cli` uses them to prove the extraction worked
(M6's Definition of Done), and the desktop sidecar (docs/12 M9) will use the same two
classes behind a Tauri shell. That is a deliberate exception to "hosts live outside the
engine" — the alternative is a second package that exists only to hold 80 lines.

The SQLite cache uses stdlib `sqlite3` on a worker thread, not `aiosqlite`, so it adds no
dependency to the engine's core install. The checkpointer does need
`langgraph-checkpoint-sqlite` — the `[local]` extra in `pyproject.toml`.
"""

from __future__ import annotations

import asyncio
import os
import sqlite3
import time
from collections.abc import Callable
from pathlib import Path

from research_engine.runconfig import DEFAULT_MODELS, ROLES, RunConfig

_PROVIDER_ENV = {
    "google": "GOOGLE_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
}


def load_env_file(path: str | Path = "../.env") -> bool:
    """Load a `.env` into the process environment, if one exists. Returns whether it did.

    Real environment variables always win over the file, so an explicit `KEY=… make eval`
    or a CI secret is never clobbered by a stale local file.

    This exists because decoupling the engine from `app.config` (docs/12 M6 step 5) also
    removed pydantic-settings' implicit `.env` loading from the eval and CLI paths — which
    silently made `LLM_MODE=real make eval` stop finding a key that was sitting right
    there. Hosts opt in explicitly; the engine still reads nothing on its own.

    python-dotenv is imported lazily and a missing dependency is a no-op, so it stays out
    of the engine's required dependency set.
    """
    env_path = Path(path)
    if not env_path.is_file():
        return False
    try:
        from dotenv import load_dotenv
    except ImportError:  # pragma: no cover - optional convenience
        return False
    return bool(load_dotenv(env_path, override=False))


def run_config_from_env(*, fake: bool) -> RunConfig:
    """Build the engine's config from the process environment.

    The local host's counterpart to `app/runtime.py`: same job, different source, and no
    pydantic-settings — so it needs no `DATABASE_URL` and no `JWT_SECRET_KEY` to exist.
    The desktop build (docs/12 M9) swaps these `os.environ` reads for a config file plus
    the OS keychain and nothing else about the engine changes.

    Used by `research_engine.cli` and by the eval harness, which is why it lives here
    rather than in either one.
    """
    if fake:
        return RunConfig(llm_mode="fake")

    models = {role: os.environ.get(f"MODEL_{role.upper()}", DEFAULT_MODELS[role]) for role in ROLES}
    keys = {
        provider: os.environ[env] for provider, env in _PROVIDER_ENV.items() if os.environ.get(env)
    }
    if not keys:
        routed = sorted({m.split(":", 1)[0] for m in models.values()})
        wanted = ", ".join(_PROVIDER_ENV.get(p, p.upper()) for p in routed)
        raise SystemExit(
            f"No provider key found. Routing needs one of: {wanted}.\n"
            f"Export it, or run with --fake for a keyless demo."
        )
    return RunConfig(
        llm_mode="real",
        models=models,
        provider_keys=keys,
        tavily_api_key=os.environ.get("TAVILY_API_KEY", ""),
        brave_api_key=os.environ.get("BRAVE_API_KEY", ""),
    )


_SCHEMA = """
CREATE TABLE IF NOT EXISTS search_cache (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    expires_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_search_cache_expires ON search_cache (expires_at);
"""


def default_data_dir() -> Path:
    """Where a local run keeps its database. Overridable by every caller."""
    return Path.home() / ".research-engine"


class SqliteCache:
    """Search-result cache in a SQLite file — the desktop counterpart of `RedisCache`.

    Every operation runs on a worker thread so it never blocks the event loop, and each
    one opens its own short-lived connection: SQLite connections are not safe to share
    across threads, and the traffic here (a handful of reads per research task) makes
    pooling pointless.

    Expiry is enforced on read rather than by a background sweeper, and expired rows are
    deleted opportunistically. `retrievers.search` treats the whole cache as advisory, so
    a locked or corrupt database degrades a run to "uncached" instead of failing it.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=5.0)
        # WAL lets a reader and a writer coexist — matters once the desktop app runs
        # research and serves its UI from the same file.
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    def _get_sync(self, key: str) -> str | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT value, expires_at FROM search_cache WHERE key = ?", (key,)
            ).fetchone()
            if row is None:
                return None
            value, expires_at = row
            if expires_at <= time.time():
                conn.execute("DELETE FROM search_cache WHERE key = ?", (key,))
                return None
            return value

    def _set_sync(self, key: str, value: str, ttl: int) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO search_cache (key, value, expires_at) VALUES (?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value, "
                "expires_at = excluded.expires_at",
                (key, value, time.time() + ttl),
            )

    async def get(self, key: str) -> str | None:
        return await asyncio.to_thread(self._get_sync, key)

    async def set(self, key: str, value: str, ttl: int) -> None:
        await asyncio.to_thread(self._set_sync, key, value, ttl)


class InProcessEventSink:
    """Collects pipeline events in memory, optionally forwarding each one live.

    The server sink persists to `agent_logs` and publishes to Redis because its readers
    are in other processes. On a laptop the reader is the same process — the desktop
    sidecar streams these straight out over SSE, and the CLI prints them.

    `on_event` is called synchronously as each event arrives, which is what makes a live
    progress display possible; `events` keeps the full ordered history for replay.
    """

    def __init__(self, on_event: Callable[[dict], None] | None = None) -> None:
        self.events: list[dict] = []
        self._on_event = on_event

    async def __call__(self, session_id: str, event: dict) -> None:  # noqa: ARG002
        self.events.append(event)
        if self._on_event is not None:
            self._on_event(event)

    def by_agent(self, agent: str) -> list[dict]:
        return [e for e in self.events if e.get("agent") == agent]
