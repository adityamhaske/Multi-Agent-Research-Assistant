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
from sqlalchemy import event, select
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models import POSTGRES_ONLY_TABLES, Base
from app.models.agent_log import AgentLog
from app.models.audit_log import AuditLog
from app.models.chat_message import ChatMessage
from app.models.project import Project
from app.models.session import Session, SessionStatus
from app.models.user import User
from app.ports import CheckpointDeleter, CorpusLocator
from app.schemas.auth import ConnectionVerdict, UsageResponse, UserResponse
from app.schemas.capabilities import DESKTOP, Capabilities
from app.schemas.corpus import CorpusStatusResponse, DocumentResponse
from app.schemas.models import (
    CatalogResponse,
    CustomEndpointStatusResponse,
    LocalLLMStatusResponse,
    RoutingResponse,
)
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

# The run request models are imported, not restated: the desktop host must accept exactly
# the body the server does, and two Pydantic models with the same name in two files is how
# that stops being true.
from app.schemas.runs import CreateRunRequest as V2CreateRunRequest
from app.schemas.runs import PlanReviewRequest as V2PlanReviewRequest
from app.schemas.runs import ReportReviewRequest as V2ReportReviewRequest

# The corpus upload contract — validation, failure mapping and response shape — lives in
# one module because both hosts serve the canonical per-project path and each used to
# choose its own status codes for the same rejection. Stdlib/pydantic/FastAPI only, so it
# is importable here (#50).
from app.services import (
    chat_scope,
    corpus_ingest,
    custom_endpoint,
    local_llm,
    memory,
    provider_health,
    usage,
)

# `download_headers` is the shared response-header policy for uploaded documents (the
# no-render rule plus the narrow PDF exception). Imported, never restated: a second copy
# of a security header policy is the worst kind of duplication this repo has. It lives in
# a stdlib-only module rather than in the server's corpus route, because importing that
# route reaches `app.config` and this host has no server settings to build (#50).
from app.services.delegation import delegates_to
from app.services.document_headers import download_headers, media_type_for
from app.services.error_responses import install_error_handlers
from app.services.event_stream import sse_frames
from app.services.run_config import apply_demo_rule, is_scripted
from app.services.session_events import lifecycle_event
from app.services.sse import SSE_HEADERS
from research_engine import bundle, catalog, citation_rate, outlines, prompts
from research_engine.build_info import build_info
from research_engine.corpus import CorpusStore
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
        self._logs: dict[str, list[tuple[int | None, dict]]] = {}
        self._listeners: dict[str, list[asyncio.Queue]] = {}

    def append(self, session_id: str, payload: dict, event_id: int | None) -> None:
        """Fan one event out live under the id it was durably given.

        The id is supplied, never generated here. This bus used to mint its own
        per-session counter starting at 1 while the backlog — what a reconnecting client
        replays — is framed with `agent_logs.id`, a global autoincrement: two id spaces for
        one `Last-Event-ID` cursor. A client that reconnected mid-run replayed the whole
        backlog again and then went silent, because every live id compared as
        already-seen against a much larger row id. The server never had this
        (`adapters.agent_log_sink` sets `event["id"] = row.id`), and now neither does this.

        `None` means the durable write failed, so the event has no replayable identity.
        It is still delivered — a live listener should see it — but it carries no cursor,
        and the stream generators leave `Last-Event-ID` where it was.
        """
        self._logs.setdefault(session_id, []).append((event_id, payload))
        for queue in self._listeners.get(session_id, []):
            queue.put_nowait((event_id, payload))

    def backlog(self, session_id: str, after_id: int = 0) -> list[tuple[int | None, dict]]:
        return [(i, p) for i, p in self._logs.get(session_id, []) if i is not None and i > after_id]

    @asynccontextmanager
    async def subscribe(self, session_id: str) -> AsyncGenerator[asyncio.Queue, None]:
        queue: asyncio.Queue = asyncio.Queue()
        self._listeners.setdefault(session_id, []).append(queue)
        try:
            yield queue
        finally:
            self._listeners.get(session_id, []).remove(queue)


async def persist_and_publish(
    session_factory: async_sessionmaker,
    bus: SessionEventBus,
    session_id: str | uuid.UUID,
    payload: dict,
) -> None:
    """Write the durable row, take its id as the cursor, then fan out live.

    The one home for that ordering on this host — the event sink and both lifecycle
    publishers call it, and every one of them used to get the order wrong in the same way
    (mint a bus id, deliver, then insert a row with a different id).

    Row first is what the server's sink does too (`adapters.agent_log_sink`) and it is
    load-bearing twice over: the id a live listener sees has to be the id that event will
    replay under, and a client that acts on a terminal event must never re-read a state
    that has not been committed.
    """
    row_id: int | None = None
    try:
        async with session_factory() as db:
            row = AgentLog(
                session_id=uuid.UUID(str(session_id)),
                event_type=payload.get("type") or "agent_log",
                agent_name=payload.get("agent"),
                # A copy, deliberately: the row must not hold the caller's dict. Mutating
                # one object and then assigning it back leaves SQLAlchemy with an old value
                # equal to the new one and no net change to write, which is why the stored
                # `id` stayed null through two attempts at this.
                payload=dict(payload),
            )
            db.add(row)
            await db.flush()
            row_id = row.id
            payload["id"] = row_id
            row.payload = dict(payload)
            await db.commit()
    except Exception as e:  # noqa: BLE001 — live delivery must not die on persistence
        logger.warning("sidecar_event_persist_failed", session_id=str(session_id), error=str(e))
    bus.append(str(session_id), payload, row_id)


class UnavailableMemoryIndex:
    """`MemoryIndex` for a host that has no project memory.

    `memory_chunks` is pgvector-backed and excluded from this host's `create_all`
    (`POSTGRES_ONLY_TABLES`), so there is nothing to search. Raising names the missing
    capability; returning `[]` would say "this project has nothing indexed", which is a
    different and false claim and the shape that makes an absent feature look like a
    working one.
    """

    available = False

    async def nearest(self, db, *, project_id, query_vector, embedding_model, limit):  # noqa: ARG002
        from app.errors import CapabilityUnavailable

        raise CapabilityUnavailable(
            "Project memory is not available on the desktop app: it is backed by pgvector, "
            "which this host does not have.",
            capability="project_memory",
        )


async def bus_events(bus: SessionEventBus, session_id: str):
    """This host's live feed as `(id, payload)` pairs — the shape `sse_frames` consumes.

    The desktop's half of the infrastructure difference: an in-process queue where the
    server has Redis pub/sub. Everything downstream of it is shared.
    """
    async with bus.subscribe(session_id) as queue:
        while True:
            yield await queue.get()


class PersistingSink:
    """The run's EventSink. Durable row first, then live delivery — see `persist_and_publish`."""

    def __init__(self, bus: SessionEventBus, session_factory: async_sessionmaker) -> None:
        self.bus = bus
        self._session_factory = session_factory

    async def __call__(self, session_id: str, event_payload: dict) -> None:
        await persist_and_publish(self._session_factory, self.bus, session_id, event_payload)


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


# Corpus-only mode used to be a persistent per-app switch here, written to `corpus.json`
# by `PUT /corpus/mode` and read into every run's `RunConfig`. It is gone, and the desktop
# takes `corpus_mode` per run exactly as the server does.
#
# Two things were wrong with the switch, in opposite directions. Nothing in `frontend/`
# ever referenced `corpus_only` or called `PUT /corpus/mode`, so the state could not be set
# or seen by a user — the class AGENTS.md records for bundle export, "a shipped control
# that 404'd" turned inside out. And because the switch was the *only* input to
# `RunConfig.corpus_mode` on this host, the `corpus_mode` a request set and the session row
# stored was never read: a run asked for as airgapped was recorded as airgapped and
# executed over the open web. `app/schemas/research.py` names that exact class.


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
        return RunConfig(llm_mode="fake", demo=demo, models=models)

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

    class _DesktopCorpusLocator:
        """`CorpusLocator` for the desktop: one flat store for the whole app.

        `for_project`/`ensure` ignore `project_id` on purpose — there is only ever the one
        store, `state["corpus"]`, seeded in `lifespan`. `paths_to_delete`/`delete` are
        no-ops for the same reason `delete_project`'s docstring already gave before this
        class existed: nothing here is project-scoped on disk to orphan. Keeping that as
        the locator's own behaviour, rather than a branch in the route, is what lets
        `delete_project` run unmodified on both hosts.
        """

        async def for_project(self, project_id, *, keys=None):  # noqa: ARG002
            return state["corpus"]

        async def ensure(self, project_id, *, keys=None):  # noqa: ARG002
            return state["corpus"]

        def paths_to_delete(self, project_id):  # noqa: ARG002
            return []

        def delete(self, project_id) -> None:  # noqa: ARG002
            pass

    def get_corpus_locator() -> CorpusLocator:
        return _DesktopCorpusLocator()

    def get_checkpoint_deleter() -> CheckpointDeleter:
        """The already-open `AsyncSqliteSaver`, wrapped to the port's plain-callable
        shape. Best-effort by the same convention `delete_project` already applied
        inline before this seam existed — logged and swallowed, not raised, because the
        row it is cleaning up after is already gone by the time this runs."""

        async def _delete(thread_id: str) -> None:
            await state["saver"].adelete_thread(thread_id)

        return _delete

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
    # The same table the server installs. The run handlers this host imports raise domain
    # errors, so without it every refusal would surface as an unhandled 500 here.
    install_error_handlers(app)
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

    @api.get("/capabilities", response_model=Capabilities)
    async def capabilities() -> Capabilities:
        """The desktop's answer, from the same shape the server serves.

        A constant rather than something probed at request time: every one of these is a
        property of how this host is built, not of its current state. `project_memory` is
        false because `memory_chunks` is pgvector-backed and excluded from this host's
        schema, and that cannot become true while the app is running.
        """
        return DESKTOP

    @api.get("/version")
    async def version():
        """The same payload the server serves, from the same reader.

        This is what makes an installed `.dmg` traceable: a developer opens Settings and
        reads the commit that produced the bundle they are running. It is behind the
        per-launch token like every other route here — not because the contents are
        sensitive, but because this host's boundary is "one token, no exceptions" and a
        second rule is a second thing to get wrong (docs/13 §7).
        """
        return build_info().as_dict()

    @api.get("/auth/me", response_model=UserResponse)
    async def me(user: User = Depends(get_local_user)):
        """The frontend boots on this call. Desktop has exactly one user and no password.

        The row is returned and `UserResponse` projects it, rather than a dict assembled
        here. The dict omitted `is_active`, every `api_key_*` field, `connection_verdict`
        and the whole `preferences` object the server's model declares — so the same
        TypeScript type read two different shapes, and nothing failed in between. Keys live
        in the keychain on this host, so the BYOK fields stay at their `None` defaults;
        that is a value, not an absence.
        """
        return user

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

    @api.patch("/auth/me", response_model=UserResponse)
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
        return user

    # -- projects -------------------------------------------------------------

    @api.get("/projects", response_model=ProjectListResponse)
    @delegates_to("app.api.v1.projects:list_projects")
    async def list_projects(
        archived: bool = False,
        db: AsyncSession = Depends(get_db),
        user: User = Depends(get_local_user),
    ):
        """The server's route, byte for byte — including the count across both the v1
        session table and v2 research runs. The desktop's own copy counted sessions
        only, so a project with a run and no session showed `session_count: 0` (found by
        actually creating one and listing, not by reading the two versions side by side).
        """
        from app.api.v1.projects import list_projects

        return await list_projects(archived, db, user)

    @api.post("/projects", response_model=ProjectResponse, status_code=201)
    @delegates_to("app.api.v1.projects:create_project")
    async def create_project(
        payload: ProjectCreateRequest,
        db: AsyncSession = Depends(get_db),
        user: User = Depends(get_local_user),
    ):
        from app.api.v1.projects import create_project

        return await create_project(payload, db, user)

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
    @delegates_to("app.api.v1.projects:update_project")
    async def update_project(
        project_id: uuid.UUID,
        payload: ProjectUpdateRequest,
        db: AsyncSession = Depends(get_db),
        user: User = Depends(get_local_user),
    ):
        """Rename, re-describe, or archive/unarchive a project — the server's route.

        This route did not exist for a whole release; `INTENTIONAL_SERVER_ONLY` in
        test_host_parity.py justified the gap as "the UI never calls it" — true only
        as long as no shared component did. `ProjectsSection.tsx` now does, on both
        hosts, which is what makes the justification stop being true and this route
        required rather than optional.
        """
        from app.api.v1.projects import update_project

        return await update_project(project_id, payload, db, user)

    @api.delete("/projects/{project_id}", status_code=204)
    @delegates_to("app.api.v1.projects:delete_project")
    async def delete_project(
        project_id: uuid.UUID,
        db: AsyncSession = Depends(get_db),
        user: User = Depends(get_local_user),
    ):
        """Delete a project and every session in it — the server's route, given this
        host's own corpus locator and checkpoint deleter explicitly (the pattern
        `_dispatcher` already uses) rather than through `Depends`, which the sidecar
        never triggers for a delegated call. `_DesktopCorpusLocator.delete` is a no-op:
        desktop's corpus is one flat `corpus.sqlite` for the whole app, not one file per
        project like the server's `corpus_<project_id>.sqlite` — a real, documented
        infra difference (AGENTS.md), not a gap. There is nothing project-scoped on disk
        here to orphan.
        """
        from app.api.v1.projects import delete_project

        return await delete_project(
            project_id, db, user, get_corpus_locator(), get_checkpoint_deleter()
        )

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

        # One mapping, shared with `pipeline_runner._persist_outcome`. This used to be a
        # second dict literal here, publishing the right event type with `data: null` —
        # so a desktop client saw the gate but none of the numbers the server sends with it.
        await persist_and_publish(
            session_factory, app.state.sidecar["bus"], session.id, lifecycle_event(outcome)
        )

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
            # The demo rule is `app/services/run_config.py`, shared with the server's two
            # workers. `is_scripted` is needed before the config exists because
            # `sidecar_run_config` takes a different branch for a scripted run; the row is
            # corrected below, once the config it describes has been built.
            row_demo = bool(session.demo)
            is_demo = is_scripted(row_demo=row_demo, host_is_scripted=bool(app.state.fake))
            # RUNNING is the driver's to set, exactly as `pipeline_runner._execute` does.
            # The route creates the row PENDING and hands it over; without this the desktop
            # left a session showing "Pending" for the whole of its run while the server
            # showed "Running" for the same request.
            session.status = SessionStatus.RUNNING
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
                # Read from the row for the same reason as the rest of this dict: it is
                # rebuilt on every resume, long after the request is gone. Server
                # counterpart: `pipeline_runner._execute`, which branches on
                # `session.corpus_mode`.
                "corpus_mode": bool(session.corpus_mode),
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
                fake=is_demo,
                demo=is_demo,
                data_dir=app.state.data_dir,
                session_routing=session_routing,
            )
            config, needs_stamp = apply_demo_rule(
                config, row_demo=row_demo, host_is_scripted=bool(app.state.fake)
            )
            if needs_stamp:
                async with session_factory() as db:
                    row = await _authorized_session(db, session_id, sidecar["user_id"])
                    row.demo = True
                    await db.commit()
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
            await persist_and_publish(
                session_factory, sidecar["bus"], session_id, make_event("FAILED", message=str(e))
            )
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
                row_demo = bool(run.demo)
                is_demo = is_scripted(row_demo=row_demo, host_is_scripted=bool(app.state.fake))
                overrides = {
                    "skip_plan_gate": bool(run.skip_plan_gate),
                    "topic_seeds": tuple(run.topic_seeds or ()),
                    "outline_template": run.outline_template,
                    # Server counterpart: `run_execution.execute_run`, which branches on
                    # `run.corpus_mode`.
                    "corpus_mode": bool(run.corpus_mode),
                }
                question, depth = run.question, run.depth
                run_routing = run.model_routing
                await run_lifecycle.set_status(db, run, "RUNNING")
                await db.commit()

            try:
                config = sidecar_run_config(
                    fake=is_demo,
                    demo=is_demo,
                    data_dir=app.state.data_dir,
                    session_routing=run_routing,
                )
                config, needs_stamp = apply_demo_rule(
                    config, row_demo=row_demo, host_is_scripted=bool(app.state.fake)
                )
                config = replace(config, **overrides)
                if needs_stamp:
                    async with session_factory() as db:
                        row = await db.get(ResearchRun, run_id)
                        row.demo = True
                        await db.commit()
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

    class _SidecarSessionDispatcher:
        """`SessionDispatcher` for this host: an asyncio task instead of a broker message.

        The session counterpart of `_SidecarDispatcher`, and it exists for the same reason:
        with it, the handlers in `app/api/v1/research.py` can be shared verbatim, so every
        ordering rule they encode holds identically on both hosts instead of being restated
        here and kept in step by hand.
        """

        async def start(self, session_id: str, user_id: str) -> None:
            asyncio.create_task(_drive_session(uuid.UUID(session_id), approved=None, feedback=None))

        async def resume_plan(self, session_id: str, user_id: str, plan: dict) -> None:
            asyncio.create_task(_drive_session(uuid.UUID(session_id), plan=plan))

        async def resume_review(self, session_id, user_id, approved, feedback) -> None:
            asyncio.create_task(
                _drive_session(uuid.UUID(session_id), approved=approved, feedback=feedback)
            )

    _session_dispatcher = _SidecarSessionDispatcher()

    @api.post("/research", response_model=ResearchStartResponse, status_code=202)
    @delegates_to("app.api.v1.research:start_research")
    async def start_research(
        payload: ResearchStartRequest,
        db: AsyncSession = Depends(get_db),
        user: User = Depends(get_local_user),
    ):
        """`_rl=None`: the rate-limit dependency is a server concern this host does not
        have (`rate_limits: false` in its capabilities), and passing None is how a
        positional call declines a `Depends` it does not want.
        """
        from app.api.v1.research import start_research

        return await start_research(payload, db, user, None, _session_dispatcher)
    @api.get("/research", response_model=SessionListResponse)
    @delegates_to("app.api.v1.research:list_sessions")
    async def list_sessions(
        page: int = 1,
        limit: int = 20,
        archived: bool = False,
        project_id: uuid.UUID | None = None,
        db: AsyncSession = Depends(get_db),
        user: User = Depends(get_local_user),
    ):
        from app.api.v1.research import list_sessions

        return await list_sessions(page, limit, archived, project_id, db, user)
    @api.get("/research/{session_id}", response_model=SessionDetail)
    @delegates_to("app.api.v1.research:get_session")
    async def get_session(
        session_id: uuid.UUID,
        db: AsyncSession = Depends(get_db),
        user: User = Depends(get_local_user),
    ):
        from app.api.v1.research import get_session

        return await get_session(session_id, db, user)
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
            # The loop is `app/services/event_stream.py`, shared with the server's two
            # streams and this host's run stream. Only the live feed differs.
            async for frame in sse_frames(
                connected={"type": "connected"},
                backlog=backlog,
                live=bus_events(bus, str(session_id)),
                replay_stop=_REPLAY_STOP_EVENTS,
                terminal_stop=_TERMINAL_EVENTS,
                already_done=already_done,
                seen_from=after_id,
            ):
                yield frame

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
    @delegates_to("app.api.v1.research:get_plan")
    async def get_plan(
        session_id: uuid.UUID,
        db: AsyncSession = Depends(get_db),
        user: User = Depends(get_local_user),
    ):
        from app.api.v1.research import get_plan

        return await get_plan(session_id, db, user)
    @api.post("/research/{session_id}/plan", response_model=PlanResponse)
    @delegates_to("app.api.v1.research:submit_plan")
    async def submit_plan(
        session_id: uuid.UUID,
        payload: PlanDecisionRequest,
        db: AsyncSession = Depends(get_db),
        user: User = Depends(get_local_user),
    ):
        """The design gate. Every rule it encodes — the 409 when the thread is not
        suspended at the matching interrupt, "None means unedited", writing the decision
        before resuming — is the server's, not a second copy kept in step by hand.
        """
        from app.api.v1.research import submit_plan

        return await submit_plan(session_id, payload, db, user, _session_dispatcher)
    @api.post("/research/{session_id}/approve")
    @delegates_to("app.api.v1.research:approve_or_rework")
    async def approve_or_rework(
        session_id: uuid.UUID,
        payload: ApprovalRequest,
        db: AsyncSession = Depends(get_db),
        user: User = Depends(get_local_user),
    ):
        from app.api.v1.research import approve_or_rework

        return await approve_or_rework(session_id, payload, db, user, _session_dispatcher)
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
    @delegates_to("app.api.v1.research:export_markdown")
    async def export_markdown(
        session_id: uuid.UUID,
        db: AsyncSession = Depends(get_db),
        user: User = Depends(get_local_user),
    ):
        from app.api.v1.research import export_markdown

        return await export_markdown(session_id, db, user)
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
        await persist_and_publish(
            session_factory,
            app.state.sidecar["bus"],
            session_id,
            make_event("FAILED", message="Research stopped by user."),
        )

        logger.info("sidecar_research_stopped_by_user", session_id=str(session_id))
        return SessionSummary.model_validate(session)

    @api.post("/research/{session_id}/archive", response_model=SessionSummary)
    @delegates_to("app.api.v1.research:archive_session")
    async def archive_session(
        session_id: uuid.UUID,
        db: AsyncSession = Depends(get_db),
        user: User = Depends(get_local_user),
    ):
        from app.api.v1.research import archive_session

        return await archive_session(session_id, db, user)
    @api.post("/research/{session_id}/unarchive", response_model=SessionSummary)
    @delegates_to("app.api.v1.research:unarchive_session")
    async def unarchive_session(
        session_id: uuid.UUID,
        db: AsyncSession = Depends(get_db),
        user: User = Depends(get_local_user),
    ):
        from app.api.v1.research import unarchive_session

        return await unarchive_session(session_id, db, user)
    @api.delete("/research/{session_id}", status_code=204)
    @delegates_to("app.api.v1.research:delete_session")
    async def delete_session(
        session_id: uuid.UUID,
        db: AsyncSession = Depends(get_db),
        user: User = Depends(get_local_user),
    ):
        from app.api.v1.research import delete_session

        return await delete_session(session_id, db, user)
    @api.get("/models", response_model=CatalogResponse)
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

    @api.post("/models/providers/test", response_model=ConnectionVerdict)
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

    @api.get("/models/local/status", response_model=LocalLLMStatusResponse)
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

    @api.get("/models/custom/status", response_model=CustomEndpointStatusResponse)
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

    @api.get("/models/routing", response_model=RoutingResponse)
    async def get_routing(user: User = Depends(get_local_user)):  # noqa: ARG001
        """The saved routing and the one a run would dial. Second home of the server's
        `GET /models/routing` — both hosts shipped this trio write-only (PUT and DELETE
        but no GET) while the frontend already fetched it, so the read 405'd on both.

        `routing` is null when nothing is saved, distinct from `effective_routing`, which
        always resolves — see the server's docstring for why the two must not collapse.
        """
        saved = stored_routing(app.state.data_dir)
        return {"routing": saved or None, "effective_routing": _effective_with(saved or None)}

    @api.put("/models/routing", response_model=RoutingResponse)
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

    @api.delete("/models/routing", response_model=RoutingResponse)
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

    # `_document_response` and `_corpus_status_response` used to be shaped here, by hand,
    # against the server's field names from memory. They are `corpus_ingest`'s job now —
    # one mapping, both hosts.

    @api.post("/corpus/documents", status_code=201)
    async def upload_document(request: Request, filename: str):
        """Ingest one PDF/MD/TXT into the corpus.

        Raw bytes in the body, name in the query — deliberately not multipart, so the
        frozen bundle needs no python-multipart. Errors stay fail-closed: an
        unsupported format or an unreachable embedding server is a 4xx/5xx, never a
        silent skip.
        """
        return await corpus_ingest.ingest_document(_corpus(), filename, await request.body())

    @api.get("/corpus/documents", response_model=list[DocumentResponse])
    async def list_corpus_documents():
        return [corpus_ingest.document_response(d) for d in await _corpus().documents()]

    @api.delete("/corpus/documents/{doc_id}", status_code=204)
    async def delete_corpus_document(doc_id: str):
        if not await _corpus().delete(doc_id):
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail=corpus_ingest.DOCUMENT_NOT_FOUND)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @api.get("/corpus/status", response_model=CorpusStatusResponse)
    async def corpus_status():
        return corpus_ingest.status_response(await _corpus().status())

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

    @api.get("/projects/{project_id}/corpus/documents", response_model=list[DocumentResponse])
    async def list_project_corpus_documents(
        project_id: uuid.UUID,
        db: AsyncSession = Depends(get_db),
        user: User = Depends(get_local_user),
    ):
        await _resolve_project(db, user.id, project_id)
        return [corpus_ingest.document_response(d) for d in await _corpus().documents()]

    @api.get("/projects/{project_id}/corpus/status", response_model=CorpusStatusResponse)
    async def project_corpus_status(
        project_id: uuid.UUID,
        db: AsyncSession = Depends(get_db),
        user: User = Depends(get_local_user),
    ):
        await _resolve_project(db, user.id, project_id)
        return corpus_ingest.status_response(await _corpus().status())

    @api.post(
        "/projects/{project_id}/corpus/documents", status_code=201, response_model=DocumentResponse
    )
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
        return await corpus_ingest.ingest_document(_corpus(), file.filename, await file.read())

    @api.delete("/projects/{project_id}/corpus/documents/{doc_id}", status_code=204)
    async def delete_project_corpus_document(
        project_id: uuid.UUID,
        doc_id: str,
        db: AsyncSession = Depends(get_db),
        user: User = Depends(get_local_user),
    ):
        await _resolve_project(db, user.id, project_id)
        if not await _corpus().delete(doc_id):
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail=corpus_ingest.DOCUMENT_NOT_FOUND)
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
        # `media_type` is not optional here: `download_headers` sets
        # `X-Content-Type-Options: nosniff`, so a response with no declared type forbids
        # the browser from guessing one. The desktop omitted it and served every document
        # untyped.
        return Response(
            content=data,
            media_type=media_type_for(kind),
            headers=download_headers(kind, filename),
        )

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
    @delegates_to("app.api.v1.runs:create_run")
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
    @delegates_to("app.api.v1.runs:list_runs")
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
    @delegates_to("app.api.v1.runs:get_run")
    async def v2_get_run(
        run_id: uuid.UUID,
        db: AsyncSession = Depends(get_db),
        user: User = Depends(get_local_user),
    ):
        # `get_run` rather than `project_run`: this used to restate the server route's own
        # two lines — resolve-then-project — which is a second implementation of the
        # ownership check, however short.
        from app.api.v1.runs import get_run

        return await get_run(run_id, db, user)

    @api.post("/runs/{run_id}/plan-review", status_code=201)
    @delegates_to("app.api.v1.runs:submit_plan_review")
    async def v2_submit_plan_review(
        run_id: uuid.UUID,
        body: V2PlanReviewRequest,
        db: AsyncSession = Depends(get_db),
        user: User = Depends(get_local_user),
    ):
        from app.api.v1.runs import submit_plan_review

        return await submit_plan_review(run_id, body, db, user, dispatcher=_dispatcher)

    @api.post("/runs/{run_id}/report-review", status_code=201)
    @delegates_to("app.api.v1.runs:submit_report_review")
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
            async for frame in sse_frames(
                connected={"type": "connected", "run_id": str(run_id)},
                backlog=backlog,
                live=bus_events(bus, str(run_id)),
                replay_stop=V2_REPLAY_STOP,
                terminal_stop=V2_TERMINAL,
                already_done=already_done,
                seen_from=after_id,
            ):
                yield frame

        return StreamingResponse(gen(), media_type="text/event-stream", headers=SSE_HEADERS)

    @api.get("/runs/{run_id}/export.md")
    @delegates_to("app.api.v1.runs:export_markdown")
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
    @delegates_to("app.api.v1.runs:cancel_run")
    async def v2_cancel_run(
        run_id: uuid.UUID,
        db: AsyncSession = Depends(get_db),
        user: User = Depends(get_local_user),
    ):
        from app.api.v1.runs import cancel_run

        return await cancel_run(run_id, db, user)

    @api.post("/runs/{run_id}/archive")
    @delegates_to("app.api.v1.runs:archive_run")
    async def v2_archive_run(
        run_id: uuid.UUID,
        db: AsyncSession = Depends(get_db),
        user: User = Depends(get_local_user),
    ):
        from app.api.v1.runs import archive_run

        return await archive_run(run_id, db, user)

    @api.post("/runs/{run_id}/unarchive")
    @delegates_to("app.api.v1.runs:unarchive_run")
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
    @delegates_to("app.api.v1.runs:get_bundle")
    async def v2_get_bundle(
        run_id: uuid.UUID,
        db: AsyncSession = Depends(get_db),
        user: User = Depends(get_local_user),
    ):
        from app.api.v1.runs import get_bundle

        return await get_bundle(run_id, db, user)

    @api.get("/runs/{run_id}/verification")
    @delegates_to("app.api.v1.runs:get_verification")
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
