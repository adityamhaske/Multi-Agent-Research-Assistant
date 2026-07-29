# 13. Local-First Architecture — the engine extraction

> **Status: [PLANNED].** Nothing in this document is built yet. It is the design
> contract for M6–M9 in [12_Launch_Plan.md](12_Launch_Plan.md). Per
> [00_INDEX.md](00_INDEX.md), code that ships must match this doc or this doc must
> change in the same PR.

## 1. Why

The product must ship in three modes from one codebase:

| Mode | Runtime | Auth | Storage | Who |
|---|---|---|---|---|
| **Desktop** | Tauri app + local Python sidecar | none — it's your machine | SQLite | most users |
| **Hosted** | today's compose stack | cookie JWT | Postgres + Redis | demo, teams |
| **Self-host** | today's compose stack | cookie JWT | Postgres + Redis | companies, homelabs |

Today the pipeline cannot run in the desktop column. Not because the graph is
wrong — the graph is fine — but because importing it drags in the server's data
plane.

## 2. The actual coupling (measured, not assumed)

Good news first. **Two of the three hard seams are already correct:**

- **Events** — [`app/agent/events.py`](../backend/app/agent/events.py) holds the sink in a
  `ContextVar` with a no-op default. The worker installs a Postgres+Redis sink; a
  desktop host installs an in-process one. `graph.py` needs **zero changes**.
- **Provider keys** — [`app/agent/llm_factory.py:59`](../backend/app/agent/llm_factory.py:59)
  already ContextVars per-user BYOK keys with server-key fallback. Desktop mode installs
  the user's keys from local config the same way.
- **Search cache** — [`app/agent/retrievers.py:88`](../backend/app/agent/retrievers.py:88)
  wraps every Redis touch in `try/except: pass`. It **already degrades correctly with no
  Redis**. Only the cache backend needs swapping, and only for quality-of-life.

The blocker is one thing:

> **`app/config.py` is a module-level singleton (`settings = get_settings()`) whose
> `database_url` and `jwt_secret_key` fields are required with no default.**

So `import app.agent.graph` → `import app.config` → hard-fails without a Postgres DSN and
a 32-char JWT secret, on a machine that has neither. The evidence this is already wrong is
in the repo: [`evals/harness.py`](../backend/evals/harness.py) has to write

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
[`app/workers/pipeline_runner.py`](../backend/app/workers/pipeline_runner.py) binds
`AsyncPostgresSaver`, the Redis session lock, the SQLAlchemy session, and the
`Session`/`AgentLog` ORM models into one function. That function gets a local twin.

## 3. Target shape

A standalone, pip-installable package with **no FastAPI, no Celery, no SQLAlchemy,
no Redis** in its dependency tree.

```
packages/research-engine/
  pyproject.toml
  research_engine/
    __init__.py
    runconfig.py        # RunConfig dataclass — plain data, NOT pydantic-settings
    ports.py            # Protocol definitions (§4)
    graph.py            # ← app/agent/graph.py, settings reads → run_config
    prompts.py          # ← app/agent/prompts.py
    schemas.py          # ← app/agent/schemas.py
    state.py            # ← app/agent/state.py  (+ run_config on AgentState)
    tools.py            # ← app/agent/tools.py
    net_guard.py        # ← app/agent/net_guard.py
    events.py           # ← app/agent/events.py  (unchanged)
    fakes.py            # ← app/agent/fakes.py
    runner.py           # NEW — checkpointer-agnostic orchestration
    models/
      factory.py        # ← app/agent/llm_factory.py, routing from RunConfig
      catalog.py        # NEW — the model catalog (§6)
      providers.py      # google | anthropic | openai | openrouter | ollama
    retrieval/
      chain.py          # ← app/agent/retrievers.py
      cache.py          # Cache port: Redis | SQLite | Memory
      connectors/       # NEW, M14 — pubmed, arxiv, sec, …
```

Two hosts consume it:

```
backend/          # server host  — FastAPI + Celery + Postgres + Redis adapters
desktop/          # local host   — sidecar HTTP server + SQLite + in-process adapters
```

The rule that makes this worth doing: **`research_engine` never imports from `app`, and
never imports a server dependency.** Enforce it in CI with an import-linter contract, not
a code-review habit.

## 4. The four ports

```python
# ports.py — Protocols only. Hosts supply the adapters.

class EventSink(Protocol):
    async def __call__(self, session_id: str, event: dict) -> None: ...

class Cache(Protocol):
    async def get(self, key: str) -> str | None: ...
    async def set(self, key: str, value: str, ttl: int) -> None: ...

class KeyProvider(Protocol):
    def key_for(self, provider: str) -> str: ...

class RunLock(Protocol):
    async def acquire(self, session_id: str, token: str, ttl: int) -> bool: ...
    async def release(self, session_id: str, token: str) -> None: ...
```

Checkpointing needs no port — LangGraph's saver interface *is* the port
(`AsyncPostgresSaver` server-side, `AsyncSqliteSaver` locally).

Adapter matrix:

| Port | Server adapter | Desktop adapter |
|---|---|---|
| Checkpointer | `AsyncPostgresSaver` | `AsyncSqliteSaver` |
| `EventSink` | `agent_logs` row → Redis publish | in-process asyncio queue → SSE |
| `Cache` | Redis, 24h TTL | SQLite table, 24h TTL |
| `KeyProvider` | decrypt from `users.api_key_encrypted` | OS keychain via Tauri |
| `RunLock` | Redis token lock | in-process `asyncio.Lock` (single process) |
| Job execution | Celery task | `asyncio.create_task` |

`RunConfig` carries everything the graph currently reads from `settings`: `llm_mode`,
per-role routing, budgets, retriever keys. It is constructed by each host — from env
in the server, from a local JSON/keychain read on the desktop — and threaded through
`AgentState` so nodes read `state["run_config"]` instead of a global.

## 5. Migration sequence (strangler — CI green at every step)

Do **not** big-bang this. Each step is independently mergeable and testable.

1. **Introduce `RunConfig`; stop reading `settings` inside `app/agent/`.** Server host
   builds it from `settings` and passes it in. Behaviour identical, tests unchanged.
   This is the whole risky part; do it first and alone.
2. **Move `app/agent/*` → `packages/research-engine/`** with `app.agent` left as a
   re-export shim so nothing else in `backend/` moves yet. Add the import-linter
   contract.
3. **Extract `runner.py`** from `pipeline_runner.py` — checkpointer, sink, lock, and
   key provider all injected. `pipeline_runner.py` becomes the ~30-line server adapter
   that supplies Postgres/Redis versions.
4. **Add the SQLite adapters** and a `research-engine` CLI that runs one query to the
   gate on a bare machine, no Docker. This is the proof the extraction worked.
5. **Delete the shim**, update imports, drop the `os.environ.setdefault` block from
   `evals/harness.py` — its removal is the acceptance test for the whole refactor.

## 6. Model layer

**Fix first (blocking, and a live bug):**
`_ANTHROPIC_NO_SAMPLING` at [`llm_factory.py:37`](../backend/app/agent/llm_factory.py:37)
omits `claude-opus-5`, so routing any role to Opus 5 sends `temperature` and takes a 400 —
contradicting the comment directly above it ("Opus 4.7+ … reject temperature"). `opus-5`
is also absent from `PRICE_TABLE`, so `validate_pricing()` refuses boot first. Both entries
are required before a picker can offer Opus 5. Fill the price from the provider's live
pricing page — never guess; the fail-fast check exists precisely to make a guess impossible
to ship silently.

**Catalog.** Promote the flat `PRICE_TABLE` into a catalog with, per model: provider,
model id, display name, input/output price per 1M, context window, tool-calling support,
structured-output support, and a `sampling_params_supported` flag (which retires the
`_ANTHROPIC_NO_SAMPLING` tuple as a hardcoded list). The UI reads this; so does cost
accounting; so does `validate_pricing()`.

**Two new providers, both small in the existing factory:**

- **OpenRouter** — one key, one OpenAI-compatible base URL, unlocks Anthropic/OpenAI/
  Google/DeepSeek/Llama/Mistral. Largest BYOK UX win available per hour of work.
- **Ollama** — OpenAI-compatible local endpoint. This *is* the offline tier-2 story.
  Local models are weaker at structured output; the fail-closed critic and the
  `_parse_evidence` fallback at [`graph.py:67`](../backend/app/agent/graph.py:67) already
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
[10_Roadmap.md](10_Roadmap.md) v2 item #1 into a headline feature: *citation-grade
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
