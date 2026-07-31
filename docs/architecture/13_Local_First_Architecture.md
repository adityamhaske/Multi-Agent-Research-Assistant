# 13. Local-First Architecture — the engine extraction

> **Status: partly built.** **§3, §4 and §5 are shipped** — M6 is code complete, so the
> engine is extracted, host-independent, and runs a full pipeline locally through
> `research-engine`. §2 is kept as the measurement record of the coupling that removal
> resolved. **[PLANNED]:** §6 the model layer (M8), §7 the desktop shell (M9), §8 the
> offline tiers (M9–M10) — each section says which.
> Design contract for M6–M10 in [12_Launch_Plan.md](../product/12_Launch_Plan.md); per
> [00_INDEX.md](../00_INDEX.md), code that ships must match this doc or this doc changes in
> the same PR.

## 1. Why

The product must ship in three modes from one codebase:

| Mode | Runtime | Auth | Storage | Who |
|---|---|---|---|---|
| **Desktop** | Tauri app + local Python sidecar | none — it's your machine | SQLite | most users |
| **Hosted** | today's compose stack | cookie JWT | Postgres + Redis | demo, teams |
| **Self-host** | today's compose stack | cookie JWT | Postgres + Redis | companies, homelabs |

The pipeline used to be unable to run in the desktop column. Not because the graph was
wrong — the graph was always fine — but because importing it dragged in the server's data
plane. **That is fixed (M6):** the engine now runs the full pipeline, review gate included,
against SQLite on a machine with no Docker, no Postgres, no Redis, and no login. What the
desktop column still needs is a shell around it (§7) and the offline tiers (§8).

## 2. The actual coupling (measured, not assumed)

> **✅ Resolved by M6 steps 1–2.** This section is kept as the measurement record — it is
> why the extraction was cheap and where the risk actually was. Paths below refer to
> `app/agent/`, which is now `backend/research_engine/`. The `settings` reads it lists are
> gone; `tests/test_engine_boundary.py` fails if any come back.

Good news first. **Two of the three hard seams are already correct:**

- **Events** — [`app/agent/events.py`](../../backend/research_engine/events.py) holds the sink in a
  `ContextVar` with a no-op default. The worker installs a Postgres+Redis sink; a
  desktop host installs an in-process one. `graph.py` needs **zero changes**.
- **Provider keys** — [`app/agent/llm_factory.py:59`](../../backend/research_engine/llm_factory.py:59)
  already ContextVars per-user BYOK keys with server-key fallback. Desktop mode installs
  the user's keys from local config the same way.
- **Search cache** — [`app/agent/retrievers.py:88`](../../backend/research_engine/retrievers.py:88)
  wraps every Redis touch in `try/except: pass`. It **already degrades correctly with no
  Redis**. Only the cache backend needs swapping, and only for quality-of-life.

The blocker is one thing:

> **`app/config.py` is a module-level singleton (`settings = get_settings()`) whose
> `database_url` and `jwt_secret_key` fields are required with no default.**

So `import app.agent.graph` → `import app.config` → hard-fails without a Postgres DSN and
a 32-char JWT secret, on a machine that has neither. The evidence this is already wrong is
in the repo: [`evals/harness.py`](../../backend/evals/harness.py) has to write

```python
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://eval:eval@localhost:5432/eval")
os.environ.setdefault("JWT_SECRET_KEY", "eval-secret-0123456789abcdef0123456789abcdef")
```

…before it can import the graph, to run a pipeline that touches no database at all. That
workaround is the design telling us what it wants.

Direct `settings` reads inside engine code, all of which must become run-scoped config:

| File | Reads |
|---|---|
| `agent/graph.py` | `llm_mode`, `max_cost_per_session_usd`, `max_wallclock_seconds`, `max_critic_loops` |
| `agent/llm_factory.py` | `llm_mode`, `model_*` routing, `*_api_key` |
| `agent/retrievers.py` | `llm_mode`, `tavily_api_key`, `brave_api_key` |
| `agent/tools.py`, `net_guard.py` | (verify at extraction time) |

The rest of the coupling is the runner:
[`app/workers/pipeline_runner.py`](../../backend/app/workers/pipeline_runner.py) binds
`AsyncPostgresSaver`, the Redis session lock, the SQLAlchemy session, and the
`Session`/`AgentLog` ORM models into one function. That function gets a local twin.

## 3. Target shape

A standalone, pip-installable package with **no FastAPI, no Celery, no SQLAlchemy,
no Redis** in its dependency tree.

**Status: ✅ built (M6 step 2).** Actual layout, with two deliberate deviations from the
first draft of this section noted below:

```
backend/
  research_engine/          # the engine — installable, host-independent
    pyproject.toml          # only engine deps; providers are extras
    __init__.py             # the boundary rule, stated where it's violated
    runconfig.py            # RunConfig + process default + ContextVar override
    graph.py                # the compiled StateGraph
    prompts.py  schemas.py  state.py
    tools.py    net_guard.py
    retrievers.py           # searches through the Cache port
    llm_factory.py          # + catalog / providers (M8)
    events.py   fakes.py
    ports.py                # EventSink + Cache Protocols (§4)
    cache.py                # NullCache default + ContextVar indirection
    runner.py               # checkpointer-agnostic orchestration → RunOutcome
    local.py                # local host: SqliteCache, InProcessEventSink, env config
    cli.py                  # `research-engine` — the reference local host
  app/                      # server host — FastAPI + Celery + Postgres + Redis
    runtime.py              # the seam: settings → RunConfig
    adapters.py             # the host's RedisCache + agent_logs event sink
  desktop/                  # [PLANNED M9] Tauri shell wrapping local.py + cli.py
```

**Deviation 1 — the package lives under `backend/`, not top-level `packages/`.** The
api and worker images build with `context: ./backend` and `COPY . /app`, so a top-level
directory falls outside the build context: moving it there means rewriting the compose
contexts, the Dockerfile COPY paths, and `.dockerignore` — verifiable only by building
images. Inside `backend/` the boundary is fully enforced at near-zero integration risk.
Its own `pyproject.toml` keeps the dependency boundary real rather than notional: the
built wheel declares langgraph, langchain-core, pydantic, httpx, bs4, lxml, tavily, ddgs,
structlog — and **no** FastAPI, Celery, SQLAlchemy, asyncpg, Redis, PyJWT, or WeasyPrint.
`git mv` it to top-level when M9's desktop packaging actually needs that, and only then.

**Deviation 2 — no `models/` and `retrieval/` subpackages yet, and no shim.** Step 2 was
a move, not a restructure; splitting `llm_factory.py` into `models/{factory,catalog,
providers}.py` belongs with M8, which is what creates the content. And the re-export shim
this document originally called for turned out unnecessary — the external import surface
was 10 lines across 6 files, so they were simply updated, leaving no dead layer for step 5
to delete.

The rule that makes this worth doing: **`research_engine` never imports from `app`, and
never imports a server dependency.** Enforced by
[`tests/test_engine_boundary.py`](../../backend/tests/test_engine_boundary.py) — it AST-scans
every engine module and fails on any `app.*` import not in an explicit, self-invalidating
allowlist.

## 4. The ports — two, not four

**Status: ✅ built (M6 step 3)** — [`research_engine/ports.py`](../../backend/research_engine/ports.py),
with the server's implementations in [`app/adapters.py`](../../backend/app/adapters.py).

```python
# ports.py — Protocols only. Hosts supply the implementations.

@runtime_checkable
class EventSink(Protocol):
    async def __call__(self, session_id: str, event: dict) -> None: ...

@runtime_checkable
class Cache(Protocol):
    async def get(self, key: str) -> str | None: ...
    async def set(self, key: str, value: str, ttl: int) -> None: ...
```

**This section originally specified four ports. Two of them were interfaces where data
or the host was sufficient, and building them would have been indirection with no second
implementation to justify it:**

- **`KeyProvider` — dropped.** Provider keys are resolved by the host *before* a run (the
  server decrypts `users.api_key_encrypted`) and handed over as a plain `{provider: key}`
  mapping: `runner.run(provider_keys=…)`. A callable would add a lookup the engine never
  exercises.
- **`RunLock` — dropped, stays in the host.** Preventing two workers from running one
  session is scheduling, not pipeline behaviour. The server needs a Redis token lock
  because Celery can redeliver; a single-process desktop app needs at most an
  `asyncio.Lock`. Nothing about it belongs to the graph.

Checkpointing needs no port either — LangGraph's saver interface *is* the port. The host
constructs it and calls `setup()` (schema creation is a host concern), then passes the
ready saver to `runner.run`/`runner.resume`.

Adapter matrix:

| Concern | Server (built) | Desktop ([PLANNED] M9) |
|---|---|---|
| Checkpointer | `AsyncPostgresSaver` | `AsyncSqliteSaver` |
| `EventSink` | `agent_logs` row → Redis publish | in-process asyncio queue → SSE |
| `Cache` | `RedisCache`, 24h TTL | SQLite table, 24h TTL |
| Provider keys (data) | decrypt from `users.api_key_encrypted` | OS keychain via Tauri |
| Run lock (host) | Redis token lock | in-process `asyncio.Lock` |
| Job execution (host) | Celery task | `asyncio.create_task` |

The engine's default for an uninstalled port is a no-op, never a crash: `events._noop`
and `cache.NullCache`. So a bare engine — a CLI run, a test, the desktop build before its
SQLite cache exists — works with no host at all. `tests/test_engine_runner.py` pins both
that and the fact that every installed port is unwound after a run, since a leaked
`ContextVar` would silently bleed one run's keys or model routing into the next.

`RunConfig` carries everything the graph used to read from `settings`: `llm_mode`,
per-role routing, budgets, retriever keys. It is constructed by each host — from env in
the server (`app/runtime.py`), from local JSON + OS keychain on the desktop.

**Delivery mechanism: a module default plus a `ContextVar` override**
([`app/agent/runconfig.py`](../../backend/research_engine/runconfig.py)), *not* threading through
`AgentState` as an earlier draft of this document said. `AgentState` cannot reach the
retriever chain: LangGraph invokes tools without passing state, and `retrievers.search()`
is called from inside `web_search`. A `ContextVar` reaches both, and matches the two
existing precedents in the package (`events._emitter`, `llm_factory._user_keys`).

- `set_process_default(cfg)` — one baseline per process, installed by the host.
- `set_run_config(cfg)` — per-run override; what M8's per-session model picker uses.
- `get_run_config()` — override → process default → module defaults, where the module
  defaults mirror `app/config.py`'s field defaults exactly, so a host that forgets to
  install degrades to today's behaviour rather than to something new.

**Status: ✅ built (M6 step 1).** `app/agent/` no longer imports `app.config`;
`import app.agent.graph` and `build_graph()` both succeed with no `DATABASE_URL`, no
`JWT_SECRET_KEY`, and no provider keys. Enforced by
[`tests/test_engine_boundary.py`](../../backend/tests/test_engine_boundary.py), which
AST-scans the package for host imports and pins the defaults equivalence.

## 5. Migration sequence (strangler — CI green at every step)

Do **not** big-bang this. Each step is independently mergeable and testable.

1. **✅ Introduce `RunConfig`; stop reading `settings` inside `app/agent/`.** Server host
   builds it from `settings` and installs it. Behaviour identical, existing tests
   unchanged. This was the whole risky part; done first and alone.
   Hosts installing a config: `app/main.py` (lifespan), `app/workers/celery_app.py`
   (import time), `evals/harness.py`, `tests/conftest.py`. Remaining engine→host
   import: `app.db.redis` in `retrievers.py`, resolved by step 3's `Cache` port and
   allowlisted in the boundary test until then.
2. **✅ Move `app/agent/*` → `backend/research_engine/`** (§3 deviation 1), rewriting the
   10 external import lines directly rather than leaving a shim (deviation 2). Boundary
   contract tightened from "no `app.config`" to "no `app.*` at all", and backed by a
   `pyproject.toml` whose built wheel proves the dependency boundary.
   Verified: `research_engine` imports and `build_graph()` compiles with **zero** `app.*`
   modules in `sys.modules`, no `DATABASE_URL`, no `JWT_SECRET_KEY`, no provider keys.
3. **✅ Extract `runner.py`** from `pipeline_runner.py` — checkpointer, event sink, cache,
   run config, and provider keys injected; returns a plain `RunOutcome`. The last
   engine→host import (`app.db.redis` in `retrievers.py`) became the `Cache` port, so the
   boundary test's allowlist is now **empty**: the engine imports nothing from the host.
   **Estimate correction:** this step said `pipeline_runner.py` would drop to ~30 lines.
   It went 211 → 187. The graph-driving logic did leave, but everything remaining is
   genuinely host-specific — the Redis lock, the single DB-session scope, BYOK
   decryption, constructing the Postgres saver, and mapping `RunOutcome` onto ORM columns
   and lifecycle events. A thin adapter is not the same as a short one.
   Verified: `runner.run()` drives a complete pipeline to the gate with **zero** `app.*`
   modules imported.
4. **✅ Add the SQLite adapters** (`local.py`: `SqliteCache` on stdlib `sqlite3`,
   `InProcessEventSink`) **and the `research-engine` CLI**. Verified from `/tmp`, outside
   the repo, with no server env: a cited draft at the gate, then `--approve` in a
   **separate process** finalizing from the SQLite checkpoint at unchanged cost — so
   durable HITL works on a laptop, not just against Postgres.
5. **✅ Drop the `os.environ.setdefault` block** from `evals/harness.py`. It now builds
   its config with `local.run_config_from_env` instead of `app.config`, so it imports
   **zero** `app.*` modules and `make eval` needs no `DATABASE_URL` and no
   `JWT_SECRET_KEY`. No shim to delete: step 2 didn't need one.
   **Side effect worth having:** the harness no longer reads a developer's `.env`, so eval
   runs are reproducible from explicit defaults + explicit env rather than from whatever
   routing happens to be on the machine. That silently-broken comparability was flagged
   during M5 — recorded cost is back in line with the committed baseline.

## 6. Model layer

**Status: ✅ built (M8).** [`catalog.py`](../../backend/research_engine/catalog.py) +
[`app/services/model_routing.py`](../../backend/app/services/model_routing.py) +
[`app/api/v1/models.py`](../../backend/app/api/v1/models.py).

**The bug this started with.** `_ANTHROPIC_NO_SAMPLING` was a tuple of model-id *prefixes*,
and `claude-opus-5` was in neither it nor `PRICE_TABLE` — so routing a role to Opus 5 failed
twice: `validate_pricing()` refused to boot, and had it booted, every request would have
sent a `temperature` and taken a 400, contradicting the comment directly above the tuple.

The entry was the symptom; the **prefix tuple was the bug**. Sampling support is now a
per-model catalog field, so the next model can't slip through the same gap, and a test pins
the whole split (Opus 5/4.8/4.7, Sonnet 5, Fable 5 reject; Opus 4.6, Sonnet 4.6, Haiku 4.5
accept) rather than one model.

**Catalog.** One `ModelSpec` per model: provider, id, display name, input/output price per
1M, context window, max output, tool-calling, structured-output, `sampling_params_supported`,
notes. Read by the picker, by cost accounting, and by `validate_pricing()`. Adding a model
is a catalog entry and nothing else — an invariant with a test behind it, plus
`catalog.register()` as the runtime escape hatch for a model this repo doesn't ship.

**Prices are never estimated.** `None` means "this deployment must supply it", not "free",
and `validate_pricing()` refuses to boot on an unpriced routed model rather than defaulting
to zero — a silent zero would turn `MAX_COST_PER_SESSION_USD` into a no-op. Anthropic
figures come from the authoritative API reference; OpenAI and OpenRouter ship deliberately
unpriced; Ollama is genuinely `0.0` because the tokens are generated on the user's hardware.

**Routing lives in three layers**, most specific winning: the session's snapshot → the
user's saved preference → the deployment's `MODEL_*`. Validation runs on *write*, so a
stored preference is always startable and a run can never fail halfway on a model that
could have been rejected when it was picked. The session's routing is **snapshotted**
rather than re-read, so a resumed run keeps the models it started with and a finished
report stays attributable to what wrote it.

**Two new providers, both small in the existing factory:**

- **OpenRouter** — one key, one OpenAI-compatible base URL, unlocks Anthropic/OpenAI/
  Google/DeepSeek/Llama/Mistral. Largest BYOK UX win available per hour of work.
- **Ollama** — OpenAI-compatible local endpoint. This *is* the offline tier-2 story.
  Local models are weaker at structured output; the fail-closed critic and the
  `_parse_evidence` fallback at [`graph.py:67`](../../backend/research_engine/graph.py:67) already
  handle that class of failure, which is why local models are viable here at all.

**Presets, then the drawer.** Ship `Fast` / `Balanced` / `Best` as one-click defaults;
the per-role picker (planner, executor, critic, synthesizer, chat) sits behind
"Customize". Role specialization is a *quality* argument — cheap model for tool-calling
breadth, strong model for synthesis — not just a flexibility toggle. Say so in the UI.

## 7. Desktop process architecture

```
┌─ Tauri shell (Rust) ────────────────────────────────┐
│  WebView → Next.js static export (`output: export`) │
│  Keychain access · auto-update · file dialogs       │
│         │ spawns + supervises                       │
│         ▼                                           │
│  Python sidecar (PyInstaller one-dir)               │
│    uvicorn on 127.0.0.1:<ephemeral>                 │
│    research_engine + SQLite + local adapters        │
└─────────────────────────────────────────────────────┘
```

- Frontend keeps talking to `/api/*`; the shell rewrites the base URL to the sidecar
  port. Same client code, same SSE handling, same citation UX.
- Auth endpoints are absent in local mode; the frontend's server-side cookie guard at
  `app/(app)/layout.tsx` compiles out behind a build flag.
- **Bind to `127.0.0.1` on an ephemeral port with a per-launch bearer token in the
  sidecar handshake.** A localhost port with no token is reachable by any other process
  on the machine, and by any web page via DNS rebinding. This is the one security item
  the desktop build adds, and it is not optional.
- **Drop WeasyPrint from the desktop bundle.** Its GTK dependency chain on Windows is a
  packaging tar pit; desktop PDF uses the WebView's print-to-PDF, which the frontend
  already implements client-side. Server-side export stays server-side.
- Expect a 150–300 MB bundle. Sign it (Apple $99/yr, Azure Trusted Signing ~$10/mo) or
  SmartScreen and Gatekeeper will eat the launch — PyInstaller binaries draw antivirus
  false positives reliably.

## 8. Offline, in three honest tiers

| Tier | Models | Evidence | Network | Real user |
|---|---|---|---|---|
| 1 · No-login | cloud, BYOK | web search | yes | privacy-minded default |
| 2 · Local models | Ollama | web search | yes | no-cloud-inference |
| 3 · Airgapped | Ollama | **local document corpus** | **none** | law, health, defense, journalism |

Tier 3 is the category-first, and it promotes "document upload" from
[10_Roadmap.md](../product/10_Roadmap.md) v2 item #1 into a headline feature: *citation-grade
research over your own files, on your own laptop, nothing leaves the machine.* The
citation machinery already built — verbatim snippets, `[n]` resolution, the visible ⚠
unverified chip — works **better** on a closed corpus than on the open web, because
snippet provenance is exact.

Implementation is a retrieval connector, not a new pipeline: ingest (PDF/MD/TXT) →
chunk → local embeddings (`sentence-transformers`, bundled) → SQLite vector store →
a `search`-shaped adapter behind the same interface `retrievers.search()` exposes. The
graph does not change.

## 9. What explicitly does not change

Guard these — they are the product:

- The compiled `StateGraph` and its node contracts ([04_Agent_Design.md](04_Agent_Design.md)).
- `interrupt()`-based HITL with resume-from-checkpoint. **Desktop keeps the gate.**
- Fail-closed critic; explicit `FAILED` states with reasons.
- Per-claim citation resolution and the ⚠ unverified chip.
- Untrusted-content framing and the SSRF guard — *more* important locally, where the
  fetcher runs inside the user's LAN.

## 10. Risks

| Risk | Mitigation |
|---|---|
| Refactor drags, blocks everything | Step 1 (`RunConfig`) merges alone; shim keeps `backend/` untouched until step 5 |
| Engine silently re-couples to server deps | import-linter contract in CI, not review discipline |
| PyInstaller AV false positives | code signing budgeted from month 1; not optional |
| Windows packaging (WeasyPrint/GTK) | excluded from desktop bundle by design (§7) |
| Local models fail structured output | already fail-closed; presets steer to tool-capable local models; document the floor |
| Two products diverge | one engine, hosts are thin adapters; golden E2E runs against **both** hosts in CI |
