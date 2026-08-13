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
import hmac
import json
import os
import secrets
import sys
import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
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
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from sqlalchemy import event, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models import Base
from app.models.agent_log import AgentLog
from app.models.memory_chunk import MemoryChunk
from app.models.project import Project
from app.models.session import Session, SessionStatus
from app.models.user import User
from app.schemas.project import ProjectCreateRequest, ProjectListResponse, ProjectResponse
from app.schemas.research import (
    ApprovalRequest,
    ResearchStartRequest,
    ResearchStartResponse,
    SessionDetail,
    SessionListResponse,
    SessionSummary,
)
from app.services.sse import SSE_HEADERS
from research_engine import catalog
from research_engine.corpus import CorpusStore
from research_engine.documents import MAX_DOCUMENT_BYTES
from research_engine.embeddings import EmbeddingsUnavailable, LocalEmbeddings
from research_engine.events import make_event
from research_engine.local import SqliteCache, load_env_file
from research_engine.runconfig import DEFAULT_MODELS, ROLES, RunConfig
from research_engine.runner import RunOutcome, resume, run

logger = structlog.get_logger()

DEFAULT_PROJECT_NAME = "General"
LOCAL_USER_EMAIL = "local@desktop.invalid"
_KEYRING_SERVICE = "research-assistant-desktop"

# Event types that end an SSE stream — identical to the server's contract
# (app/api/v1/research.py), so the same frontend hook drives both hosts.
_TERMINAL_EVENTS = ("COMPLETED", "FAILED", "HITL_READY")


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


def validate_routing(routing: dict) -> dict[str, str]:
    if not isinstance(routing, dict):
        raise ValueError("Model routing must be an object keyed by agent role.")
    unknown_roles = sorted(set(routing) - set(ROLES))
    if unknown_roles:
        raise ValueError(f"Unknown agent role(s): {unknown_roles}. Valid roles: {list(ROLES)}.")
    missing_roles = sorted(set(ROLES) - set(routing))
    if missing_roles:
        raise ValueError(f"Every role needs a model. Missing: {missing_roles}.")
    cleaned: dict[str, str] = {}
    for role, route in routing.items():
        if not isinstance(route, str) or ":" not in route:
            raise ValueError(f"{role}: expected a 'provider:model' string, got {route!r}.")
        provider, _, model_id = route.partition(":")
        if provider not in catalog.KNOWN_PROVIDERS:
            raise ValueError(
                f"{role}: unknown provider '{provider}'. Known: {', '.join(catalog.KNOWN_PROVIDERS)}."
            )
        spec = catalog.get(model_id)
        if spec is None:
            raise ValueError(f"{role}: '{model_id}' is not in the model catalog.")
        if not spec.priced:
            raise ValueError(
                f"{role}: '{model_id}' has no configured price, so spending on it could "
                "not be capped. Add its price to the catalog before routing to it."
            )
        cleaned[role] = spec.route
    return cleaned


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


def sidecar_run_config(*, fake: bool, data_dir: str | Path | None = None) -> RunConfig:
    """The desktop's RunConfig: env keys merged with keychain keys (keychain wins).

    The desktop counterpart of `local.run_config_from_env` — same shape, but a user who
    pasted a key into the settings screen keeps working after a restart, because the
    keychain is consulted at every launch (docs/12 M9: keys in the OS keychain).
    """
    if fake:
        return RunConfig(llm_mode="fake", corpus_mode=corpus_only_enabled(data_dir))

    load_env_file()
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

    models = {role: os.environ.get(f"MODEL_{role.upper()}", DEFAULT_MODELS[role]) for role in ROLES}
    if data_dir is not None:
        saved = stored_routing(data_dir)
        if saved:
            models.update(saved)  # the user's saved preference beats MODEL_* env
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
        # The pgvector-backed table cannot exist on SQLite; the corpus keeps its own
        # store (docs/12 M10). Everything else in the schema is dialect-portable
        # (app/models/types.py).
        tables = [t for t in Base.metadata.sorted_tables if t.name != MemoryChunk.__tablename__]
        async with engine.begin() as conn:
            await conn.run_sync(
                lambda sync_conn: Base.metadata.create_all(sync_conn, tables=tables)
            )

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
        await db.commit()
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
        session.status = {
            "awaiting_approval": SessionStatus.AWAITING_APPROVAL,
            "completed": SessionStatus.COMPLETED,
            "failed": SessionStatus.FAILED,
        }[outcome.status]
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
        await db.commit()

        lifecycle = {
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
        session_id: uuid.UUID, *, approved: bool | None, feedback: str | None
    ) -> None:
        """Run or resume one session in-process — the desktop's Celery replacement."""
        sidecar = app.state.sidecar
        sink = PersistingSink(sidecar["bus"], session_factory)
        try:
            config = sidecar_run_config(fake=app.state.fake, data_dir=app.state.data_dir)
        except RuntimeError as e:
            async with session_factory() as db:
                session = await _authorized_session(db, session_id, sidecar["user_id"])
                session.status = SessionStatus.FAILED
                session.error_message = str(e)[:500]
                await db.commit()
            payload = make_event("FAILED", message=str(e))
            payload["id"] = sidecar["bus"].append(str(session_id), payload)
            return

        ports = {
            "event_sink": sink,
            "cache": sidecar["cache"],
            "run_config": config,
            "corpus": sidecar["corpus"],
        }
        try:
            if approved is None:
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

    @api.post("/research", response_model=ResearchStartResponse, status_code=202)
    async def start_research(
        payload: ResearchStartRequest,
        db: AsyncSession = Depends(get_db),
        user: User = Depends(get_local_user),
    ):
        project = await _resolve_project(db, user.id, payload.project_id)
        session = Session(
            user_id=user.id,
            project_id=project.id,
            prompt=payload.query,
            status=SessionStatus.PENDING,
            research_depth=payload.depth,
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
        already_done = session.status in (SessionStatus.COMPLETED, SessionStatus.FAILED)

        async def gen() -> AsyncGenerator[str, None]:
            yield f"data: {json.dumps({'type': 'connected'})}\n\n"
            seen_max = after_id
            for eid, payload in backlog:
                seen_max = max(seen_max, eid or 0)
                yield f"id: {eid}\ndata: {json.dumps(payload)}\n\n"
                if payload.get("type") in _TERMINAL_EVENTS:
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
        session.status = SessionStatus.RUNNING
        session.rework_count = session.rework_count + (0 if payload.approved else 1)
        await db.commit()
        asyncio.create_task(
            _drive_session(session_id, approved=payload.approved, feedback=payload.feedback)
        )
        return {"message": "Approved. Finalizing." if payload.approved else "Rework requested."}

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
        filename = f"research-{str(session.id)[:8]}.md"
        return Response(
            content=report,
            media_type="text/markdown; charset=utf-8",
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
        return {
            "doc_id": result.doc_id,
            "filename": result.filename,
            "chunks_written": result.chunks_written,
            "skipped": result.skipped,
            "reason": result.reason,
        }

    @api.get("/corpus/documents")
    async def list_corpus_documents():
        return {"documents": await _corpus().documents()}

    @api.delete("/corpus/documents/{doc_id}", status_code=204)
    async def delete_corpus_document(doc_id: str):
        if not await _corpus().delete(doc_id):
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Document not found.")
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @api.get("/corpus/status")
    async def corpus_status():
        info = await _corpus().status()
        info["corpus_only"] = corpus_only_enabled(app.state.data_dir)
        return info

    @api.put("/corpus/mode")
    async def set_corpus_mode(payload: dict):
        """Flip corpus-only mode. Persisted; the next run picks it up via RunConfig."""
        corpus_only = bool(payload.get("corpus_only"))
        save_corpus_config(app.state.data_dir, corpus_only=corpus_only)
        logger.info("sidecar_corpus_mode", corpus_only=corpus_only)
        return {"corpus_only": corpus_only}

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
