"""
The desktop sidecar (docs/12 M9, docs/13 §7).

A single-process local host for the whole product: the same API surface the frontend
already speaks (`/api/v1/*`), backed by SQLite and the in-process research engine —
no Docker, no Postgres, no Redis, no login. The Tauri shell spawns it, reads the
handshake line (port + token) from stdout, and points its WebView at it.

Security contract (docs/13 §7 — not optional):

- Binds `127.0.0.1` only, on an ephemeral port chosen by the OS.
- Every request must carry the per-launch bearer token (`Authorization: Bearer …`).
  A localhost port with no token is reachable by any process on the machine — and by
  any web page via DNS rebinding. The token middleware fails closed: no token, wrong
  token, or a path outside the API prefix → 401. Native `EventSource` cannot set
  headers, so the SSE endpoint also accepts `?access_token=…`; the WebView injects it.
- No auth endpoints exist here. `GET /auth/me` returns the single local user so the
  frontend's existing session boot works unchanged; there is no password anywhere.

What differs from the server host, and nothing else:

- Celery → `asyncio.create_task`; Redis pub/sub → an in-process per-session fan-out.
  Events are still persisted to `agent_logs`, so SSE replay after reconnect works the
  same way (Last-Event-ID honored).
- `memory_chunks` is excluded from `create_all` — its pgvector column is Postgres-only.
  Project memory (approved-report ingestion) is the one feature absent on desktop;
  the airgapped corpus (docs/12 M10) has its own SQLite store and local embeddings.
- PDF export answers 501 by design: the desktop renders PDF via the WebView's
  print-to-PDF (docs/13 §7), and WeasyPrint's GTK chain stays out of the bundle.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import secrets
import sys
import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

# Launched as a plain script (Tauri shell, PyInstaller entry point), so make the
# backend packages importable regardless of the working directory. In a frozen
# build the modules resolve through PyInstaller's importer and this is a no-op.
_BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

import structlog
import uvicorn
from fastapi import (
    APIRouter,
    Depends,
    FastAPI,
    HTTPException,
    Request,
    Response,
    UploadFile,
    status,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from sqlalchemy import event, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# `download_headers` is the shared response-header policy for uploaded documents (the
# no-render rule plus the narrow PDF exception). Imported, never restated: a second copy
# of a security header policy is the worst kind of duplication this repo has. It lives in
# a stdlib-only module rather than in the server's corpus route, because importing that
# route reaches `app.config` and this host has no server settings to build (#50).
from app.services.document_headers import download_headers

# The run request models are imported, not restated: the desktop host must accept exactly
# the body the server does, and two Pydantic models with the same name in two files is how
# that stops being true.
from app.schemas.runs import CreateRunRequest as V2CreateRunRequest
from app.schemas.runs import PlanReviewRequest as V2PlanReviewRequest
from app.schemas.runs import ReportReviewRequest as V2ReportReviewRequest
from app.models import POSTGRES_ONLY_TABLES, Base
from app.models.agent_log import AgentLog
from app.models.audit_log import AuditLog
from app.models.chat_message import ChatMessage
from app.models.project import Project
from app.models.session import Session, SessionStatus
from app.models.user import User
from app.schemas.auth import UsageResponse
from app.schemas.project import (
    ProjectCreateRequest,
    ProjectListResponse,
    ProjectResponse,
    ProjectUpdateRequest,
)
from app.schemas.research import (
    ApprovalRequest,
    ChatMessageSchema,
    ChatRequest,
    OutlineSectionSchema,
    OutlineTemplateSchema,
    PlanDecisionRequest,
    PlanResponse,
    PlanTaskSchema,
    ResearchStartRequest,
    ResearchStartResponse,
    SessionDetail,
    SessionListResponse,
    SessionSummary,
)
from app.services import chat_scope, custom_endpoint, local_llm, provider_health, usage
from app.services.sse import SSE_HEADERS
from research_engine import bundle, catalog, citation_rate, outlines, prompts
from research_engine.corpus import CorpusStore
from research_engine.documents import MAX_DOCUMENT_BYTES
from research_engine.embeddings import EmbeddingsUnavailable, LocalEmbeddings
from research_engine.events import make_event
from research_engine.graph import build_graph
from research_engine.llm_factory import get_llm, text_of
from research_engine.local import SqliteCache, load_env_file
from research_engine.routing_rules import validate as validate_routing_rule
from research_engine.runconfig import (
    DEFAULT_MODELS,
    ROLES,
    RunConfig,
    reset_run_config,
    set_run_config,
)

# `resume`/`run` are also bound under aliases: in `_drive_run`, `run` is the ResearchRun
# row, and letting the row shadow the engine entry point would be a silent bug rather than
# a name error.
from research_engine.runner import RunOutcome, resume, run
from research_engine.runner import resume as resume_run
from research_engine.runner import run as run_pipeline

logger = structlog.get_logger()

DEFAULT_PROJECT_NAME = "General"
LOCAL_USER_EMAIL = "local@desktop.invalid"
_KEYRING_SERVICE = "research-assistant-desktop"

# Event types that end an SSE stream — identical to the server's contract
# (app/api/v1/research.py), so the same frontend hook drives both hosts. "Terminal" here
# means "the run has stopped producing events until a human acts", which is why both
# gates are in the list: PLAN_READY suspends the graph exactly as HITL_READY does, and a
# stream left open on it would hold a connection nothing will ever write to again.
_TERMINAL_EVENTS = ("COMPLETED", "FAILED", "HITL_READY", "PLAN_READY")

#: Events after which *replay* stops — the true terminals only, deliberately not the gates.
#: Second home of `app.api.v1.runs._REPLAY_STOP_EVENTS`; see the reasoning there. The
#: stop-list above is right for the live tail and wrong for the backlog: a client that
#: reconnects without a `Last-Event-ID` replays from 0, and stopping at the design gate
#: hides everything the run did after it. The server's session stream has always drawn
#: this distinction; the run streams and this host's session stream did not.
_REPLAY_STOP_EVENTS = ("COMPLETED", "FAILED")


# ── Event fan-out ────────────────────────────────────────────────────────────────


class SessionEventBus:
    """In-process replacement for the server's agent_logs + Redis pub/sub pair.

    Every event gets a monotonically increasing id (per session), is appended to the
    in-memory log, persisted to `agent_logs` by the caller, and broadcast to every
    attached SSE listener. Reconnecting clients replay from the DB via Last-Event-ID,
    exactly like the server stream.
    """

    def __init__(self) -> None:
        self._logs: dict[str, list[tuple[int, dict]]] = {}
        self._next: dict[str, int] = {}
        self._listeners: dict[str, list[asyncio.Queue]] = {}

    def append(self, session_id: str, payload: dict) -> int:
        eid = self._next.get(session_id, 0) + 1
        self._next[session_id] = eid
        self._logs.setdefault(session_id, []).append((eid, payload))
        for queue in self._listeners.get(session_id, []):
            queue.put_nowait((eid, payload))
        return eid

    def backlog(self, session_id: str, after_id: int = 0) -> list[tuple[int, dict]]:
        return [(i, p) for i, p in self._logs.get(session_id, []) if i > after_id]

    @asynccontextmanager
    async def subscribe(self, session_id: str) -> AsyncGenerator[asyncio.Queue, None]:
        queue: asyncio.Queue = asyncio.Queue()
        self._listeners.setdefault(session_id, []).append(queue)
        try:
            yield queue
        finally:
            self._listeners.get(session_id, []).remove(queue)


class PersistingSink:
    """The run's EventSink: assigns ids, fans out live, persists for replay.

    Matches the server worker's sink semantics (docs/13 §4): durable row first, then
    live delivery — so a reconnecting stream never loses an event either way.
    """

    def __init__(self, bus: SessionEventBus, session_factory: async_sessionmaker) -> None:
        self.bus = bus
        self._session_factory = session_factory

    async def __call__(self, session_id: str, event_payload: dict) -> None:
        eid = self.bus.append(session_id, event_payload)
        try:
            async with self._session_factory() as db:
                db.add(
                    AgentLog(
                        session_id=uuid.UUID(session_id),
                        event_type=event_payload.get("type") or "agent_log",
                        agent_name=event_payload.get("agent"),
                        payload=event_payload,
                    )
                )
                await db.commit()
        except Exception as e:  # noqa: BLE001 — live delivery must not die on persistence
            logger.warning("sidecar_event_persist_failed", session_id=session_id, error=str(e))
        event_payload["id"] = eid


# ── Keys ─────────────────────────────────────────────────────────────────────────


def _add_missing_columns(sync_conn, tables) -> None:
    """Add ORM-declared columns that an existing SQLite file is missing.

    The desktop deliberately builds its schema with `create_all` rather than Alembic:
    the migrations are Postgres-shaped from 0001 onward (JSONB, and later pgvector), and
    the ORM's `with_variant` types are what make one model set serve both hosts
    (app/models/types.py). But `create_all` only creates *missing tables* — it never
    alters an existing one, so every column added after a user's first launch was
    invisible to them. Nothing has shipped yet, which is exactly why this is worth fixing
    now: the first release that adds a column would otherwise break every install.

    Derived from `Base.metadata` rather than a hand-written list, so a column added to a
    model reaches the desktop without anyone remembering a second place to edit — the
    class of drift this codebase has already paid for more than once.

    **Additive only.** Renames, drops, type changes and data backfills are not handled and
    pass silently; SQLite cannot express most of them without a table rebuild. If one is
    ever needed, it needs explicit handling here rather than an assumption that this
    covers it.

    Concretely already true of `ck_source_ret` (0023_corpus_document_retrieval_status):
    widening it to admit `CORPUS_DOCUMENT` reaches a fresh install's `create_all` and the
    server's `alembic upgrade`, but an existing local `corpus.sqlite` keeps the narrower
    constraint it was created with, unrebuilt, until this function (or a dedicated
    migration) does something about it. Low-risk today only because the *absence* of that
    value made every corpus-mode evidence insert fail outright — no installed database can
    hold a `CORPUS_DOCUMENT` row the rebuild would need to preserve.
    """
    inspector = sa_inspect(sync_conn)
    existing_tables = set(inspector.get_table_names())

    for table in tables:
        if table.name not in existing_tables:
            continue  # create_all just made it, so it is already current
        have = {c["name"] for c in inspector.get_columns(table.name)}
        for column in table.columns:
            if column.name in have:
                continue
            ddl_type = column.type.compile(dialect=sync_conn.dialect)
            clause = f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {ddl_type}'
            # SQLite requires a non-null default when adding a NOT NULL column to a table
            # that already has rows. Use the column's own server_default so the value
            # matches what a fresh install would get.
            default = getattr(column.server_default, "arg", None)
            if default is not None:
                clause += f" DEFAULT {default}"
            if not column.nullable:
                clause += " NOT NULL"
            sync_conn.exec_driver_sql(clause)
            logger.info("sidecar_schema_column_added", table=table.name, column=column.name)


def _keyring():
    """The OS keychain, lazily imported. None when the platform has no backend."""
    try:
        import keyring
        from keyring.errors import KeyringError  # noqa: F401

        return keyring
    except Exception:  # noqa: BLE001 — any import failure means "no keychain here"
        return None


def store_key(provider: str, key: str) -> None:
    kr = _keyring()
    if kr is None:
        raise RuntimeError(
            "No OS keychain is available on this machine. Export the key as an "
            "environment variable instead (e.g. GOOGLE_API_KEY)."
        )
    kr.set_password(_KEYRING_SERVICE, provider, key)


def stored_keys() -> dict[str, str]:
    """Provider keys from the OS keychain. Empty where there is no keychain."""
    kr = _keyring()
    keys: dict[str, str] = {}
    if kr is None:
        return keys
    for provider in ("google", "anthropic", "openai", "openrouter", "custom"):
        try:
            value = kr.get_password(_KEYRING_SERVICE, provider)
        except Exception:  # noqa: BLE001 — one locked backend must not sink the rest
            continue
        if value:
            keys[provider] = value
    return keys


def delete_key(provider: str) -> None:
    kr = _keyring()
    if kr is None:
        raise RuntimeError("No OS keychain is available on this machine.")
    try:
        kr.delete_password(_KEYRING_SERVICE, provider)
    except KeyError:  # keyring raises KeyError for "nothing stored under this name"
        pass


# ── Saved model routing ───────────────────────────────────────────────────────────
#
# The server keeps the user's routing on the users row; the desktop keeps it in one
# JSON file under the data directory. Validation mirrors `app.services.model_routing`
# (which imports `app.config` and so cannot run here): a saved routing must be
# startable, so a run can never fail on a model that could have been rejected here.


def _routing_path(data_dir: str | Path) -> Path:
    return Path(data_dir) / "routing.json"


#: The server's rule, not a copy of it. This host used to restate the check and the
#: restatement went stale: it demanded catalog membership for every id, so a `custom:`
#: gateway route was unselectable here and the only local routes that validated were
#: family names like `ollama:deepseek-r1` — which Ollama 404s without a `:latest` tag.
#: `routing_rules` needs only the catalog and the role list, so it runs on this host
#: unchanged; the `app.config` dependency that forced the split belongs to
#: `available_providers`/`deployment_default`, which stay server-only.
validate_routing = validate_routing_rule


def stored_routing(data_dir: str | Path) -> dict[str, str] | None:
    """The user's saved routing, or None. A corrupt file degrades to the default."""
    try:
        raw = json.loads(_routing_path(data_dir).read_text(encoding="utf-8"))
        return validate_routing(raw)
    except FileNotFoundError:
        return None
    except Exception:  # noqa: BLE001 — bad JSON / stale model ids must not sink launch
        return None


def save_routing(data_dir: str | Path, routing: dict[str, str] | None) -> None:
    path = _routing_path(data_dir)
    if routing is None:
        path.unlink(missing_ok=True)
        return
    path.write_text(json.dumps(routing, indent=2), encoding="utf-8")


# ── Custom Endpoint ──────────────────────────────────────────────────────────────

#: The demo session shown on first launch. Deliberately a real question rather than
#: lorem: the point of leading with it is to show what the product produces, and
#: "Fixture Report" demonstrates only that the plumbing runs.
DEMO_QUERY = "What is retrieval-augmented generation, and when does it beat fine-tuning?"


def _demo_seeded_path(data_dir: str | Path) -> Path:
    return Path(data_dir) / "demo_seeded.json"


def demo_already_seeded(data_dir: str | Path) -> bool:
    """Whether first-launch seeding has already happened.

    A marker, not a count of sessions. "No sessions exist" is the obvious test and it is
    wrong: it resurrects the demo every launch after the user deletes it, which is a
    peculiarly annoying way to disrespect a deletion (docs/17 §8a).
    """
    return _demo_seeded_path(data_dir).exists()


def mark_demo_seeded(data_dir: str | Path) -> None:
    """Record that seeding ran. Written *before* the run, not after.

    A run that crashes halfway still counts as seeded: retrying it on every launch would
    turn one broken demo into an endless supply of them.
    """
    _demo_seeded_path(data_dir).write_text(
        json.dumps({"seeded": True, "query": DEMO_QUERY}, indent=2), encoding="utf-8"
    )


def _custom_endpoint_path(data_dir: str | Path) -> Path:
    return Path(data_dir) / "custom_endpoint.json"


def stored_custom_endpoint(data_dir: str | Path) -> str | None:
    try:
        raw = json.loads(_custom_endpoint_path(data_dir).read_text(encoding="utf-8"))
        return raw.get("base_url")
    except FileNotFoundError:
        return None
    except Exception:
        return None


def save_custom_endpoint(data_dir: str | Path, url: str | None) -> None:
    path = _custom_endpoint_path(data_dir)
    if url is None:
        path.unlink(missing_ok=True)
        return
    path.write_text(json.dumps({"base_url": url}, indent=2), encoding="utf-8")


# ── Corpus mode (docs/12 M10) ─────────────────────────────────────────────────
#
# The airgapped switch lives in one JSON file next to routing.json. When on, every
# run's evidence comes ONLY from the installed corpus — no web search, no fetches —
# and the engine enforces that itself (retrievers.search delegates, read_webpage
# refuses). Persisted so the choice survives restarts, exactly like the routing.


def _corpus_config_path(data_dir: str | Path) -> Path:
    return Path(data_dir) / "corpus.json"


def corpus_only_enabled(data_dir: str | Path | None) -> bool:
    """Whether corpus-only mode is switched on. A corrupt file degrades to off."""
    if data_dir is None:
        return False
    try:
        raw = json.loads(_corpus_config_path(data_dir).read_text(encoding="utf-8"))
        return bool(raw.get("corpus_only"))
    except FileNotFoundError:
        return False
    except Exception:  # noqa: BLE001 — bad JSON must not sink launch
        return False


def save_corpus_config(data_dir: str | Path, *, corpus_only: bool) -> None:
    _corpus_config_path(data_dir).write_text(
        json.dumps({"corpus_only": corpus_only}, indent=2), encoding="utf-8"
    )


def make_corpus_store(data_dir: str | Path) -> CorpusStore:
    """The desktop's corpus: SQLite vectors + local embeddings via Ollama.

    `LocalEmbeddings` rather than the server's adapter because `app/adapters.py`
    imports `app.config` (and redis), neither of which belongs in the frozen bundle.
    Same `ollama:<model>` id scheme, so a corpus indexed on one host reads as the
    same model on the other.
    """
    embedder = LocalEmbeddings(
        model=os.environ.get("CORPUS_EMBEDDINGS_MODEL", "nomic-embed-text"),
        base_url=os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434/v1"),
    )
    return CorpusStore(Path(data_dir) / "corpus.sqlite", embedder)


def sidecar_run_config(
    *,
    fake: bool,
    demo: bool = False,
    data_dir: str | Path | None = None,
    session_routing: dict[str, str] | None = None,
) -> RunConfig:
    """The desktop's RunConfig: env keys merged with keychain keys (keychain wins).

    The desktop counterpart of `local.run_config_from_env` — same shape, but a user who
    pasted a key into the settings screen keeps working after a restart, because the
    keychain is consulted at every launch (docs/12 M9: keys in the OS keychain).

    `demo` selects the seeded session's content (docs/17 §6.1) and is meaningful only
    alongside `fake`; the server's counterpart is `pipeline_runner._run_config_for`.

    `session_routing` is this session's own already-validated per-run override, if the
    caller stored one — it wins over both the saved-routing file and `MODEL_*` env,
    mirroring the server's session → user → deployment resolution order. Resolved here
    (not just for the real branch) so a fake/demo run's `model_routing` snapshot also
    reflects the routing that *would* have been dialled, exactly as
    `pipeline_runner._run_config_for` passes `models=routing` into its own demo branch.
    """
    if not fake:
        # Real environment variables always win over the file (see `load_env_file`'s own
        # docstring) — but a fake run must still never touch a developer's real `.env`,
        # or a `--fake`/demo test process picks up real provider keys and MODEL_* values
        # it has no business reading, and other tests running after it in the same
        # process inherit the pollution (`os.environ` mutations outlive the test).
        load_env_file()

    if session_routing:
        models = dict(session_routing)
    else:
        models = {
            role: os.environ.get(f"MODEL_{role.upper()}", DEFAULT_MODELS[role]) for role in ROLES
        }
        if data_dir is not None:
            saved = stored_routing(data_dir)
            if saved:
                models.update(saved)  # the user's saved preference beats MODEL_* env

    if fake:
        return RunConfig(
            llm_mode="fake", demo=demo, corpus_mode=corpus_only_enabled(data_dir), models=models
        )

    env_names = {
        "google": "GOOGLE_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
        "openai": "OPENAI_API_KEY",
        "openrouter": "OPENROUTER_API_KEY",
        "custom": "CUSTOM_API_KEY",
    }
    keys = {p: os.environ[e] for p, e in env_names.items() if os.environ.get(e)}
    keys.update(stored_keys())

    if data_dir is not None:
        custom_base_url = stored_custom_endpoint(data_dir)
        if custom_base_url:
            keys["custom_base_url"] = custom_base_url

    if not keys:
        raise RuntimeError(
            "No provider key found. Paste one in Settings (stored in the OS keychain), "
            "or export e.g. GOOGLE_API_KEY before launching."
        )

    def _int_env(name: str, default: int) -> int:
        try:
            return int(os.environ.get(name) or default)
        except ValueError:
            return default

    def _float_env(name: str, default: float) -> float:
        try:
            return float(os.environ.get(name) or default)
        except ValueError:
            return default

    return RunConfig(
        llm_mode="real",
        models=models,
        provider_keys=keys,
        tavily_api_key=os.environ.get("TAVILY_API_KEY", ""),
        brave_api_key=os.environ.get("BRAVE_API_KEY", ""),
        corpus_mode=corpus_only_enabled(data_dir),
        enforce_ssrf_guards=False,
        max_critic_loops=_int_env("MAX_CRITIC_LOOPS", 2),
        max_cost_per_session_usd=_float_env("MAX_COST_PER_SESSION_USD", 0.50),
        max_wallclock_seconds=_int_env("MAX_WALLCLOCK_SECONDS", 600),
        max_parallel_tasks=_int_env("MAX_PARALLEL_TASKS", 4),
    )


# ── App factory ──────────────────────────────────────────────────────────────────


def create_sidecar_app(
    *,
    data_dir: str | Path,
    token: str | None = None,
    fake: bool = False,
) -> FastAPI:
    """Build the sidecar FastAPI app. `fake` forces scripted models (tests, demos)."""
    data_path = Path(data_dir)
    data_path.mkdir(parents=True, exist_ok=True)
    bearer = token or secrets.token_urlsafe(32)

    # The run routes below import their handlers from `app.api.v1.runs` rather than
    # restating them — one contract, one implementation — and that module reaches
    # `app.config` through `app.db.base`. `app/config.py` builds its `Settings` at import
    # time and requires `database_url` and `jwt_secret_key`: a *server* contract this host
    # has no use for, since auth here is the per-launch bearer token above and the database
    # is the SQLite file below. Absent those two names the import raises, so every run route
    # answers 500 on its first request while the server is perfectly healthy.
    #
    # That asymmetry is why it survived to a release build. A dev shell and CI both export
    # both variables (`tests/conftest.py` sets them via `setdefault`), so the whole suite —
    # `test_host_parity` included — exercises an environment no installed app ever has.
    # Route *registration* is identical across hosts here; only invocation diverged.
    #
    # `setdefault`, so a repo checkout already exporting a real DSN keeps it. The engine
    # `app.db.base` builds from this is never used on this host — the sidecar passes its
    # own session into every handler — but pointing it at the desktop's own database is
    # what makes an accidental future use read real rows instead of silently empty ones.
    os.environ.setdefault("DATABASE_URL", f"sqlite+aiosqlite:///{data_path / 'desktop.sqlite'}")
    # No JWT is ever minted here; this only has to exist, and must not be a shipped constant.
    os.environ.setdefault("JWT_SECRET_KEY", secrets.token_urlsafe(32))

    engine = create_async_engine(f"sqlite+aiosqlite:///{data_path / 'desktop.sqlite'}")

    @event.listens_for(engine.sync_engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _record) -> None:  # noqa: ANN001
        cursor = dbapi_conn.cursor()
        # WAL: the pipeline writes events while the API serves reads from one file.
        cursor.execute("PRAGMA journal_mode=WAL")
        # Foreign keys are OFF by default in SQLite; the cascade deletes the models
        # declare only mean anything with this on.
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    session_factory = async_sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False, autoflush=False
    )
    bus = SessionEventBus()
    state: dict = {
        "engine": engine,
        "db": session_factory,
        "bus": bus,
        "saver": None,
        "cache": None,
        "corpus": None,
        # The `ollama serve` process this app started, if any (docs/07 §2, Phase 2b).
        # Only ever populated by `/local/start` — a server the user started themselves
        # outside the app is never touched by `/local/stop`.
        "local_llm_process": None,
    }

    async def get_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as db:
            try:
                yield db
                await db.commit()
            except Exception:
                await db.rollback()
                raise

    async def get_local_user(db: AsyncSession = Depends(get_db)) -> User:
        user = (
            await db.execute(select(User).where(User.email == LOCAL_USER_EMAIL))
        ).scalar_one_or_none()
        if user is None:
            raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Local user missing")
        return user

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        # pgvector-backed tables cannot exist on SQLite; the corpus keeps its own store
        # (docs/12 M10). Everything else in the schema is dialect-portable
        # (app/models/types.py). The exclusion set lives in `app.models` rather than being
        # filtered by name here — this was a single inline name comparison, which is the
        # "two homes, one contract" shape that keeps biting: the domain tables added two more
        # pgvector-dependent tables and an inline filter would have silently tried to
        # create them.
        tables = [t for t in Base.metadata.sorted_tables if t.name not in POSTGRES_ONLY_TABLES]
        async with engine.begin() as conn:
            await conn.run_sync(
                lambda sync_conn: Base.metadata.create_all(sync_conn, tables=tables)
            )
            await conn.run_sync(lambda sync_conn: _add_missing_columns(sync_conn, tables))

        saver = AsyncSqliteSaver.from_conn_string(str(data_path / "checkpoints.sqlite"))
        state["saver"] = await saver.__aenter__()
        await state["saver"].setup()
        state["_saver_cm"] = saver
        state["cache"] = SqliteCache(data_path / "cache.sqlite")
        # The airgapped corpus (docs/12 M10). Creating the store only makes a SQLite
        # file — no network until something ingests or searches, and even then the
        # only call leaves for the local Ollama server.
        state["corpus"] = make_corpus_store(data_path)

        # Seed the single local user and their default project on first launch.
        async with session_factory() as db:
            user = (
                await db.execute(select(User).where(User.email == LOCAL_USER_EMAIL))
            ).scalar_one_or_none()
            if user is None:
                db.add(User(email=LOCAL_USER_EMAIL, hashed_pw="!", display_name="Local"))
                await db.commit()
            user = (
                await db.execute(select(User).where(User.email == LOCAL_USER_EMAIL))
            ).scalar_one()
            state["user_id"] = user.id
            general = (
                await db.execute(
                    select(Project)
                    .where(Project.user_id == user.id, Project.name == DEFAULT_PROJECT_NAME)
                    .limit(1)
                )
            ).scalar_one_or_none()
            if general is None:
                db.add(Project(user_id=user.id, name=DEFAULT_PROJECT_NAME))
                await db.commit()

        # First launch: leave a finished demo report waiting, so the app opens on what it
        # produces rather than an empty form and a request for an API key (docs/17 §6.1).
        # Generated rather than shipped pre-built: measured at 0.67s end to end, and a
        # generated one cannot drift from the pipeline the way a frozen fixture does.
        if not demo_already_seeded(data_path):
            try:
                # Marked before running, so a crash mid-run cannot produce a fresh broken
                # demo on every subsequent launch.
                mark_demo_seeded(data_path)
                async with session_factory() as db:
                    project = (
                        await db.execute(select(Project).where(Project.user_id == user.id).limit(1))
                    ).scalar_one()
                    seed = Session(
                        user_id=user.id,
                        project_id=project.id,
                        prompt=DEMO_QUERY,
                        status=SessionStatus.RUNNING,
                        research_depth="fast",
                        demo=True,
                    )
                    db.add(seed)
                    await db.commit()
                    await db.refresh(seed)
                # Not awaited: the window should paint immediately, and the run resolves
                # into the session list on its own.
                asyncio.create_task(_drive_session(seed.id, approved=None, feedback=None))
                logger.info("sidecar_demo_seeded", session_id=str(seed.id))
            except Exception as e:  # noqa: BLE001 — a missing demo must never block boot
                logger.warning("sidecar_demo_seed_failed", error=str(e))

        yield

        await state["_saver_cm"].__aexit__(None, None, None)
        await engine.dispose()

    app = FastAPI(title="Research Assistant Desktop Sidecar", lifespan=lifespan)
    app.state.sidecar = state
    app.state.data_dir = data_path
    app.state.fake = fake

    # ── Token middleware — the one security property this host adds (docs/13 §7) ──
    @app.middleware("http")
    async def require_token(request: Request, call_next):
        # SSE via native EventSource cannot set headers; the WebView passes the same
        # per-launch token as a query parameter there and nowhere else.
        supplied = None
        auth = request.headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            supplied = auth[7:]
        elif request.query_params.get("access_token"):
            supplied = request.query_params["access_token"]
        if not supplied or not hmac.compare_digest(supplied, bearer):
            return Response(
                content=json.dumps({"detail": "Not authenticated"}),
                status_code=401,
                media_type="application/json",
            )
        return await call_next(request)

    app.state.token = bearer

    # ── CORS — the WebView origin is not the sidecar origin (docs/13 §7) ─────────
    # The Tauri shell serves the static export from its own asset origin and calls
    # http://127.0.0.1:<port> cross-origin, so the browser needs CORS headers —
    # including on the preflight, which carries no token and must not be rejected
    # by the token middleware. Added after that middleware, so it wraps it and runs
    # first. The allow-list is the Tauri asset origins only; `allow_credentials`
    # stays off because the desktop authenticates with the bearer token, never
    # cookies.
    cors_origins = os.environ.get(
        "DESKTOP_CORS_ORIGINS", "tauri://localhost,http://tauri.localhost"
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in cors_origins.split(",") if o.strip()],
        allow_methods=["*"],
        allow_headers=["authorization", "content-type"],
    )

    # ── Routes ───────────────────────────────────────────────────────────────────
    api = APIRouter(prefix="/api/v1")

    @api.get("/auth/me")
    async def me(user: User = Depends(get_local_user)):
        # The frontend boots on this call. Desktop has exactly one user and no password:
        # returning the row keeps the existing UI code path working with no login screen.
        return {
            "id": str(user.id),
            "email": user.email,
            "display_name": user.display_name,
            "avatar_url": user.avatar_url,
            "created_at": user.created_at.isoformat() if user.created_at else None,
            "api_key_provider": None,
            "api_key_hint": None,
            "monthly_token_limit": 0,
            "preferences": user.preferences or {},
        }

    @api.get("/auth/me/usage", response_model=UsageResponse)
    async def get_usage(
        db: AsyncSession = Depends(get_db),
        user: User = Depends(get_local_user),
    ):
        """Token and cost usage. Second home of the server's `GET /auth/me/usage` (M1.5).

        Settings renders a usage panel unconditionally, so this 404'd on desktop (M1).

        Served rather than hidden, and that is the interesting call. The *limit* half of
        this endpoint is a multi-tenant abuse guard with no meaning for one local user
        paying their own provider bill — `monthly_token_limit` is 0 here and always will
        be, so `limit_remaining` is null and `limit_reached` is false. But the *usage*
        half is exactly as meaningful locally as it is on a server: this is the only place
        the product says what a month of research actually cost, and a BYOK user is the
        person most likely to want it.

        Hiding the panel behind `isDesktop` would have removed real information to close a
        contract gap, and added a branch to do it. `app.services.usage.summary` reads
        `sessions`, which this host has, so the same computation serves both.
        """
        return await usage.summary(db, user.id, user.monthly_token_limit)

    @api.patch("/auth/me")
    async def update_me(
        request: Request,
        db: AsyncSession = Depends(get_db),
        user: User = Depends(get_local_user),
    ):
        """Persist Settings preferences (docs/07 §2, Phase 3) — contract copy #3 of the
        server's `PATCH /auth/me`, merged rather than replaced for the same reason."""
        body = await request.json()
        if "display_name" in body:
            user.display_name = body["display_name"] or None
        if "avatar_url" in body:
            user.avatar_url = body["avatar_url"] or None
        if "preferences" in body and isinstance(body["preferences"], dict):
            merged = dict(user.preferences or {})
            merged.update(body["preferences"])
            user.preferences = merged
        await db.commit()
        await db.refresh(user)
        return {
            "id": str(user.id),
            "email": user.email,
            "display_name": user.display_name,
            "avatar_url": user.avatar_url,
            "created_at": user.created_at.isoformat() if user.created_at else None,
            "api_key_provider": None,
            "api_key_hint": None,
            "monthly_token_limit": 0,
            "preferences": user.preferences or {},
        }

    # -- projects -------------------------------------------------------------

    def _project_response(p: Project, count: int = 0) -> ProjectResponse:
        return ProjectResponse(
            id=p.id,
            name=p.name,
            description=p.description,
            archived_at=p.archived_at,
            created_at=p.created_at,
            session_count=count,
        )

    @api.get("/projects", response_model=ProjectListResponse)
    async def list_projects(
        archived: bool = False,
        db: AsyncSession = Depends(get_db),
        user: User = Depends(get_local_user),
    ):
        rows = (
            (
                await db.execute(
                    select(Project).where(
                        Project.user_id == user.id,
                        Project.archived_at.is_not(None)
                        if archived
                        else Project.archived_at.is_(None),
                    )
                )
            )
            .scalars()
            .all()
        )
        ids = [p.id for p in rows]
        counts: dict = {}
        if ids:
            count_rows = await db.execute(
                select(Session.project_id, func.count())
                .where(Session.project_id.in_(ids))
                .group_by(Session.project_id)
            )
            counts = {pid: n for pid, n in count_rows.all()}
        return ProjectListResponse(
            projects=[_project_response(p, counts.get(p.id, 0)) for p in rows], total=len(rows)
        )

    @api.post("/projects", response_model=ProjectResponse, status_code=201)
    async def create_project(
        payload: ProjectCreateRequest,
        db: AsyncSession = Depends(get_db),
        user: User = Depends(get_local_user),
    ):
        project = Project(user_id=user.id, name=payload.name, description=payload.description)
        db.add(project)
        try:
            await db.commit()
        except IntegrityError:
            # Same answer the server gives, for the same reason: the unique index is
            # case-insensitive, so a duplicate is only reliably detectable here. Without
            # this the desktop ProjectSwitcher answered an ordinary retyped name with a
            # 500 from an unhandled IntegrityError while the server explained itself.
            await db.rollback()
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail=f"You already have a project named '{payload.name}'.",
            ) from None
        await db.refresh(project)
        return _project_response(project)

    async def _resolve_project(
        db: AsyncSession, user_id: uuid.UUID, project_id: uuid.UUID | None
    ) -> Project:
        if project_id is None:
            project = (
                await db.execute(
                    select(Project)
                    .where(Project.user_id == user_id, Project.name == DEFAULT_PROJECT_NAME)
                    .limit(1)
                )
            ).scalar_one_or_none()
            if project is None:  # pragma: no cover — seeded at startup
                project = Project(user_id=user_id, name=DEFAULT_PROJECT_NAME)
                db.add(project)
                await db.commit()
                await db.refresh(project)
            return project
        project = (
            await db.execute(
                select(Project).where(Project.id == project_id, Project.user_id == user_id)
            )
        ).scalar_one_or_none()
        if project is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Project not found.")
        return project

    @api.patch("/projects/{project_id}", response_model=ProjectResponse)
    async def update_project(
        project_id: uuid.UUID,
        payload: ProjectUpdateRequest,
        db: AsyncSession = Depends(get_db),
        user: User = Depends(get_local_user),
    ):
        """Rename, re-describe, or archive/unarchive a project — the server's route
        (app/api/v1/projects.py), same validation and same 409 on a duplicate name.

        This route did not exist for a whole release; `INTENTIONAL_SERVER_ONLY` in
        test_host_parity.py justified the gap as "the UI never calls it" — true only
        as long as no shared component did. `ProjectsSection.tsx` now does, on both
        hosts, which is what makes the justification stop being true and this route
        required rather than optional.
        """
        project = await _resolve_project(db, user.id, project_id)
        if payload.name is not None:
            project.name = payload.name
        if payload.description is not None:
            project.description = payload.description
        if payload.archived is not None:
            project.archived_at = datetime.now(UTC) if payload.archived else None
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
            raise HTTPException(
                status.HTTP_409_CONFLICT, detail="You already have a project with that name."
            ) from None
        await db.refresh(project)
        count = (
            await db.execute(
                select(func.count()).select_from(Session).where(Session.project_id == project.id)
            )
        ).scalar_one()
        return _project_response(project, count)

    @api.delete("/projects/{project_id}", status_code=204)
    async def delete_project(
        project_id: uuid.UUID,
        db: AsyncSession = Depends(get_db),
        user: User = Depends(get_local_user),
    ):
        """Delete a project and every session in it — same refusal-while-running rule
        and same checkpoint cleanup as the server route.

        Deliberately does NOT touch a corpus file: desktop's corpus is one flat
        `corpus.sqlite` for the whole app (`make_corpus_store`), not one file per
        project like the server's `corpus_<project_id>.sqlite` — a real, documented
        infra difference (AGENTS.md), not a gap. There is nothing project-scoped on
        disk here to orphan.
        """
        project = await _resolve_project(db, user.id, project_id)
        running = (
            await db.execute(
                select(func.count())
                .select_from(Session)
                .where(Session.project_id == project.id, Session.status == SessionStatus.RUNNING)
            )
        ).scalar_one()
        if running:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail=f"{running} session(s) in this project are still running.",
            )
        session_ids = (
            (await db.execute(select(Session.id).where(Session.project_id == project.id)))
            .scalars()
            .all()
        )
        await db.delete(project)  # sessions (and their logs/chat/audit) cascade
        await db.commit()
        for sid in session_ids:
            try:
                await app.state.sidecar["saver"].adelete_thread(str(sid))
            except Exception as e:  # noqa: BLE001 — the rows are gone; log and move on
                logger.warning("checkpoint_cleanup_failed", session_id=str(sid), error=str(e))
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    # -- research sessions ------------------------------------------------------

    async def _authorized_session(
        db: AsyncSession, session_id: uuid.UUID, user_id: uuid.UUID
    ) -> Session:
        session = (
            await db.execute(
                select(Session).where(Session.id == session_id, Session.user_id == user_id)
            )
        ).scalar_one_or_none()
        if session is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Session not found.")
        return session

    async def _apply_outcome(db: AsyncSession, session: Session, outcome: RunOutcome) -> None:
        """Map a runner outcome onto the session row, then emit the lifecycle event.

        Order matches the server: commit the row BEFORE the terminal event leaves, so a
        client that receives COMPLETED and re-fetches never sees a stale status.
        """
        # A run the user stopped stays stopped (issue #54). Second home of the guard in
        # `pipeline_runner._persist_outcome`; `run_execution.persist_outcome` is the third.
        # Cancellation is advisory on both hosts — nothing interrupts the asyncio.Task any
        # more than it interrupts the Celery task — so the outcome still arrives, and
        # without this it would move the session back out of its terminal state minutes
        # after the user was told it had stopped.
        #
        # Spend is still recorded, for the same reason as on the server: tokens burned
        # between the stop and the pipeline noticing are real, and dropping them would make
        # usage totals lie. No lifecycle event is emitted — `cancel_session` already
        # published FAILED, and a second terminal event on a closed stream says nothing.
        if session.is_cancelled:
            session.total_cost_usd = outcome.cost_usd
            session.total_tokens_input = outcome.tokens_input
            session.total_tokens_output = outcome.tokens_output
            session.rework_count = outcome.rework_count
            await db.commit()
            return

        # Second home of the server's `pipeline_runner._persist_outcome` mapping — both
        # dict literals below have to grow every status the runner can return, or a new
        # outcome raises KeyError inside a background task and the session sits on
        # RUNNING forever with nothing in the log to say why.
        session.status = {
            "awaiting_plan": SessionStatus.AWAITING_PLAN,
            "awaiting_approval": SessionStatus.AWAITING_APPROVAL,
            "completed": SessionStatus.COMPLETED,
            "failed": SessionStatus.FAILED,
        }[outcome.status]
        if outcome.status == "awaiting_plan":
            # The proposal the reviewer is about to edit. `plan_approved_at` stays null
            # until they decide — see `submit_plan` below.
            session.plan_json = {"tasks": outcome.plan_tasks}
            session.outline_json = {"sections": outcome.plan_outline}
        if outcome.draft_report:
            session.draft_report = outcome.draft_report
        if outcome.final_report:
            session.final_report = outcome.final_report
        session.sources = outcome.sources
        session.total_cost_usd = outcome.cost_usd
        session.total_tokens_input = outcome.tokens_input
        session.total_tokens_output = outcome.tokens_output
        session.rework_count = outcome.rework_count
        session.elapsed_seconds = outcome.elapsed_seconds
        session.error_message = outcome.error
        if outcome.status == "completed":
            # Second home of `pipeline_runner._persist_outcome`'s line. Computed at the
            # moment the report becomes final, never per list request.
            session.citation_resolution_rate = citation_rate.resolution_rate(
                outcome.final_report or "", outcome.sources
            )
        await db.commit()

        if outcome.status == "completed":
            # Desktop's session counterpart to `pipeline_runner._ingest_report_into_corpus`.
            # There is no desktop project-memory ingestion to mirror alongside it (project
            # memory is pgvector-only — AGENTS.md), but the corpus is plain SQLite and has
            # no such constraint, so this is not skipped the way memory is.
            from app.services.report_corpus import ingest_report

            await ingest_report(
                make_corpus_store(app.state.data_dir),
                session_id=str(session.id),
                report_markdown=outcome.final_report,
            )

        lifecycle = {
            "awaiting_plan": "PLAN_READY",
            "awaiting_approval": "HITL_READY",
            "completed": "COMPLETED",
            "failed": "FAILED",
        }[outcome.status]
        bus = app.state.sidecar["bus"]
        payload = make_event(lifecycle, message=outcome.error)
        eid = bus.append(str(session.id), payload)
        payload["id"] = eid
        async with session_factory() as log_db:
            log_db.add(
                AgentLog(
                    session_id=session.id, event_type=lifecycle, agent_name=None, payload=payload
                )
            )
            await log_db.commit()

    async def _drive_session(
        session_id: uuid.UUID,
        *,
        approved: bool | None = None,
        feedback: str | None = None,
        plan: dict | None = None,
    ) -> None:
        """Run or resume one session in-process — the desktop's Celery replacement.

        Three dispatches, matching `research_engine.runner`: no decision at all is a
        fresh run, `approved` resumes the draft gate, `plan` resumes the design gate.
        """
        sidecar = app.state.sidecar
        sink = PersistingSink(sidecar["bus"], session_factory)

        # Per-session demo, not just the process-wide `--fake` flag (docs/17 §6.2). The
        # desktop is single-process, so without this a user who ticks "demo run" while the
        # app is configured with a real key would spend that key — and get a report stamped
        # as a demo, which is the worst of both.
        async with session_factory() as db:
            session = await _authorized_session(db, session_id, sidecar["user_id"])
            # Third home of the server's rule (`pipeline_runner._run_config_for`, and
            # `run_execution.run_config_for_run` for runs): a run whose models are scripted is
            # *recorded* as a demo run, whichever way it got there. `app.state.fake` is the
            # whole-process `--fake` flag, and a run under it used to persist `demo = false`
            # — so its bundle named models nothing had called and its `.md` export skipped
            # the demo stamp. The row follows what actually ran, not what was requested.
            is_demo = bool(session.demo) or bool(app.state.fake)
            if is_demo and not session.demo:
                session.demo = True
                await db.commit()
            session_routing = session.model_routing
            # The research design gate (docs/07 §2, Phase 4). Read from the session row,
            # not from the request, because this runs again on every resume and the
            # request is long gone by then. Server counterpart:
            # `pipeline_runner._run_config_for`.
            plan_gate_overrides = {
                "skip_plan_gate": bool(session.skip_plan_gate),
                "topic_seeds": tuple(session.topic_seeds or ()),
                "outline_template": session.outline_template,
            }
            local_user = await db.get(User, sidecar["user_id"])
            # Same mapping as the server's `pipeline_runner._preference_overrides`
            # (docs/07 §2, Phase 3) — third home of this contract.
            prefs = (local_user.preferences if local_user else None) or {}
            preference_overrides = {
                k: prefs[k]
                for k in (
                    "retrieval_k",
                    "min_sources_per_task",
                    "snippet_max_chars",
                    "tavily_api_key",
                    "brave_api_key",
                )
                if prefs.get(k) is not None
            }

        try:
            config = sidecar_run_config(
                fake=app.state.fake or is_demo,
                demo=is_demo,
                data_dir=app.state.data_dir,
                session_routing=session_routing,
            )
            # Applied after construction rather than inside `sidecar_run_config`, which
            # has two `RunConfig(...)` sites (fake and real) — adding a field to only one
            # of them is precisely how the fake path and the real path drift.
            config = replace(config, **plan_gate_overrides)
            if preference_overrides:
                config = replace(config, **preference_overrides)
        except RuntimeError as e:
            async with session_factory() as db:
                session = await _authorized_session(db, session_id, sidecar["user_id"])
                session.status = SessionStatus.FAILED
                session.error_message = str(e)[:500]
                await db.commit()
            payload = make_event("FAILED", message=str(e))
            payload["id"] = sidecar["bus"].append(str(session_id), payload)
            return

        # Snapshot exactly what this run is about to dial — mirrors the server's
        # `pipeline_runner._run_config_for`, which resolves-then-persists before the
        # graph starts. Without this, `SessionDetail.model_routing` (and every export's
        # "models used" table) stayed null on every desktop session forever, even though
        # a real routing decision had just been made two lines above.
        if session.model_routing != config.models:
            async with session_factory() as db:
                session = await _authorized_session(db, session_id, sidecar["user_id"])
                session.model_routing = dict(config.models)
                await db.commit()

        ports = {
            "event_sink": sink,
            "cache": sidecar["cache"],
            "run_config": config,
            "corpus": sidecar["corpus"],
        }
        try:
            if approved is None and plan is None:
                async with session_factory() as db:
                    session = await _authorized_session(db, session_id, sidecar["user_id"])
                    query, depth = session.prompt, session.research_depth
                outcome = await run(
                    checkpointer=sidecar["saver"],
                    session_id=str(session_id),
                    user_id="local",
                    query=query,
                    depth=depth,
                    **ports,
                )
            elif plan is not None:
                outcome = await resume(
                    checkpointer=sidecar["saver"],
                    session_id=str(session_id),
                    plan=plan,
                    **ports,
                )
            else:
                outcome = await resume(
                    checkpointer=sidecar["saver"],
                    session_id=str(session_id),
                    approved=approved,
                    feedback=feedback,
                    **ports,
                )
        except Exception as e:  # noqa: BLE001 — a crashed run must surface as FAILED
            logger.exception("sidecar_run_crashed", session_id=str(session_id))
            outcome = RunOutcome(status="failed", error=str(e)[:500])

        async with session_factory() as db:
            session = await _authorized_session(db, session_id, sidecar["user_id"])
            await _apply_outcome(db, session, outcome)

    # ── Research runs, driven in this process ─────────────────────────────────────
    #
    # The desktop's answer to `app/run_execution.py::execute_run`, which is server-only:
    # it takes a Redis lock, opens the server engine and checkpoints to Postgres, none of
    # which exist here. Everything *above* that function in `run_execution` is host-free and
    # is imported rather than restated — `persist_outcome` writes the domain rows and
    # `lifecycle_event` names the terminal event, so a desktop run and a server run cannot
    # record different things about the same outcome.
    #
    # Only the mechanism differs: an asyncio task instead of a Celery message, this host's
    # SQLite saver instead of the Postgres one, and the desktop's own `RunConfig` builder
    # instead of the server settings. Same shape as `_drive_session` above, which is the
    # long-standing precedent for exactly this substitution.

    #: Guards against two drivers on one run. Celery can redeliver a message, which is why
    #: the server takes a Redis lock; a single-process host cannot, but a user double-
    #: clicking Approve can still land two coroutines on one run, and the second would
    #: resume a graph the first is already advancing.
    _runs_in_flight: set[str] = set()

    async def _drive_run(
        run_id: uuid.UUID,
        *,
        resume: tuple[bool, str | None] | None = None,
        plan: dict | None = None,
    ) -> None:
        """Run or resume one research run in-process — the desktop's worker."""
        from app import run_execution, run_lifecycle
        from app.models.research import ResearchRun

        key = str(run_id)
        if key in _runs_in_flight:
            logger.warning("sidecar_run_already_in_flight", run_id=key)
            return
        _runs_in_flight.add(key)
        try:
            sidecar = app.state.sidecar
            sink = PersistingSink(sidecar["bus"], session_factory)

            async with session_factory() as db:
                run = await db.get(ResearchRun, run_id)
                if run is None or run.owner_id != sidecar["user_id"]:
                    logger.error("sidecar_run_not_found", run_id=key)
                    return
                # "No new research will be started for this run" has to stay true across a
                # resume dispatched after a cancel; the server guards the same way, and
                # without it the status write violates `ck_run_cancelled`.
                if run.status == "CANCELLED":
                    logger.info("sidecar_run_start_skipped_cancelled", run_id=key)
                    return

                # Fourth home of "the row records what actually ran, not what was
                # requested" (AGENTS.md): `pipeline_runner._run_config_for`,
                # `run_execution.run_config_for_run`, `sidecar._drive_session`, and here.
                # A run under the process-wide `--fake` flag must persist `demo = true`, or
                # its bundle names models nothing called and its export skips the stamp.
                is_demo = bool(run.demo) or bool(app.state.fake)
                if is_demo and not run.demo:
                    run.demo = True
                overrides = {
                    "skip_plan_gate": bool(run.skip_plan_gate),
                    "topic_seeds": tuple(run.topic_seeds or ()),
                    "outline_template": run.outline_template,
                }
                question, depth = run.question, run.depth
                run_routing = run.model_routing
                await run_lifecycle.set_status(db, run, "RUNNING")
                await db.commit()

            try:
                config = sidecar_run_config(
                    fake=app.state.fake or is_demo,
                    demo=is_demo,
                    data_dir=app.state.data_dir,
                    session_routing=run_routing,
                )
                config = replace(config, **overrides)
            except RuntimeError as e:
                async with session_factory() as db:
                    run = await db.get(ResearchRun, run_id)
                    await run_lifecycle.record_failure(db, run, str(e)[:500])
                    await db.commit()
                await sink(key, make_event("FAILED", message=str(e)))
                return

            # Snapshot what this run actually dialled, before the graph starts — the same
            # reason `_drive_session` does it: without it every desktop run's bundle
            # reports a null routing for a decision that was really made.
            if run_routing != config.models:
                async with session_factory() as db:
                    run = await db.get(ResearchRun, run_id)
                    run.model_routing = dict(config.models)
                    await db.commit()

            ports = {
                "event_sink": sink,
                "cache": sidecar["cache"],
                "run_config": config,
                "corpus": sidecar["corpus"],
            }
            try:
                if plan is not None:
                    outcome = await resume_run(
                        checkpointer=sidecar["saver"], session_id=key, plan=plan, **ports
                    )
                elif resume is None:
                    outcome = await run_pipeline(
                        checkpointer=sidecar["saver"],
                        session_id=key,
                        user_id="local",
                        query=question,
                        depth=depth,
                        **ports,
                    )
                else:
                    approved, feedback = resume
                    outcome = await resume_run(
                        checkpointer=sidecar["saver"],
                        session_id=key,
                        approved=approved,
                        feedback=feedback,
                        **ports,
                    )
            except Exception as e:  # noqa: BLE001 — a crashed run must surface as FAILED
                logger.exception("sidecar_v2_run_crashed", run_id=key)
                outcome = RunOutcome(status="failed", error=str(e)[:500])

            async with session_factory() as db:
                run = await db.get(ResearchRun, run_id)
                result = await run_execution.persist_outcome(
                    db, run, outcome, saver=sidecar["saver"]
                )
                # Persist, commit, then publish — a client acting on COMPLETED must never
                # re-read a status that has not caught up.
                await db.commit()
            await sink(key, run_execution.lifecycle_event(result))
        finally:
            _runs_in_flight.discard(key)

    class _SidecarDispatcher:
        """`RunDispatcher` for this host: an asyncio task instead of a broker message.

        The handlers in `app/api/v1/runs.py` are shared verbatim; only this is swapped,
        so the ordering rules they encode — commit before dispatch, RUNNING in the same
        transaction as the decision — hold identically on both hosts.
        """

        async def start(self, run_id: str, user_id: str) -> None:
            asyncio.create_task(_drive_run(uuid.UUID(run_id)))

        async def resume_plan(self, run_id: str, user_id: str, plan: dict) -> None:
            asyncio.create_task(_drive_run(uuid.UUID(run_id), plan=plan))

        async def rework(self, run_id: str, user_id: str, feedback: str | None) -> None:
            asyncio.create_task(_drive_run(uuid.UUID(run_id), resume=(False, feedback)))

    _dispatcher = _SidecarDispatcher()

    @api.post("/research", response_model=ResearchStartResponse, status_code=202)
    async def start_research(
        payload: ResearchStartRequest,
        db: AsyncSession = Depends(get_db),
        user: User = Depends(get_local_user),
    ):
        # Per-run model choice, validated here so an unroutable model is rejected before
        # a session exists — same contract as the server (`app/api/v1/research.py`).
        # None means "use my saved settings"; `start_research` previously accepted this
        # field and then never read it again, so a request that did NOT omit it still
        # ran on the saved settings — the same "accepted by the schema, dropped on the
        # floor" bug `corpus_mode`/`demo` document just below.
        routing = None
        if payload.model_routing:
            try:
                routing = validate_routing(payload.model_routing)
            except ValueError as e:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)) from e

        project = await _resolve_project(db, user.id, payload.project_id)
        session = Session(
            user_id=user.id,
            project_id=project.id,
            prompt=payload.query,
            status=SessionStatus.PENDING,
            research_depth=payload.depth,
            model_routing=routing,
            # Both were accepted by the request schema and then dropped, exactly as they
            # were on the server path: the session silently took the column default, so
            # "restrict to corpus" ran an ordinary search and a demo run produced an
            # unstamped report indistinguishable from real research.
            corpus_mode=payload.corpus_mode,
            demo=payload.demo,
            # Research design gate (docs/07 §2, Phase 4). Third home of the
            # request→`Session(...)` contract, and the one AGENTS.md records as having
            # been wrong all three times; server counterpart is `api/v1/research.py`.
            skip_plan_gate=payload.skip_plan_gate,
            topic_seeds=payload.topic_seeds or None,
            outline_template=payload.outline_template,
        )
        db.add(session)
        await db.commit()
        await db.refresh(session)
        session.status = SessionStatus.RUNNING
        await db.commit()
        asyncio.create_task(_drive_session(session.id, approved=None, feedback=None))
        logger.info("sidecar_research_started", session_id=str(session.id))
        return ResearchStartResponse(session_id=session.id, status=session.status)

    @api.get("/research", response_model=SessionListResponse)
    async def list_sessions(
        page: int = 1,
        limit: int = 20,
        archived: bool = False,
        project_id: uuid.UUID | None = None,
        db: AsyncSession = Depends(get_db),
        user: User = Depends(get_local_user),
    ):
        limit = max(1, min(limit, 100))
        filters = [
            Session.user_id == user.id,
            Session.archived_at.is_not(None) if archived else Session.archived_at.is_(None),
        ]
        if project_id is not None:
            filters.append(Session.project_id == project_id)
        base = select(Session).where(*filters)
        total = (await db.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
        rows = (
            (
                await db.execute(
                    base.order_by(Session.created_at.desc()).offset((page - 1) * limit).limit(limit)
                )
            )
            .scalars()
            .all()
        )
        return SessionListResponse(
            sessions=[SessionSummary.model_validate(s) for s in rows],
            total=total,
            page=page,
            limit=limit,
        )

    @api.get("/research/{session_id}", response_model=SessionDetail)
    async def get_session(
        session_id: uuid.UUID,
        db: AsyncSession = Depends(get_db),
        user: User = Depends(get_local_user),
    ):
        session = await _authorized_session(db, session_id, user.id)
        return SessionDetail.model_validate(session)

    @api.get("/research/{session_id}/stream")
    async def stream_events(
        session_id: uuid.UUID,
        request: Request,
        db: AsyncSession = Depends(get_db),
        user: User = Depends(get_local_user),
    ):
        session = await _authorized_session(db, session_id, user.id)
        sidecar = app.state.sidecar
        bus: SessionEventBus = sidecar["bus"]

        last_event_id = request.headers.get("last-event-id")
        after_id = int(last_event_id) if last_event_id and last_event_id.isdigit() else 0

        # Snapshot the durable backlog (fresh session: the request-scoped one closes
        # when streaming starts). Subscribing first, like the server, loses nothing.
        async with session_factory() as sdb:
            backlog = [
                (row.id, row.payload)
                for row in (
                    await sdb.execute(
                        select(AgentLog)
                        .where(AgentLog.session_id == session_id, AgentLog.id > after_id)
                        .order_by(AgentLog.id.asc())
                    )
                )
                .scalars()
                .all()
            ]

        # A session that already reached a terminal state needs no live tail — the
        # backlog IS the stream. (The server has the same implicit behavior; here it
        # is spelled out because the in-process bus only holds this launch's events.)
        # Terminal *or* parked at a gate: in both cases nothing more will be published
        # until a human acts, so the stream ends after the backlog instead of tailing.
        # The gates moved here from the replay stop-list — stopping replay at a gate also
        # hid every event after it (see `_REPLAY_STOP_EVENTS`), which is a different and
        # wrong statement. Second home of `runs_api._SUSPENDED_STATUSES`.
        already_done = session.status in (
            SessionStatus.COMPLETED,
            SessionStatus.FAILED,
            SessionStatus.AWAITING_PLAN,
            SessionStatus.AWAITING_APPROVAL,
        )

        async def gen() -> AsyncGenerator[str, None]:
            yield f"data: {json.dumps({'type': 'connected'})}\n\n"
            seen_max = after_id
            for eid, payload in backlog:
                seen_max = max(seen_max, eid or 0)
                yield f"id: {eid}\ndata: {json.dumps(payload)}\n\n"
                if payload.get("type") in _REPLAY_STOP_EVENTS:
                    return
            if already_done:
                return
            async with bus.subscribe(str(session_id)) as queue:
                while True:
                    eid, payload = await queue.get()
                    if eid <= seen_max:
                        continue  # already replayed from the backlog
                    yield f"id: {eid}\ndata: {json.dumps(payload)}\n\n"
                    seen_max = eid
                    if payload.get("type") in _TERMINAL_EVENTS:
                        return

        return StreamingResponse(gen(), media_type="text/event-stream", headers=SSE_HEADERS)

    # ── Research design gate (docs/07 §2, Phase 4) ─────────────────────────────
    # Second home of `app/api/v1/research.py`'s plan endpoints. The bodies differ only
    # in how they dispatch — Celery there, an asyncio task here — because that is the
    # only thing that actually differs between the hosts; every rule below (404 vs empty
    # plan, the 409, "None means unedited", writing the decision before resuming) is the
    # shared contract and has to move in both files at once.

    def _plan_response(session: Session) -> PlanResponse:
        plan = session.plan_json or {}
        outline = session.outline_json or {}
        return PlanResponse(
            session_id=session.id,
            status=session.status,
            tasks=[PlanTaskSchema.model_validate(t) for t in (plan.get("tasks") or [])],
            outline=[
                OutlineSectionSchema.model_validate(s) for s in (outline.get("sections") or [])
            ],
            approved_at=session.plan_approved_at,
        )

    @api.get("/research/outline-templates", response_model=list[OutlineTemplateSchema])
    async def list_outline_templates(user: User = Depends(get_local_user)):
        # Declared before `/research/{session_id}`, whose path parameter is a UUID and
        # would 422 this path rather than fall through to it.
        return [OutlineTemplateSchema.model_validate(t) for t in outlines.catalog()]

    @api.get("/research/{session_id}/plan", response_model=PlanResponse)
    async def get_plan(
        session_id: uuid.UUID,
        db: AsyncSession = Depends(get_db),
        user: User = Depends(get_local_user),
    ):
        session = await _authorized_session(db, session_id, user.id)
        if session.plan_json is None:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND,
                detail=(
                    "This session has no research plan to review — it did not use the design gate."
                ),
            )
        return _plan_response(session)

    @api.post("/research/{session_id}/plan", response_model=PlanResponse)
    async def submit_plan(
        session_id: uuid.UUID,
        payload: PlanDecisionRequest,
        db: AsyncSession = Depends(get_db),
        user: User = Depends(get_local_user),
    ):
        session = await _authorized_session(db, session_id, user.id)
        if session.status != SessionStatus.AWAITING_PLAN:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail=f"Session must be AWAITING_PLAN (currently {session.status}).",
            )

        proposed = (session.plan_json or {}).get("tasks") or []
        tasks = [t.model_dump() for t in payload.tasks] if payload.tasks is not None else proposed
        outline = (
            [s.model_dump() for s in payload.outline]
            if payload.outline is not None
            else (session.outline_json or {}).get("sections") or []
        )
        kept = [t for t in tasks if t.get("include", True)]
        if not kept:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Keep at least one task — a plan with nothing in it researches nothing.",
            )

        session.plan_json = {"tasks": kept}
        session.outline_json = {"sections": outline}
        session.plan_approved_at = datetime.now(UTC)
        # Second home of `app/api/v1/research.py::submit_plan`'s audit row, and hashed the
        # same way, so the bundle's approval chain carries the design decision on this host
        # too. The sidecar recorded neither gate's decision until M0C — the table existed
        # (create_all builds it from `app.models`) and stayed empty.
        db.add(
            AuditLog(
                session_id=session.id,
                user_id=user.id,
                action="plan_approved",
                feedback=None,
                draft_hash=hashlib.sha256(
                    json.dumps({"tasks": kept, "outline": outline}, sort_keys=True).encode("utf-8")
                ).hexdigest(),
            )
        )
        session.status = SessionStatus.RUNNING
        await db.commit()
        await db.refresh(session)

        asyncio.create_task(_drive_session(session_id, plan={"tasks": kept, "outline": outline}))
        logger.info("sidecar_plan_approved", session_id=str(session_id), task_count=len(kept))
        return _plan_response(session)

    @api.post("/research/{session_id}/approve")
    async def approve_or_rework(
        session_id: uuid.UUID,
        payload: ApprovalRequest,
        db: AsyncSession = Depends(get_db),
        user: User = Depends(get_local_user),
    ):
        session = await _authorized_session(db, session_id, user.id)
        if session.status != SessionStatus.AWAITING_APPROVAL:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail=f"Session must be AWAITING_APPROVAL (currently {session.status}).",
            )
        if not payload.approved and session.rework_count >= 3:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail="Rework limit reached. Approve or abandon this session.",
            )
        # The load-bearing half of the bundle's approval chain, and the reason a desktop
        # bundle can be verified at all: `verify_bundle._check_approval_chain` fails a
        # bundle whose chain is empty ("this report was never human-reviewed"), and fails
        # again unless an `approved` entry's `draft_hash` equals the report hash.
        #
        # Hashed over `draft_report` exactly as the server does, which links because
        # `finalizer_node` sets `final_report = draft_report` — so the text a human
        # approved and the text the bundle carries are the same bytes.
        #
        # Written before the run is resumed, matching the server: a human's decision is
        # evidence, and evidence is recorded when it is made, not after the work it
        # authorises has succeeded.
        db.add(
            AuditLog(
                session_id=session.id,
                user_id=user.id,
                action="approved" if payload.approved else "rework_requested",
                feedback=None if payload.approved else payload.feedback,
                draft_hash=hashlib.sha256((session.draft_report or "").encode("utf-8")).hexdigest(),
            )
        )
        session.status = SessionStatus.RUNNING
        session.rework_count = session.rework_count + (0 if payload.approved else 1)
        await db.commit()
        asyncio.create_task(
            _drive_session(session_id, approved=payload.approved, feedback=payload.feedback)
        )
        return {"message": "Approved. Finalizing." if payload.approved else "Rework requested."}

    # ── Follow-up chat (docs/07 §2, Phase 5) ───────────────────────────────────
    # Second home of `app/api/v1/chat.py`. The sidecar had none of this, while the
    # desktop build rendered `ChatPanel.tsx` and POSTed to it — a shipped control that
    # 404'd. Three things differ from the server and nothing else should:
    #   * keys come from the OS keychain, not a `crypto.decrypt` of a DB column;
    #   * no rate-limit dependency — `enforce_chat_rate_limit` needs `get_current_user`
    #     and Redis, and this host is one local user with neither;
    #   * the corpus is a single `corpus.sqlite` for the whole app, already built at
    #     boot, rather than one file per project. Reuse it; do not rebuild a path.

    @api.get("/research/{session_id}/chat", response_model=list[ChatMessageSchema])
    async def chat_history(
        session_id: uuid.UUID,
        db: AsyncSession = Depends(get_db),
        user: User = Depends(get_local_user),
    ):
        await _authorized_session(db, session_id, user.id)
        rows = (
            (
                await db.execute(
                    select(ChatMessage)
                    .where(ChatMessage.session_id == session_id)
                    .order_by(ChatMessage.created_at.asc())
                )
            )
            .scalars()
            .all()
        )
        return rows

    @api.post("/research/{session_id}/chat")
    async def send_chat_message(
        session_id: uuid.UUID,
        payload: ChatRequest,
        db: AsyncSession = Depends(get_db),
        user: User = Depends(get_local_user),
    ):
        session = await _authorized_session(db, session_id, user.id)
        if session.status != SessionStatus.COMPLETED:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                detail="Chat is available only for completed sessions.",
            )

        db.add(ChatMessage(session_id=session_id, role="user", content=payload.message))
        await db.commit()

        history = (
            (
                await db.execute(
                    select(ChatMessage)
                    .where(ChatMessage.session_id == session_id)
                    .order_by(ChatMessage.created_at.asc())
                    .limit(20)
                )
            )
            .scalars()
            .all()
        )

        try:
            grounding = await chat_scope.gather(
                payload.scope,
                query=payload.message,
                report=session.final_report,
                report_sources=session.sources or [],
                memory_excerpts=None,
                # One store for the whole app (`make_corpus_store`), unlike the server's
                # per-project file — the reason this is a lambda over existing state
                # rather than a path built from `session.project_id`.
                store_factory=lambda: app.state.sidecar["corpus"],
            )
        except EmbeddingsUnavailable as e:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(e)) from e

        system = (
            f"{prompts.CHAT_PROMPT}\n\n"
            f"{chat_scope.system_suffix(grounding)}\n\n"
            f"<untrusted_web_content>\n{grounding.text}\n</untrusted_web_content>"
        )
        messages: list = [SystemMessage(content=system)]
        for m in history:
            messages.append(
                HumanMessage(content=m.content)
                if m.role == "user"
                else AIMessage(content=m.content)
            )

        config = sidecar_run_config(
            fake=app.state.fake, data_dir=app.state.data_dir, session_routing=session.model_routing
        )

        async def gen() -> AsyncGenerator[str, None]:
            cfg_token = set_run_config(config)
            acc = ""
            try:
                llm = get_llm("chat")  # raises with an actionable message if no key
                yield (
                    "data: "
                    + json.dumps(
                        {
                            "type": "connected",
                            "scope": grounding.scope,
                            "sources": grounding.sources,
                            "notes": grounding.notes,
                        }
                    )
                    + "\n\n"
                )
                async for chunk in llm.astream(messages):
                    text = text_of(chunk)
                    if text:
                        acc += text
                        yield f"data: {json.dumps({'type': 'chunk', 'text': text})}\n\n"
                async with session_factory() as wdb:
                    msg = ChatMessage(session_id=session_id, role="assistant", content=acc)
                    wdb.add(msg)
                    await wdb.commit()
                    await wdb.refresh(msg)
                    message_id = str(msg.id)
                yield f"data: {json.dumps({'type': 'done', 'message_id': message_id})}\n\n"
            except Exception as e:  # noqa: BLE001 — surfaced to the client, never swallowed
                logger.warning("sidecar_chat_failed", session_id=str(session_id), error=str(e))
                yield f"data: {json.dumps({'type': 'error', 'detail': str(e)})}\n\n"
            finally:
                reset_run_config(cfg_token)

        return StreamingResponse(gen(), media_type="text/event-stream", headers=SSE_HEADERS)

    @api.get("/research/{session_id}/export.md")
    async def export_markdown(
        session_id: uuid.UUID,
        db: AsyncSession = Depends(get_db),
        user: User = Depends(get_local_user),
    ):
        session = await _authorized_session(db, session_id, user.id)
        report = session.final_report or session.draft_report
        if not report:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="No report available to export.")
        # Demo-stamped exactly as the server stamps it (#52). Both hosts call the same
        # `bundle.stamp_demo_md`, so the rule has one implementation rather than two that
        # have to be kept in step by discipline. The desktop `.md` shipped unstamped for a
        # whole release while docs/29 promised every export path stamps — an unmarked
        # fixture report leaving the app is the one thing the demo flag exists to prevent.
        # The bundle stays unstamped on both hosts: prose in the report body would break
        # `report_hash` against the approval chain.
        report = bundle.stamp_demo_md(report, demo=bool(session.demo))
        report += bundle.render_model_attribution_md(session.model_routing)
        filename = f"research-{str(session.id)[:8]}.md"
        return Response(
            content=report,
            media_type="text/markdown; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @api.get("/research/{session_id}/export.bundle.json")
    async def export_bundle_json(
        session_id: uuid.UUID,
        db: AsyncSession = Depends(get_db),
        user: User = Depends(get_local_user),
    ):
        """Second home of `app/api/v1/research.py::export_bundle_json` (M0C).

        The desktop build rendered no way to reach this and the sidecar served no route,
        so the product's central differentiator — an artifact a third party can check
        offline — was unreachable from the app it ships in. Same failure shape as the
        chat panel that 404'd for a whole release.

        Four things differ from the server, and nothing else should:

        * evidence and contradictions come from the SQLite checkpointer rather than the
          Postgres one — same `aget_state`, different saver;
        * there is no `crypto.decrypt` step, because this host has no BYOK column;
        * the report is read directly rather than through `_report_or_404`, which is a
          server module; the demo rule it encodes is reproduced here (see below);
        * `trace_available` is **True**. `bundle.py`'s docstring cites the desktop as the
          example of a host without durable logging, but `PersistingSink` writes an
          `agent_logs` row for every event exactly as the worker's sink does, so the
          trace is real and saying otherwise would understate the artifact.

        The report is deliberately NOT demo-stamped, matching the server: `report_hash` is
        checked against the `draft_hash` recorded at approval, so prose injected into the
        body would break the approval chain for a reason that has nothing to do with the
        bundle's integrity. The `demo` field carries that provenance instead and is covered
        by `bundle_hash`.
        """
        session = await _authorized_session(db, session_id, user.id)
        if session.status != SessionStatus.COMPLETED:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                detail="Bundle export is only available for COMPLETED sessions.",
            )
        report = session.final_report or session.draft_report
        if not report:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="No report available to export.")

        agent_logs = (
            (
                await db.execute(
                    select(AgentLog)
                    .where(AgentLog.session_id == session.id)
                    .order_by(AgentLog.id.asc())
                )
            )
            .scalars()
            .all()
        )
        audit_logs = (
            (
                await db.execute(
                    select(AuditLog)
                    .where(AuditLog.session_id == session.id)
                    .order_by(AuditLog.id.asc())
                )
            )
            .scalars()
            .all()
        )

        # `app.state.sidecar`, not the `sidecar` local that `_drive_session` closes over —
        # that name does not exist in a route's scope. Same accessor the delete route uses
        # for `adelete_thread`.
        state = (
            await build_graph(app.state.sidecar["saver"]).aget_state(
                {"configurable": {"thread_id": str(session.id)}}
            )
        ).values or {}

        manifest = bundle.assemble(
            session_id=str(session.id),
            query=session.prompt,
            report=report,
            evidence=state.get("evidence", []),
            sources=session.sources or [],
            contradictions=state.get("contradictions", []),
            models=session.model_routing or {},
            cost_usd=float(session.total_cost_usd),
            tokens_input=session.total_tokens_input,
            tokens_output=session.total_tokens_output,
            elapsed_seconds=float(session.elapsed_seconds) if session.elapsed_seconds else None,
            research_depth=session.research_depth,
            approval_chain=[
                {
                    "action": al.action,
                    "feedback": al.feedback,
                    "draft_hash": al.draft_hash,
                    "timestamp": al.created_at.isoformat() if al.created_at else "",
                }
                for al in audit_logs
            ],
            trace=[log.payload for log in agent_logs],
            trace_available=True,
            demo=session.demo,
        )
        filename = f"research-{str(session.id)[:8]}.bundle.json"
        return Response(
            content=bundle.serialize(manifest),
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @api.get("/research/{session_id}/export.pdf", status_code=501)
    async def export_pdf(session_id: uuid.UUID):
        # By design (docs/13 §7): desktop PDF is the WebView's print-to-PDF, which the
        # frontend already does client-side. WeasyPrint stays out of the bundle.
        raise HTTPException(
            status.HTTP_501_NOT_IMPLEMENTED,
            detail="Desktop PDF uses the app's Print → Save as PDF. Server-side PDF is "
            "not part of the desktop bundle.",
        )

    @api.post("/research/{session_id}/cancel", response_model=SessionSummary)
    async def cancel_session(
        session_id: uuid.UUID,
        db: AsyncSession = Depends(get_db),
        user: User = Depends(get_local_user),
    ):
        """Stop an in-progress research run. Second home of the server's `cancel_session`.

        The Stop button in `SessionView` renders for PENDING/RUNNING on both builds and had
        no route here, so on desktop it 404'd (M1).

        **Cancellation is cooperative-by-omission, and that is the honest word for it.**
        Nothing interrupts the running work: the sidecar's `asyncio.Task` and the server's
        Celery task both continue to their next checkpoint, spending tokens after the user
        has been told the run stopped. What issue #54 changed is that the decision now
        *sticks* — `cancelled_at` is durable and `_apply_outcome` refuses to move a
        cancelled session out of its terminal state, so the run can no longer come back to
        life minutes later and offer its report for approval.

        Preemption stays unbuilt on purpose rather than by neglect. Killing the task risks a
        half-written LangGraph checkpoint, and the sidecar could do it (it owns the Task)
        where the server would need a different mechanism — which is exactly the undeclared
        divergence AGENTS.md warns about. A cooperative check at node boundaries is the
        shape that would work identically on both hosts; until it exists both hosts behave
        the same way, and `docs/25` says so plainly.
        """
        session = await _authorized_session(db, session_id, user.id)
        if session.status not in (SessionStatus.RUNNING, SessionStatus.PENDING):
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot stop a session with status {session.status}.",
            )

        session.status = SessionStatus.FAILED
        session.error_message = "Research stopped by user."
        # Second home of the server's line — the durable mark `_apply_outcome` reads so a
        # late outcome cannot move this session back out of its terminal state (issue #54).
        session.cancelled_at = datetime.now(UTC)
        await db.commit()
        await db.refresh(session)

        # Same ordering as `_apply_outcome`: the row is committed before the terminal
        # event leaves, so a client acting on FAILED never re-reads a stale status.
        bus = app.state.sidecar["bus"]
        payload = make_event("FAILED", message="Research stopped by user.")
        eid = bus.append(str(session_id), payload)
        payload["id"] = eid
        db.add(
            AgentLog(session_id=session_id, event_type="FAILED", agent_name=None, payload=payload)
        )
        await db.commit()

        logger.info("sidecar_research_stopped_by_user", session_id=str(session_id))
        return SessionSummary.model_validate(session)

    @api.post("/research/{session_id}/archive", response_model=SessionSummary)
    async def archive_session(
        session_id: uuid.UUID,
        db: AsyncSession = Depends(get_db),
        user: User = Depends(get_local_user),
    ):
        session = await _authorized_session(db, session_id, user.id)
        if session.archived_at is None:
            session.archived_at = datetime.now(UTC)
            await db.commit()
            await db.refresh(session)
        return SessionSummary.model_validate(session)

    @api.post("/research/{session_id}/unarchive", response_model=SessionSummary)
    async def unarchive_session(
        session_id: uuid.UUID,
        db: AsyncSession = Depends(get_db),
        user: User = Depends(get_local_user),
    ):
        session = await _authorized_session(db, session_id, user.id)
        if session.archived_at is not None:
            session.archived_at = None
            await db.commit()
            await db.refresh(session)
        return SessionSummary.model_validate(session)

    @api.delete("/research/{session_id}", status_code=204)
    async def delete_session(
        session_id: uuid.UUID,
        db: AsyncSession = Depends(get_db),
        user: User = Depends(get_local_user),
    ):
        session = await _authorized_session(db, session_id, user.id)
        if session.status == SessionStatus.RUNNING:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail="This session is still running. Wait for it to finish before deleting.",
            )
        await db.delete(session)
        await db.commit()
        try:
            await app.state.sidecar["saver"].adelete_thread(str(session_id))
        except Exception as e:  # noqa: BLE001 — the rows are gone; log and move on
            logger.warning("checkpoint_cleanup_failed", session_id=str(session_id), error=str(e))
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    # -- models -----------------------------------------------------------------

    @api.get("/models")
    async def get_catalog(user: User = Depends(get_local_user)):  # noqa: ARG001
        """The picker's catalog. Availability is judged by keys, desktop-style:
        keychain keys merged with the environment (nothing else exists here)."""
        user_routing = stored_routing(app.state.data_dir)
        effective = _effective_with(user_routing)
        try:
            config = sidecar_run_config(fake=app.state.fake, data_dir=app.state.data_dir)
            usable = set(config.provider_keys)
        except RuntimeError:
            usable = set()

        return {
            "roles": list(ROLES),
            "models": [
                {
                    "route": spec.route,
                    "provider": spec.provider,
                    "model_id": spec.model_id,
                    "display_name": spec.display_name,
                    "input_per_mtok": spec.input_per_mtok,
                    "output_per_mtok": spec.output_per_mtok,
                    "context_window": spec.context_window,
                    "max_output_tokens": spec.max_output_tokens,
                    "supports_tools": spec.supports_tools,
                    "supports_structured_output": spec.supports_structured_output,
                    "notes": spec.notes,
                    "available": spec.provider in usable,
                }
                for spec in sorted(
                    catalog.CATALOG.values(),
                    key=lambda s: (s.provider, s.output_per_mtok if s.priced else float("inf")),
                )
            ],
            "presets": catalog.PRESETS,
            "preset_names": list(catalog.PRESET_NAMES),
            "available_providers": sorted(usable),
            "effective_routing": effective,
            "user_routing": user_routing,
            "deployment_routing": effective,
        }

    def _effective_with(routing: dict[str, str] | None) -> dict[str, str]:
        models = {
            role: os.environ.get(f"MODEL_{role.upper()}", DEFAULT_MODELS[role]) for role in ROLES
        }
        if routing:
            models.update(routing)
        return models

    def _verdict_dict(verdict: provider_health.Verdict) -> dict:
        return {
            "state": verdict.state,
            "reason": verdict.reason,
            "checked_at": verdict.checked_at,
            "model_count": verdict.model_count,
        }

    @api.post("/models/providers/test")
    async def test_provider(request: Request):
        """Probe a submitted key BEFORE it is stored in the keychain (docs/07 §2, Phase
        2a) — contract copy #2 of the server's `POST /models/providers/test`."""
        body = await request.json()
        provider = body.get("provider", "")
        if provider not in ("google", "anthropic", "openai", "openrouter", "custom"):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Unknown provider.")
        key = (body.get("api_key") or "").strip()
        base_url = body.get("api_base_url")
        verdict = await provider_health.probe(provider, key, base_url)
        return _verdict_dict(verdict)

    @api.get("/models/providers/health/{provider}")
    async def provider_health_check(provider: str):
        """Re-probe a stored keychain key on demand (docs/07 §2, Phase 2a).

        Desktop can hold a key per provider simultaneously — unlike the server's single
        `user.api_key_provider` — so this is scoped by provider rather than "the" key.
        404s when nothing is stored for it, same reason as the server's endpoint: the
        keys screen already says "not connected" in prose for that case.
        """
        if provider not in ("google", "anthropic", "openai", "openrouter", "custom"):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Unknown provider.")
        key = stored_keys().get(provider)
        if not key:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="No key stored to check.")
        base_url = stored_custom_endpoint(app.state.data_dir) if provider == "custom" else None
        verdict = await provider_health.probe(provider, key, base_url)
        return _verdict_dict(verdict)

    @api.get("/models/local/status")
    async def local_status():
        """Probe the configured local model server — same shape as the server's
        `GET /models/local/status`, which this build had no counterpart for at all."""
        status_ = await local_llm.probe()
        return {
            "configured_base_url": status_.configured_base_url,
            "reachable": status_.reachable,
            "usable": status_.usable,
            "models": [
                {
                    "name": m.name,
                    "size_bytes": m.size_bytes,
                    "route": m.route,
                    "in_catalog": m.in_catalog,
                    "likely_underpowered": m.likely_underpowered,
                    "is_embedding": m.is_embedding,
                    "params_b": m.params_b,
                }
                for m in status_.models
            ],
            "error": status_.error,
            "hint": status_.hint,
            "install_state": status_.install_state,
        }

    @api.get("/models/custom/status")
    async def custom_status():
        """Contract copy of the server's `GET /models/custom/status`.

        Restated rather than imported because every route in this host is — the server
        handler carries `Depends(get_current_user)`, which needs the JWT stack this host
        does not have. The *probe* underneath is shared, so the two hosts cannot disagree
        about what the endpoint serves; only the auth wrapper differs, which is the one
        difference this host is allowed to have.
        """
        status_ = await custom_endpoint.probe()
        return {
            "configured_base_url": status_.configured_base_url,
            "reachable": status_.reachable,
            "models": status_.models,
            "error": status_.error,
            "hint": status_.hint,
        }

    @api.post("/models/local/start")
    async def start_local_server():
        """One-click local model server (docs/07 §2, Phase 2b) — the honest boundary
        stated in the UI: the web build can only guide, the desktop build can act,
        because only here does the request originate from a process already running
        on the user's own machine.

        No-ops if a server is already reachable — this checks live state rather than
        trusting a stale "we started it" flag, the same reasoning `get_readiness`
        documents for not caching a boolean across requests.
        """
        status_ = await local_llm.probe()
        if status_.reachable:
            return {"already_running": True}

        existing = app.state.sidecar.get("local_llm_process")
        if existing is not None and existing.returncode is None:
            return {"already_running": True}

        binary = local_llm.resolve_binary()
        if binary is None:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND,
                detail="Ollama is not installed on this machine. Install it, then try again.",
            )
        try:
            process = await asyncio.create_subprocess_exec(
                binary,
                "serve",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
        except OSError as e:
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE, detail=f"Could not start Ollama: {e}"
            ) from e
        app.state.sidecar["local_llm_process"] = process
        return {"started": True}

    @api.post("/models/local/stop")
    async def stop_local_server():
        """Stop the server this app started. A server the user started themselves
        (outside the app, or before the app's own start) is never touched — this
        process handle is only ever set by `/local/start`."""
        process = app.state.sidecar.get("local_llm_process")
        if process is None or process.returncode is not None:
            return {"stopped": False, "reason": "Not started by this app."}
        process.terminate()
        try:
            await asyncio.wait_for(process.wait(), timeout=5.0)
        except TimeoutError:
            process.kill()
        app.state.sidecar["local_llm_process"] = None
        return {"stopped": True}

    @api.post("/models/local/pull")
    async def pull_model(request: Request):
        """Stream download progress for a recommended model (docs/07 §2, Phase 2b) —
        newline-delimited JSON, one `PullProgress` per line, same shape the frontend
        already knows how to read incrementally from the research SSE stream's raw
        body (this is plain chunked HTTP, not SSE — Ollama's own wire format)."""
        body = await request.json()
        model = (body.get("model") or "").strip()
        if not model:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="No model given.")

        async def gen():
            async for progress in local_llm.pull(model):
                yield (
                    json.dumps(
                        {
                            "status": progress.status,
                            "completed": progress.completed,
                            "total": progress.total,
                            "error": progress.error,
                        }
                    )
                    + "\n"
                )

        return StreamingResponse(gen(), media_type="application/x-ndjson")

    @api.get("/models/routing")
    async def get_routing(user: User = Depends(get_local_user)):  # noqa: ARG001
        """The saved routing and the one a run would dial. Second home of the server's
        `GET /models/routing` — both hosts shipped this trio write-only (PUT and DELETE
        but no GET) while the frontend already fetched it, so the read 405'd on both.

        `routing` is null when nothing is saved, distinct from `effective_routing`, which
        always resolves — see the server's docstring for why the two must not collapse.
        """
        saved = stored_routing(app.state.data_dir)
        return {"routing": saved or None, "effective_routing": _effective_with(saved or None)}

    @api.put("/models/routing")
    async def set_routing(payload: dict, user: User = Depends(get_local_user)):  # noqa: ARG001
        """Save the per-role routing to `routing.json` in the data directory.

        Validated before it is stored (same contract as the server's endpoint), so a
        saved preference is always startable.
        """
        try:
            cleaned = validate_routing(payload.get("routing", payload))
        except ValueError as e:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)) from e
        save_routing(app.state.data_dir, cleaned)
        return {"routing": cleaned, "effective_routing": _effective_with(cleaned)}

    @api.delete("/models/routing")
    async def clear_routing(user: User = Depends(get_local_user)):  # noqa: ARG001
        """Drop the saved preference; routing falls back to MODEL_* env / defaults."""
        save_routing(app.state.data_dir, None)
        return {"routing": None, "effective_routing": _effective_with(None)}

    # -- keys --------------------------------------------------------------------

    @api.put("/desktop/keys/{provider}", status_code=204)
    async def set_key(provider: str, request: Request):
        """Store a pasted provider key in the OS keychain (docs/12 M9)."""
        if provider not in ("google", "anthropic", "openai", "openrouter", "custom"):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Unknown provider.")
        body = await request.json()
        key = (body.get("key") or "").strip()
        if not key:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Key is empty.")
        try:
            store_key(provider, key)
        except RuntimeError as e:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e)) from e
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @api.delete("/desktop/keys/{provider}", status_code=204)
    async def remove_key(provider: str):
        """Forget a stored key from the OS keychain (the env-derived ones are read-only)."""
        if provider not in ("google", "anthropic", "openai", "openrouter", "custom"):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Unknown provider.")
        try:
            delete_key(provider)
        except RuntimeError as e:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e)) from e
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @api.get("/desktop/keys")
    async def list_keys():
        """Which providers have a stored key — hints only, keys never leave the chain."""
        present = stored_keys()
        env_names = {
            "google": "GOOGLE_API_KEY",
            "anthropic": "ANTHROPIC_API_KEY",
            "openai": "OPENAI_API_KEY",
            "openrouter": "OPENROUTER_API_KEY",
            "custom": "CUSTOM_API_KEY",
        }
        return {
            provider: {
                "keychain": provider in present,
                "environment": bool(os.environ.get(env_names[provider])),
            }
            for provider in ("google", "anthropic", "openai", "openrouter", "custom")
        }

    @api.put("/desktop/keys/custom_endpoint", status_code=204)
    async def set_custom_endpoint(request: Request):
        body = await request.json()
        base_url = (body.get("base_url") or "").strip()
        save_custom_endpoint(app.state.data_dir, base_url if base_url else None)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @api.get("/desktop/keys/custom_endpoint")
    async def get_custom_endpoint():
        return {"base_url": stored_custom_endpoint(app.state.data_dir)}

    # -- corpus (airgapped mode, docs/12 M10) -----------------------------------

    def _corpus() -> CorpusStore:
        store = app.state.sidecar.get("corpus")
        if store is None:  # pragma: no cover — lifespan installs it before serving
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail="Corpus not ready.")
        return store

    def _document_response(d: dict) -> dict:
        """`CorpusStore.documents()`'s raw shape → the server's `DocumentResponse` field
        names (`app/api/v1/corpus.py`) — the same client contract on both hosts.

        Registration alone made these routes look done: `test_desktop_contract_gaps.py`
        called them and got 200s, but nothing checked the *body* against the server's
        actual field names (`id`/`chunks`/`created_at`) versus this store's own
        (`chunk_count`/`ingested_at`) — id vs doc_id, chunks vs chunks_written. The
        frontend hook types the response as a bare `CorpusDocument[]`
        (`hooks/queries.ts::useCorpusDocuments`); the wrapped `{"documents": [...]}` this
        used to return has `.length` read as `undefined` off the wrapper object, which is
        falsy, so the Corpus page rendered "no documents" for a corpus that was never
        empty — silent data loss in the UI, not a crash, which is why it went unnoticed.
        """
        return {
            "id": d["id"],
            "filename": d["filename"],
            "chunks": d["chunk_count"],
            "created_at": d["ingested_at"],
            "size_bytes": d.get("size_bytes"),
            "downloadable": d.get("downloadable", False),
            "origin": d.get("origin", "uploaded"),
        }

    def _corpus_status_response(info: dict) -> dict:
        """Same shape gap as `_document_response`, in `CorpusStatusResponse`: the server
        adds a top-level `chunks` sum (`app/api/v1/corpus.py::get_status`) that
        `CorpusStore.status()` itself does not compute — this host must add it too."""
        info = dict(info)
        info["chunks"] = sum(info["chunks_by_model"].values())
        return info

    @api.post("/corpus/documents", status_code=201)
    async def upload_document(request: Request, filename: str):
        """Ingest one PDF/MD/TXT into the corpus.

        Raw bytes in the body, name in the query — deliberately not multipart, so the
        frozen bundle needs no python-multipart. Errors stay fail-closed: an
        unsupported format or an unreachable embedding server is a 4xx/5xx, never a
        silent skip.
        """
        clean_name = Path(filename).name  # the name is metadata only; never a path
        if not clean_name:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, detail="filename is required."
            )
        body = await request.body()
        if not body:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, detail="The document body is empty."
            )
        if len(body) > MAX_DOCUMENT_BYTES:
            raise HTTPException(
                status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"Document is {len(body)} bytes; the limit is {MAX_DOCUMENT_BYTES}.",
            )
        try:
            result = await _corpus().ingest(clean_name, body)
        except ValueError as e:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)) from e
        except EmbeddingsUnavailable as e:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e)) from e
        # Same field names as the server's DocumentResponse (app/api/v1/corpus.py), not
        # `Ingested`'s own doc_id/chunks_written/skipped/reason — see _document_response.
        return {"id": result.doc_id, "filename": result.filename, "chunks": result.chunks_written}

    @api.get("/corpus/documents")
    async def list_corpus_documents():
        return [_document_response(d) for d in await _corpus().documents()]

    @api.delete("/corpus/documents/{doc_id}", status_code=204)
    async def delete_corpus_document(doc_id: str):
        if not await _corpus().delete(doc_id):
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Document not found.")
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @api.get("/corpus/status")
    async def corpus_status():
        info = _corpus_status_response(await _corpus().status())
        info["corpus_only"] = corpus_only_enabled(app.state.data_dir)
        return info

    @api.put("/corpus/mode")
    async def set_corpus_mode(payload: dict):
        """Flip corpus-only mode. Persisted; the next run picks it up via RunConfig."""
        corpus_only = bool(payload.get("corpus_only"))
        save_corpus_config(app.state.data_dir, corpus_only=corpus_only)
        logger.info("sidecar_corpus_mode", corpus_only=corpus_only)
        return {"corpus_only": corpus_only}

    # -- canonical per-project corpus contract (M1.5) ---------------------------
    #
    # The flat `/corpus/*` routes above are the desktop's *internal* shape: this host
    # keeps one `corpus.sqlite` for the whole app rather than one file per project. That
    # is a real infrastructure difference and it stays.
    #
    # What was wrong is that the difference leaked into the client. The Corpus page and
    # the report preview call `/projects/{id}/corpus/...` — the server's shape — with no
    # `isDesktop` branch, so on desktop the document list, status panel, upload, delete
    # and preview all 404'd. Both hosts had a complete corpus implementation and they
    # never met (M1, `KNOWN_DESKTOP_GAPS`).
    #
    # So the per-project path is the **canonical product contract** and both hosts serve
    # it. Here it resolves to the one flat store, which is exactly the "same contract,
    # different internals" split the parity harness is meant to protect. Adding a branch
    # to the frontend instead would have taught it about a storage decision it has no
    # business knowing.
    #
    # `_resolve_project` still runs and still 404s on an unknown project, matching the
    # server's authorization boundary — the project id is not *used* to pick a store, but
    # answering for a project that does not exist would be a different contract.

    @api.get("/projects/{project_id}/corpus/documents")
    async def list_project_corpus_documents(
        project_id: uuid.UUID,
        db: AsyncSession = Depends(get_db),
        user: User = Depends(get_local_user),
    ):
        await _resolve_project(db, user.id, project_id)
        return [_document_response(d) for d in await _corpus().documents()]

    @api.get("/projects/{project_id}/corpus/status")
    async def project_corpus_status(
        project_id: uuid.UUID,
        db: AsyncSession = Depends(get_db),
        user: User = Depends(get_local_user),
    ):
        await _resolve_project(db, user.id, project_id)
        info = _corpus_status_response(await _corpus().status())
        info["corpus_only"] = corpus_only_enabled(app.state.data_dir)
        return info

    @api.post("/projects/{project_id}/corpus/documents", status_code=201)
    async def upload_project_corpus_document(
        project_id: uuid.UUID,
        file: UploadFile,
        db: AsyncSession = Depends(get_db),
        user: User = Depends(get_local_user),
    ):
        """Multipart, matching the server — this is the canonical client contract.

        The flat route above takes raw bytes with the name in the query string, chosen so
        the frozen bundle would not need `python-multipart`. That saving is not available
        here: the browser sends a `FormData`, and teaching the frontend to encode
        differently for one host is precisely the leak this section removes.
        `python-multipart` is already a hard backend dependency; the PyInstaller spec now
        names it explicitly because nothing else in the sidecar's import graph pulls it in.
        """
        await _resolve_project(db, user.id, project_id)

        clean_name = Path(file.filename or "").name  # metadata only; never a path
        if not clean_name:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, detail="filename is required."
            )
        body = await file.read()
        if not body:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, detail="The document body is empty."
            )
        if len(body) > MAX_DOCUMENT_BYTES:
            raise HTTPException(
                status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"Document is {len(body)} bytes; the limit is {MAX_DOCUMENT_BYTES}.",
            )
        try:
            result = await _corpus().ingest(clean_name, body)
        except ValueError as e:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)) from e
        except EmbeddingsUnavailable as e:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e)) from e
        # Same field names as the server's DocumentResponse — see _document_response.
        return {"id": result.doc_id, "filename": result.filename, "chunks": result.chunks_written}

    @api.delete("/projects/{project_id}/corpus/documents/{doc_id}", status_code=204)
    async def delete_project_corpus_document(
        project_id: uuid.UUID,
        doc_id: str,
        db: AsyncSession = Depends(get_db),
        user: User = Depends(get_local_user),
    ):
        await _resolve_project(db, user.id, project_id)
        if not await _corpus().delete(doc_id):
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Document not found.")
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @api.get("/projects/{project_id}/corpus/documents/{doc_id}/download")
    async def download_project_corpus_document(
        project_id: uuid.UUID,
        doc_id: str,
        db: AsyncSession = Depends(get_db),
        user: User = Depends(get_local_user),
    ):
        """Serve the original uploaded file, with the server's own response headers.

        `download_headers` is imported from the server module rather than restated: it is
        where the rule that an uploaded document must not render in this origin lives,
        along with the single narrow exception (PDF) that in-place preview needs. A second
        copy of a security header policy is the worst kind of duplication to have.
        """
        await _resolve_project(db, user.id, project_id)
        found = await _corpus().blob(doc_id)
        if found is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Document not found.")
        data, filename, kind = found
        return Response(content=data, headers=download_headers(kind, filename))

    # ── The research run surface ──────────────────────────────────────────────────
    #
    # Second home of `app/api/v1/runs.py`, added in the SAME milestone as the server
    # routes rather than a release later. The chat panel and the bundle export both shipped
    # server-only and 404'd in the desktop build for a whole release; `test_host_parity`
    # exists to stop the third instance, and it caught these five before they landed.
    #
    # Only two things differ, and nothing else should: the user comes from the per-launch
    # local token instead of a JWT, and the projection/lifecycle/bundle code is *imported*
    # from `app/` rather than restated — one contract, one implementation.

    async def _v2_run_or_404(db: AsyncSession, run_id: uuid.UUID, owner_id: uuid.UUID):
        from app.api.v1.runs import _run_or_404

        return await _run_or_404(db, run_id, owner_id)

    @api.post("/runs", status_code=201)
    async def v2_create_run(
        body: V2CreateRunRequest,
        db: AsyncSession = Depends(get_db),
        user: User = Depends(get_local_user),
    ):
        # This used to answer 501: executing a run meant `run_execution.execute_run`, which
        # takes a Redis lock and checkpoints to Postgres, or a Celery task this host has no
        # broker for. That made the packaged app's primary control — Start research — a
        # button that could not work, because the desktop UI does call this path.
        #
        # The fix is the in-process driver, not a wider bundle: `_dispatcher` runs the same
        # engine against this host's SQLite saver. The handler below is the server's, byte
        # for byte, so the ordering rules it encodes are not restated here.
        from app.api.v1.runs import create_run

        return await create_run(body, db, user, dispatcher=_dispatcher)

    @api.get("/runs")
    async def v2_list_runs(
        project_id: uuid.UUID | None = None,
        archived: bool = False,
        limit: int = 50,
        db: AsyncSession = Depends(get_db),
        user: User = Depends(get_local_user),
    ):
        from app.api.v1.runs import list_runs

        return await list_runs(project_id, archived, limit, db, user)

    @api.get("/runs/{run_id}")
    async def v2_get_run(
        run_id: uuid.UUID,
        db: AsyncSession = Depends(get_db),
        user: User = Depends(get_local_user),
    ):
        from app.api.v1.runs import project_run

        return await project_run(db, await _v2_run_or_404(db, run_id, user.id))

    @api.post("/runs/{run_id}/plan-review", status_code=201)
    async def v2_submit_plan_review(
        run_id: uuid.UUID,
        body: V2PlanReviewRequest,
        db: AsyncSession = Depends(get_db),
        user: User = Depends(get_local_user),
    ):
        from app.api.v1.runs import submit_plan_review

        return await submit_plan_review(run_id, body, db, user, dispatcher=_dispatcher)

    @api.post("/runs/{run_id}/report-review", status_code=201)
    async def v2_submit_report_review(
        run_id: uuid.UUID,
        body: V2ReportReviewRequest,
        db: AsyncSession = Depends(get_db),
        user: User = Depends(get_local_user),
    ):
        from app.api.v1.runs import submit_report_review

        result = await submit_report_review(run_id, body, db, user, dispatcher=_dispatcher)

        if body.decision == "APPROVED":
            # `submit_report_review` already tried its own server-side corpus ingest and
            # swallowed it (app/api/v1/runs.py::_ingest_report_into_corpus) — it imports
            # `app.config`/`app.adapters`, which `make_corpus_store`'s own docstring
            # documents as excluded from this bundle, so that attempt always fails cleanly
            # here and never completes the save. This is the completion: desktop's actual,
            # bundle-safe path, using the same flat `corpus.sqlite` every other desktop
            # corpus route writes to (AGENTS.md — one store for the whole app, by design).
            from app.models.revision import Revision
            from app.services.report_corpus import ingest_report

            revision = (
                (
                    await db.execute(
                        select(Revision)
                        .where(Revision.run_id == run_id)
                        .order_by(Revision.version.desc())
                    )
                )
                .scalars()
                .first()
            )
            if revision is not None:
                await ingest_report(
                    make_corpus_store(app.state.data_dir),
                    session_id=str(run_id),
                    report_markdown=revision.report_markdown,
                )

        return result

    @api.get("/runs/{run_id}/stream")
    async def v2_stream_run(
        run_id: uuid.UUID,
        request: Request,
        db: AsyncSession = Depends(get_db),
        user: User = Depends(get_local_user),
    ):
        """The run stream, over this host's in-process bus rather than Redis.

        The only difference from the server, and the same one the session stream already has:
        there is no Redis here, so the live tail comes from `SessionEventBus`. Backlog,
        `Last-Event-ID` replay and the stop-list are identical, and the backlog query works
        unchanged because `agent_logs.session_id` is polymorphic.
        """
        from app.api.v1.runs import _REPLAY_STOP_EVENTS as V2_REPLAY_STOP
        from app.api.v1.runs import _TERMINAL_EVENTS as V2_TERMINAL
        from app.api.v1.runs import _run_or_404

        run = await _run_or_404(db, run_id, user.id)
        bus: SessionEventBus = app.state.sidecar["bus"]
        last_event_id = request.headers.get("last-event-id")
        after_id = int(last_event_id) if last_event_id and last_event_id.isdigit() else 0

        async with session_factory() as sdb:
            backlog = [
                (row.id, row.payload)
                for row in (
                    await sdb.execute(
                        select(AgentLog)
                        .where(AgentLog.session_id == run_id, AgentLog.id > after_id)
                        .order_by(AgentLog.id.asc())
                    )
                )
                .scalars()
                .all()
            ]
        already_done = run.status in (
            "COMPLETED",
            "FAILED",
            "CANCELLED",
            "AWAITING_PLAN",
            "AWAITING_REVIEW",
        )

        async def gen() -> AsyncGenerator[str, None]:
            yield f"data: {json.dumps({'type': 'connected', 'run_id': str(run_id)})}\n\n"
            seen_max = after_id
            for eid, payload in backlog:
                seen_max = max(seen_max, eid or 0)
                yield f"id: {eid}\ndata: {json.dumps(payload)}\n\n"
                if payload.get("type") in V2_REPLAY_STOP:
                    return
            if already_done:
                return
            async with bus.subscribe(str(run_id)) as queue:
                while True:
                    eid, payload = await queue.get()
                    if eid <= seen_max:
                        continue
                    yield f"id: {eid}\ndata: {json.dumps(payload)}\n\n"
                    seen_max = eid
                    if payload.get("type") in V2_TERMINAL:
                        return

        return StreamingResponse(gen(), media_type="text/event-stream", headers=SSE_HEADERS)

    @api.get("/runs/{run_id}/export.md")
    async def v2_export_markdown(
        run_id: uuid.UUID,
        revision_version: int | None = None,
        db: AsyncSession = Depends(get_db),
        user: User = Depends(get_local_user),
    ):
        from app.api.v1.runs import export_markdown

        return await export_markdown(run_id, revision_version, db, user)

    @api.get("/runs/{run_id}/export.pdf", status_code=501)
    async def v2_export_pdf(run_id: uuid.UUID):
        # By design (docs/13 §7), same as the session route: desktop PDF is the WebView's
        # print-to-PDF, and WeasyPrint stays out of the bundle. Declaring the route rather
        # than omitting it is what makes the 501 a documented answer instead of a 404 the
        # UI has to guess about.
        raise HTTPException(
            status.HTTP_501_NOT_IMPLEMENTED,
            detail="Desktop PDF uses the app's Print → Save as PDF. Server-side PDF is "
            "not part of the desktop bundle.",
        )

    @api.post("/runs/{run_id}/cancel")
    async def v2_cancel_run(
        run_id: uuid.UUID,
        db: AsyncSession = Depends(get_db),
        user: User = Depends(get_local_user),
    ):
        from app.api.v1.runs import cancel_run

        return await cancel_run(run_id, db, user)

    @api.post("/runs/{run_id}/archive")
    async def v2_archive_run(
        run_id: uuid.UUID,
        db: AsyncSession = Depends(get_db),
        user: User = Depends(get_local_user),
    ):
        from app.api.v1.runs import archive_run

        return await archive_run(run_id, db, user)

    @api.post("/runs/{run_id}/unarchive")
    async def v2_unarchive_run(
        run_id: uuid.UUID,
        db: AsyncSession = Depends(get_db),
        user: User = Depends(get_local_user),
    ):
        from app.api.v1.runs import unarchive_run

        return await unarchive_run(run_id, db, user)

    @api.delete("/runs/{run_id}", status_code=204)
    async def v2_delete_run(
        run_id: uuid.UUID,
        db: AsyncSession = Depends(get_db),
        user: User = Depends(get_local_user),
    ):
        from app import run_lifecycle
        from app.api.v1.runs import _run_or_404

        run = await _run_or_404(db, run_id, user.id)
        try:
            await run_lifecycle.delete_run(db, run)
        except run_lifecycle.LifecycleError as exc:
            raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
        await db.commit()

        try:
            await app.state.sidecar["saver"].adelete_thread(str(run_id))
        except Exception as e:  # noqa: BLE001
            logger.warning("checkpoint_cleanup_failed", run_id=str(run_id), error=str(e))

        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @api.get("/runs/{run_id}/bundle.json")
    async def v2_get_bundle(
        run_id: uuid.UUID,
        db: AsyncSession = Depends(get_db),
        user: User = Depends(get_local_user),
    ):
        from app.api.v1.runs import get_bundle

        return await get_bundle(run_id, db, user)

    @api.get("/runs/{run_id}/verification")
    async def v2_get_verification(
        run_id: uuid.UUID,
        db: AsyncSession = Depends(get_db),
        user: User = Depends(get_local_user),
    ):
        from app.api.v1.runs import get_verification

        return await get_verification(run_id, db, user)

    app.include_router(api)
    return app


# ── Entry point ──────────────────────────────────────────────────────────────────


def shell_alive(pid: int) -> bool:
    """True while a process with this PID exists and we may signal it."""
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:  # pragma: no cover — exists but not ours anymore
        return True


def _watch_shell(shell_pid: int) -> None:
    """Die when the launching shell disappears.

    The shell kills the sidecar on graceful exit, but a hard kill (kill -9, crash,
    OS force-quit) never runs that path — so the sidecar supervises back and never
    outlives its parent by more than one poll interval.
    """
    import time

    while True:
        time.sleep(2.0)
        if not shell_alive(shell_pid):
            os._exit(0)


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="research-sidecar")
    parser.add_argument("--data-dir", default=str(Path.home() / ".research-engine"))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=0, help="0 = ephemeral (the default)")
    parser.add_argument("--fake", action="store_true", help="scripted models, no keys needed")
    parser.add_argument(
        "--shell-pid",
        type=int,
        default=None,
        help="exit automatically when this PID disappears (Tauri shell supervision)",
    )
    args = parser.parse_args(argv)

    if args.host != "127.0.0.1":
        # The token threat model assumes loopback only. Refuse rather than weaken.
        print("error: the sidecar binds 127.0.0.1 only (docs/13 §7)", file=sys.stderr)
        return 2

    if args.shell_pid:
        import threading

        threading.Thread(target=_watch_shell, args=(args.shell_pid,), daemon=True).start()

    token = secrets.token_urlsafe(32)
    app = create_sidecar_app(data_dir=args.data_dir, token=token, fake=args.fake)

    # Pick the ephemeral port BEFORE handing the socket to uvicorn, so the handshake
    # line carries the real number. SO_REUSEADDR lets uvicorn rebind the same port.
    import socket

    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    probe.bind((args.host, args.port))
    port = probe.getsockname()[1]
    probe.close()

    # The handshake. The Tauri shell parses exactly this line from stdout and then
    # supervises the process; nothing else may print before it.
    print(json.dumps({"ready": True, "host": args.host, "port": port, "token": token}), flush=True)

    uvicorn.run(app, host=args.host, port=port, log_level="warning", access_log=False)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
