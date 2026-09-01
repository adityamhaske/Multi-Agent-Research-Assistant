"""
One host, made drivable in-process. **Not a test module.**

Both drivers expose the same thing — an `httpx.AsyncClient` speaking `/api/v1` to a real
application object — so a journey is written once and run twice. Everything a driver does
beyond that is *pinning*, and each pin is here for a stated reason:

- **The same scripted models on both.** `conftest` exports `MODEL_*` for every role, the
  server reads them through `Settings`, and `sidecar_run_config` reads them directly. So
  routing is already identical, and the normalizer compares cost and `model_routing`
  exactly rather than reducing them (plan §8.2).
- **The same deterministic embedder on both.** `Embeddings` is a port with a real host
  difference — hosted on the server, local on the desktop — which would make every
  `chunks_by_model` disagree for a reason that is not a defect. Injecting one fake on both
  sides replaces the *port*, not the code under test: the corpus store, the ingestion path
  and the routes stay real.
- **No first-launch demo on the desktop.** The sidecar seeds a demo session on first
  launch and the server has no counterpart, so leaving it on would make every session
  listing diverge over a product feature rather than a defect. Suppressed through the
  app's own `mark_demo_seeded`, not by reaching into its internals.

**What the server driver does NOT measure, stated plainly.** It overrides
`get_run_dispatcher` with an in-process dispatcher, so a run is driven by
`run_execution` against a SQLite saver instead of by a Celery worker against Postgres.
That swaps the one mechanism `app/run_dispatch.py` already declares as host-specific, and
nothing else — the handlers, `run_config_for_run`, the engine and `persist_outcome` are
the server's own. The Celery path stays covered by the `golden-e2e` job.

**The session path now has the same seam.** It did not: `POST /research` called
`app.workers.tasks.*.delay` directly, so the server could not drive a session in-process at
all and session journeys were skipped on that host. `SessionDispatcher` is the first rung of
the plan's Phase 7 ladder — the baseline that lets everything after it be measured, because
a move cannot be proved behaviour-preserving against a behaviour nobody recorded.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from research_engine.runconfig import ROLES

TOKEN = "parity-token"

#: The one embedder both hosts get. `is_local = True` is truthful, not a convenience —
#: it computes in-process and opens no socket, so the corpus airgap guard is satisfied
#: honestly rather than bypassed.
EMBEDDER_NAME = "parity-embed"

#: Capabilities each host claims. Until `GET /capabilities` exists (plan Phase 10) this is
#: the harness's own record of the product-design differences, and a journey that needs one
#: declares it — so a capability difference skips a journey visibly instead of quietly
#: producing an empty result both hosts agree on.
SERVER_CAPABILITIES = frozenset({"project_memory", "project_chat", "server_pdf", "rate_limits"})
DESKTOP_CAPABILITIES = frozenset({"local_llm_control"})


@dataclass
class Driver:
    """One host, ready to be driven."""

    name: str
    client: httpx.AsyncClient
    #: "postgres" or "sqlite". Journeys that need pgvector declare it, because a server on
    #: SQLite reports project memory as absent — agreeing with the desktop for the wrong
    #: reason, which is the degenerate pass `tests/parity/liveness.py` exists to refuse.
    backing: str
    capabilities: frozenset[str] = field(default_factory=frozenset)
    #: True when this host can start and finish a run inside the test process.
    run_driver: bool = False

    async def request(self, method: str, path: str, **kw) -> httpx.Response:
        return await self.client.request(method, f"/api/v1{path}", **kw)


def _embedder():
    from tests.dataflow.test_corpus_store import FakeEmbeddings

    return FakeEmbeddings(EMBEDDER_NAME)


def pinned_routing() -> dict[str, str]:
    """What both hosts will resolve to, read from the same place each of them reads."""
    import os

    return {role: os.environ[f"MODEL_{role.upper()}"] for role in ROLES}


def pin_local_llm_probe():
    """Make `GET /models` see one fixed local model server. Returns the previous probe.

    `_ollama_presets_from_installed()` builds `presets["ollama"]` from whatever Ollama is
    *actually reachable at request time* — a live localhost call, and the last unpinned
    input to a recorded contract. The golden's ollama preset names `llama3.2:latest` and
    `qwen2.5-coder:14b` because the machine that recorded it had exactly those pulled;
    anywhere else — CI, or any laptop without Ollama running — the helper returns `None`,
    `presets` comes back with no `ollama` key at all (`catalog.PRESETS` is static
    anthropic + google), and the step diverges for a reason that has nothing to do with
    the code under test.

    The two models below reproduce the recorded preset exactly, and are chosen to exercise
    the selection rather than hand it one answer: `fast` must pick the smallest chat model
    and `balanced`/`best` the largest *research-ready* one, so a 3B tagged underpowered and
    a 14B that is not are the smallest case where "smallest" and "strongest" differ and the
    `likely_underpowered` filter is load-bearing.

    Pinned for **both** hosts, like `_embedder`: the desktop calls this same helper now
    (plan phase 8 — its catalog used to return the static table and could offer a model
    the machine never pulled), so leaving the probe live would leave the same
    nondeterminism on that side, latent behind an `XFAIL_DIVERGENCES` entry.
    """
    from app.services import local_llm

    installed = [
        local_llm.LocalModel(
            name="llama3.2:latest",
            route="ollama:llama3.2",
            in_catalog=True,
            likely_underpowered=True,
            params_b=3.0,
        ),
        local_llm.LocalModel(
            name="qwen2.5-coder:14b",
            route="ollama:qwen2.5-coder",
            in_catalog=True,
            likely_underpowered=False,
            params_b=14.0,
        ),
    ]

    async def _probe(base_url=None):  # noqa: ARG001 - matches the real signature
        return local_llm.LocalLLMStatus(
            configured_base_url="http://localhost:11434/v1",
            reachable=True,
            models=installed,
            install_state="running",
        )

    previous = local_llm.probe
    local_llm.probe = _probe
    return previous


# ── Desktop ───────────────────────────────────────────────────────────────────────


@asynccontextmanager
async def desktop_driver(data_dir: Path):
    from desktop import sidecar as sidecar_module
    from desktop.sidecar import create_sidecar_app, mark_demo_seeded

    data_dir.mkdir(parents=True, exist_ok=True)
    mark_demo_seeded(data_dir)

    # `make_corpus_store` constructs `LocalEmbeddings` on every call, and it is called in
    # more than one place — the lifespan builds one store and the report auto-ingest builds
    # another. Substituting the class is what makes *every* store this host opens use the
    # same deterministic embedder; assigning to the one instance the lifespan happened to
    # create leaves the others pointing at Ollama.
    shared = _embedder()
    previous_local_embeddings = sidecar_module.LocalEmbeddings
    sidecar_module.LocalEmbeddings = lambda **_kw: shared
    previous_probe = pin_local_llm_probe()

    app = create_sidecar_app(data_dir=data_dir, token=TOKEN, fake=True)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://desktop.invalid",
            headers={"Authorization": f"Bearer {TOKEN}"},
        ) as client:
            try:
                yield Driver(
                    name="desktop",
                    client=client,
                    backing="sqlite",
                    capabilities=DESKTOP_CAPABILITIES,
                    run_driver=True,
                )
            finally:
                sidecar_module.LocalEmbeddings = previous_local_embeddings
                from app.services import local_llm

                local_llm.probe = previous_probe


# ── Server ────────────────────────────────────────────────────────────────────────


def _agent_log_sink(session_factory):
    """The `EventSink` port, writing the durable half only.

    The server's own sink (`adapters.agent_log_sink`) writes an `agent_logs` row and then
    publishes to Redis; this host has no Redis. Only the *durable* half is product
    behaviour that survives the request — it is what SSE replay reads and what a bundle's
    `trace` is assembled from — so omitting the sink entirely is not an option: the server
    would emit no trace, the desktop would emit a full one, and the harness would report
    its own gap as a product divergence.
    """
    import asyncio

    from app.models.agent_log import AgentLog

    # Serialised for the same reason the server's own sink is: once the executor runs tasks
    # in parallel, two of them reach the sink at once, and `Last-Event-ID` replay hands
    # clients a cursor that has to be monotonic.
    write_lock = asyncio.Lock()

    async def sink(session_id: str, event: dict) -> None:
        async with write_lock, session_factory() as db:
            row = AgentLog(
                session_id=uuid.UUID(session_id),
                event_type=event.get("type", "agent_log"),
                agent_name=event.get("agent"),
                payload=event,
            )
            db.add(row)
            await db.flush()
            event["id"] = row.id
            await db.commit()

    return sink


class _InProcessSessionDispatcher:
    """`SessionDispatcher` for the harness — the server's own session worker, no broker.

    Deliberately not the desktop's `_drive_session`: reusing that would make the "server"
    host literally the desktop implementation, and the comparison would prove nothing.
    This drives `research_engine.runner` with the config `pipeline_runner` resolves and
    persists through `pipeline_runner._persist_outcome`, which is what the Celery task does.
    """

    def __init__(self, session_factory, saver) -> None:
        self._sessions = session_factory
        self._saver = saver
        self._sink = _agent_log_sink(session_factory)
        self._tasks: set = set()

    def _spawn(self, coro) -> None:
        import asyncio

        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _drive(self, session_id: str, user_id: str, *, resume=None, plan=None) -> None:
        from app.models.session import Session, SessionStatus
        from app.workers import pipeline_runner
        from research_engine import runner

        async with self._sessions() as db:
            session = await db.get(Session, uuid.UUID(session_id))
            if session is None:
                return
            session.status = SessionStatus.RUNNING
            await db.commit()
            config = await pipeline_runner._run_config_for(db, session, user_id)  # noqa: SLF001
            query, depth = session.prompt, session.research_depth

        ports = {"run_config": config, "event_sink": self._sink}
        if plan is not None:
            outcome = await runner.resume(
                checkpointer=self._saver, session_id=session_id, plan=plan, **ports
            )
        elif resume is None:
            outcome = await runner.run(
                checkpointer=self._saver,
                session_id=session_id,
                user_id=user_id,
                query=query,
                depth=depth,
                **ports,
            )
        else:
            approved, feedback = resume
            outcome = await runner.resume(
                checkpointer=self._saver,
                session_id=session_id,
                approved=approved,
                feedback=feedback,
                **ports,
            )

        async with self._sessions() as db:
            session = await db.get(Session, uuid.UUID(session_id))
            await pipeline_runner._persist_outcome(  # noqa: SLF001
                db, session, session_id, outcome, self._sink, {}
            )

    async def start(self, session_id: str, user_id: str) -> None:
        self._spawn(self._drive(session_id, user_id))

    async def resume_plan(self, session_id: str, user_id: str, plan: dict) -> None:
        self._spawn(self._drive(session_id, user_id, plan=plan))

    async def resume_review(self, session_id, user_id, approved, feedback) -> None:
        self._spawn(self._drive(session_id, user_id, resume=(approved, feedback)))


class _InProcessDispatcher:
    """`RunDispatcher` for the harness — the server's own adapter, no broker.

    Deliberately not the desktop's `_SidecarDispatcher`: reusing that would make the
    "server" host literally the desktop implementation and the comparison would prove
    nothing. This drives `run_execution` — which is what the Celery task drives — against
    a saver the test process can open.
    """

    def __init__(self, session_factory, saver) -> None:
        self._sessions = session_factory
        self._saver = saver
        self._sink = _agent_log_sink(session_factory)
        # Dispatch is fire-and-forget on BOTH hosts — Celery returns as soon as the message
        # is queued, and the sidecar's dispatcher creates a task. Awaiting the run here
        # instead would make `POST /runs` return a finished run on the server and a PENDING
        # one on the desktop: a timing difference the harness invented, reported as a
        # product divergence. The set keeps the tasks referenced; asyncio only holds weak
        # references, so a dropped one can be collected mid-run.
        self._tasks: set = set()

    def _spawn(self, coro) -> None:
        import asyncio

        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _drive(self, run_id: str, *, resume=None, plan=None) -> None:
        from app import run_execution, run_lifecycle
        from app.models.research import ResearchRun
        from research_engine import runner

        async with self._sessions() as db:
            run = await db.get(ResearchRun, uuid.UUID(run_id))
            if run is None or run.status == "CANCELLED":
                return
            config = await run_execution.run_config_for_run(db, run)
            question, depth = run.question, run.depth
            await run_lifecycle.set_status(db, run, "RUNNING")
            await db.commit()

        ports = {"run_config": config, "event_sink": self._sink}
        if plan is not None:
            outcome = await runner.resume(
                checkpointer=self._saver, session_id=run_id, plan=plan, **ports
            )
        elif resume is None:
            outcome = await runner.run(
                checkpointer=self._saver,
                session_id=run_id,
                user_id="parity",
                query=question,
                depth=depth,
                **ports,
            )
        else:
            approved, feedback = resume
            outcome = await runner.resume(
                checkpointer=self._saver,
                session_id=run_id,
                approved=approved,
                feedback=feedback,
                **ports,
            )

        async with self._sessions() as db:
            run = await db.get(ResearchRun, uuid.UUID(run_id))
            await run_execution.persist_outcome(db, run, outcome, saver=self._saver)
            await db.commit()

    async def start(self, run_id: str, user_id: str) -> None:
        self._spawn(self._drive(run_id))

    async def resume_plan(self, run_id: str, user_id: str, plan: dict) -> None:
        self._spawn(self._drive(run_id, plan=plan))

    async def rework(self, run_id: str, user_id: str, feedback: str | None) -> None:
        self._spawn(self._drive(run_id, resume=(False, feedback)))


@asynccontextmanager
async def server_driver(data_dir: Path):
    from fastapi import Depends
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    from sqlalchemy import insert
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.config import settings
    from app.db.base import get_db
    from app.dependencies import (
        enforce_chat_rate_limit,
        enforce_research_rate_limit,
        get_current_user,
    )
    from app.main import app as server_app
    from app.models.user import User
    from app.workers.dispatch import get_run_dispatcher, get_session_dispatcher
    from tests.sqlite_support import open_db

    data_dir.mkdir(parents=True, exist_ok=True)

    async with open_db(data_dir / "server.sqlite") as session_factory:
        user_id = uuid.uuid4()
        async with session_factory() as db:
            await db.execute(
                insert(User).values(
                    id=user_id, email="parity@server.invalid", hashed_pw="!", is_active=True
                )
            )
            await db.commit()

        async def _db():
            async with session_factory() as db:
                try:
                    yield db
                    await db.commit()
                except Exception:
                    await db.rollback()
                    raise

        # Resolved through the *overridden* `get_db`, so the identity a route reads is
        # attached to that request's session. Loading it from a second session instead
        # hands the route a detached instance, and the first `refresh` raises
        # "Instance is not persistent within this Session" — a harness bug that would read
        # as a server defect.
        async def _user(db: AsyncSession = Depends(get_db)) -> User:
            return await db.get(User, user_id)

        saver_cm = AsyncSqliteSaver.from_conn_string(str(data_dir / "checkpoints.sqlite"))
        saver = await saver_cm.__aenter__()
        await saver.setup()

        # Scripted models, stated by the driver rather than inherited from the environment.
        # The desktop driver passes `fake=True` explicitly and this one used to rely on
        # `conftest` exporting `LLM_MODE=fake` — so running the harness outside pytest
        # reached the developer's real provider keys, spent real money, and produced a
        # golden full of live model output. A driver that can only be trusted inside one
        # test runner is not a driver; pin it here.
        previous_llm_mode = settings.llm_mode
        settings.llm_mode = "fake"

        # Which providers are *reachable*, stated here for the same reason `llm_mode` is.
        # `model_routing.available_providers` reads these settings, and `GET /models`
        # reports them as `available_providers` plus a per-model `available` flag — so the
        # catalog's recorded contract silently depended on whether whoever ran the harness
        # happened to have `GOOGLE_API_KEY` and `CUSTOM_BASE_URL` in their `.env`. The
        # golden was recorded on a machine that did; CI has neither, so it read
        # `['ollama']` against a golden saying `['custom', 'google', 'ollama']` and the
        # server journey failed there and only there. `XFAIL_DIVERGENCES` had already
        # named this — "which the harness does not yet pin" — and assigned it to plan
        # phase 8; this is that pin.
        #
        # Google and custom are pinned *present* rather than all five pinned absent: the
        # routing `conftest` pins is `google:gemini-2.5-flash`, so a catalog where google
        # is unavailable would contradict the run journeys beside it, and a golden where
        # every model is `available: False` exercises only one side of the flag. Anthropic,
        # OpenAI and OpenRouter stay absent so both sides are covered. The values are
        # inert: `llm_mode` is `fake`, so nothing dials a provider with them.
        _PINNED_KEYS = {
            "google_api_key": "parity-google-key",
            "custom_base_url": "http://custom.invalid/v1",
            "anthropic_api_key": "",
            "openai_api_key": "",
            "openrouter_api_key": "",
        }
        previous_keys = {name: getattr(settings, name) for name in _PINNED_KEYS}
        for name, value in _PINNED_KEYS.items():
            setattr(settings, name, value)

        # The other half of the catalog's ambient input — see `pin_local_llm_probe`.
        previous_probe = pin_local_llm_probe()

        # The corpus is a real store on a real path; only the directory is redirected, so
        # the per-project file layout the server actually uses is still exercised.
        previous_corpus_dir = settings.corpus_dir
        settings.corpus_dir = str(data_dir / "corpus")

        # `embeddings_for` is the server's Embeddings adapter — the port. Substituting one
        # deterministic implementation on both hosts is what makes the corpus comparable;
        # the store and the routes above it stay real.
        import app.adapters as adapters

        shared_embedder = _embedder()

        async def _embeddings_for(_keys=None):
            return shared_embedder

        # One binding now. This used to patch `app.api.v1.corpus.embeddings_for` as well,
        # because that route did `from app.adapters import embeddings_for` and held its own
        # reference from import time — patching only the module attribute left the corpus
        # routes on the deployment default, which is how the first recorded run ended up
        # with two different embedding models in one journey. The routes go through
        # `ServerCorpusLocator` now, which resolves its factory from this attribute when it
        # is constructed, so there is one place to substitute.
        previous_embeddings_for = adapters.embeddings_for
        adapters.embeddings_for = _embeddings_for

        overrides = server_app.dependency_overrides
        previous_overrides = dict(overrides)
        overrides[get_db] = _db
        overrides[get_current_user] = _user
        overrides[enforce_research_rate_limit] = lambda: None
        overrides[enforce_chat_rate_limit] = lambda: None
        dispatcher = _InProcessDispatcher(session_factory, saver)
        overrides[get_run_dispatcher] = lambda: dispatcher
        session_dispatcher = _InProcessSessionDispatcher(session_factory, saver)
        overrides[get_session_dispatcher] = lambda: session_dispatcher

        try:
            transport = httpx.ASGITransport(app=server_app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://server.invalid"
            ) as client:
                yield Driver(
                    name="server",
                    client=client,
                    backing="sqlite",
                    capabilities=SERVER_CAPABILITIES,
                    # Both surfaces have a dispatcher port now, so both are drivable here.
                    run_driver=True,
                )
        finally:
            overrides.clear()
            overrides.update(previous_overrides)
            adapters.embeddings_for = previous_embeddings_for
            settings.corpus_dir = previous_corpus_dir
            settings.llm_mode = previous_llm_mode
            for name, value in previous_keys.items():
                setattr(settings, name, value)
            from app.services import local_llm

            local_llm.probe = previous_probe
            await saver_cm.__aexit__(None, None, None)
