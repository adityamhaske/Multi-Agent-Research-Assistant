# Local and self-hosted architecture

One engine, two hosts, three privacy tiers. This page explains what runs where, what leaves
the machine, and what does not.

## Three modes from one codebase

| Mode | Runtime | Auth | Storage | Who it is for |
|---|---|---|---|---|
| **Desktop** | Tauri shell + a bundled Python engine | None — it is your machine | SQLite | Individuals |
| **Self-hosted** | The Compose stack | Cookie sessions | Postgres + Redis | Companies, homelabs |
| **Hosted** | The same Compose stack | Cookie sessions | Postgres + Redis | Demos, small teams |

The middle two are the same deployment with different exposure. Only the first is a
different program shape.

## The engine boundary

The pipeline lives in `research_engine`, a package with **no FastAPI, no Celery, no
SQLAlchemy, and no Redis** in its dependency tree. It never imports from the server
application at all — a test AST-scans every engine module and fails on any host import.

```
backend/
  research_engine/        the engine — installable, host-independent
    runconfig.py          RunConfig: process default + per-run override
    graph.py              the compiled StateGraph
    prompts.py  schemas.py  state.py
    tools.py    net_guard.py
    retrievers.py         searches through the Cache port
    llm_factory.py  catalog.py
    events.py   fakes.py  demo_fixtures.py
    ports.py              EventSink, Cache, Embeddings, Corpus protocols
    corpus.py  chunking.py  embeddings.py
    runner.py             checkpointer-agnostic orchestration → RunOutcome
    local.py              the local host: SqliteCache, in-process events, env config
    cli.py                `research-engine` — the reference local host
    bundle.py  verify_bundle.py
  app/                    server host — FastAPI, Celery, Postgres, Redis
    runtime.py            the seam: settings → RunConfig
    adapters.py           RedisCache and the agent_logs event sink
  desktop/
    sidecar.py            the desktop host
```

That boundary is what makes a desktop build possible at all. It is also why the evaluation
harness needs no `DATABASE_URL` and no `JWT_SECRET_KEY` to run a pipeline that touches no
database.

## Ports

Two protocols, plus two more for the corpus tier. Hosts supply the implementations.

```python
class EventSink(Protocol):
    async def __call__(self, session_id: str, event: dict) -> None: ...

class Cache(Protocol):
    async def get(self, key: str) -> str | None: ...
    async def set(self, key: str, value: str, ttl: int) -> None: ...

class Embeddings(Protocol):
    @property
    def model_id(self) -> str: ...
    @property
    def dimensions(self) -> int: ...
    async def embed(self, texts: list[str]) -> list[list[float]]: ...

class Corpus(Protocol):
    async def search(self, query: str, max_results: int) -> list[dict]: ...
    async def read(self, url: str) -> dict: ...
```

`Corpus.search` returns exactly the shape the web retriever returns, so the executor needs no
branch and the graph does not change when the corpus replaces the web.

Checkpointing needs no port — LangGraph's saver interface *is* the port. The host constructs
it and hands the ready saver to the runner.

Every embeddings adapter should additionally expose an **`is_local`** attribute. It is not
declared on the protocol; the corpus airgap guard reads it defensively and **treats a
missing one as remote**, so an adapter that forgets to answer is handled as the unsafe case
rather than waved through.

| Concern | Server | Desktop |
|---|---|---|
| Checkpointer | `AsyncPostgresSaver` | `AsyncSqliteSaver` |
| Event sink | `agent_logs` row → Redis publish | In-process queue → SSE |
| Cache | Redis, 24h TTL | SQLite table, 24h TTL |
| Provider keys | Decrypted from an encrypted column | OS keychain |
| Run lock | Redis token lock | In-process lock |
| Job execution | Celery task | An asyncio task |

The engine's default for an uninstalled port is a **no-op, never a crash**, so a bare engine
— a CLI run, a test, a fresh desktop build — works with no host at all.

Configuration arrives as a `RunConfig`: a process-wide default installed by the host, plus a
per-run override in a `ContextVar` so concurrent runs in one worker can carry different model
routing and budgets. A `ContextVar` rather than graph state, because tools are invoked
without access to state and the retriever chain is called from inside a tool.

## Desktop process architecture

```
┌─ Tauri shell (Rust) ────────────────────────────────┐
│  WebView → Next.js static export                    │
│  Keychain access · file dialogs                     │
│         │ spawns and supervises                     │
│         ▼                                           │
│  Python sidecar (PyInstaller, one directory)        │
│    uvicorn on 127.0.0.1:<ephemeral port>            │
│    research_engine + SQLite + local adapters        │
└─────────────────────────────────────────────────────┘
```

- The frontend keeps talking to `/api/*`; the shell rewrites the base URL to the sidecar
  port. Same client code, same SSE handling, same citation UX.
- Auth endpoints are absent, and the frontend's server-side cookie guard compiles out behind
  a build flag.
- **The sidecar binds to `127.0.0.1` on an ephemeral port with a per-launch bearer token.**
  A loopback port with no token is reachable by any other process on the machine, and by any
  web page through DNS rebinding. This is the one security control the desktop build adds,
  and it is not optional.
- The sidecar watches the shell's process id and exits when the shell does.
- **WeasyPrint is excluded from the bundle** — its native dependency chain on Windows is a
  packaging tar pit. Desktop PDF uses the WebView's print-to-PDF. A test pins that the
  sidecar process never imports the server's export module at all.

The bundle is around 81 MB for the macOS `.dmg`, installing to roughly 182 MB. It carries no
PyTorch and no `sentence-transformers`; its heaviest dependency is numpy.

## What differs between the hosts

The pipeline, both gates, citation resolution, and the export formats are identical. These
are the deliberate differences:

| | Desktop | Server |
|---|---|---|
| Report chat | Yes, same scope contract | Yes |
| Project chat and project memory | **Absent by design** — memory is pgvector-only | Yes |
| Durable event log | Absent; bundles record `trace_available: false` rather than an empty trace | `agent_logs` |
| Corpus layout | One `corpus.sqlite` for the app | One file per project |
| Rate limiting | None — needs Redis and a user model, and the desktop has neither | Yes |
| PDF export | WebView print-to-PDF | WeasyPrint, server-side |

`trace_available` is worth noting as a pattern: an empty `trace: []` is ambiguous between
"the host has no durable log", "the log was empty", and "the log is missing". The flag
disambiguates, and it is covered by the bundle hash, so the truthful state is what gets
signed.

### Keeping the two in step

Every shared behaviour has two homes, and the second one is what gets forgotten. When you
change any of the following, change both:

- Request fields reaching the session row
- The per-session run config
- A new session status, or a new pause event
- Route validation
- Report chat behaviour
- Schema: a migration **and** the ORM model, which is what the desktop's schema sync reads

Where possible, extract the shared logic into one function instead of keeping two copies in
step by discipline. The `localhost` → `host.docker.internal` rewrite is the worked example:
it existed in three copies, two of which were wrong, and is now one function both hosts call.

## Local endpoints and Docker

`map_local_host()` is the single implementation that rewrites `localhost` to
`host.docker.internal` when running inside a container. Both the pipeline's model calls and
the health probe go through it, so the check agrees with the thing it is checking — the
probe used to dial the raw configured value and then tell you to retype it by hand.

## Three privacy tiers

| Tier | Models | Evidence | Network | Who needs it |
|---|---|---|---|---|
| **1 · Cloud, BYOK** | Provider APIs | Web search | Yes | Privacy-minded default: no SaaS intermediary |
| **2 · Local models** | Ollama | Web search | Yes, for retrieval only | No cloud inference |
| **3 · Airgapped corpus** | Ollama | **Your documents only** | **None** | Law, health, defence, journalism |

### What leaves the machine, per tier

**Tier 1.** Prompts and reports go to your chosen model provider on your key. Search queries
go to the retriever. Nothing is proxied through a service operated by this project, because
there is no such service.

**Tier 2.** Model inference is fully local — prompts, reports, and chat never reach a model
provider. **Search queries still leave**, because ordinary research still searches the web
and fetches pages. This is the caveat people most often assume away, so it is stated plainly:
your *reasoning* stays local, your *queries* do not.

**Tier 3.** Nothing. Evidence comes only from the installed corpus; `read_webpage` refuses
every non-corpus URL, and the retriever delegates exclusively to the corpus store. A run in
this mode with no corpus installed **fails closed** rather than falling back to the web.

Corpus hits carry `corpus://<doc-id>#chars=<start>-<end>` URLs, and the synthesizer's normal
source assembly turns them into ordinary `[n]` citations whose snippets resolve back to the
exact character range in the source document. Citation provenance is *more* exact on a closed
corpus than on the open web.

Embeddings for tier 3 go through the `Embeddings` port to the same Ollama, defaulting to
`nomic-embed-text` — not a bundled `sentence-transformers`, whose torch dependency alone
would exceed the whole bundle budget. Zero egress is asserted by a test with socket and DNS
guards.

> **A note on testing an absence.** A test that asserts "no network calls" while injecting a
> fake embedder proves nothing if the query embedding was the only thing that egressed. When
> writing a test for an absence, check what the fixtures replaced: if the mechanism under
> test is the thing you mocked, the test is decorative.

## What explicitly does not change across hosts

These are the product, and they hold everywhere:

- The compiled graph and its node contracts.
- `interrupt()`-based human gates with resume-from-checkpoint. **Desktop keeps both gates.**
- The fail-closed critic, and explicit failure states with reasons.
- Per-claim citation resolution and the ⚠ unverified chip.
- Untrusted-content framing and the SSRF guard — *more* important locally, where the fetcher
  runs inside your own network.
