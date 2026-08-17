# Configuration

All configuration is environment variables, read by `pydantic-settings` in
`backend/app/config.py` and by `research_engine/local.py` for the CLI and the desktop
build. `.env.example` is the annotated template; copy it to `.env`.

This page covers the settings you actually reach for. **Every variable, with its exact
default, is in the [Configuration reference](../reference/36-configuration.md).**

## The minimum

Two things are required. Everything else has a working default.

```bash
# Required. >= 32 characters of real randomness; startup refuses placeholders.
JWT_SECRET_KEY=$(openssl rand -hex 32)

# Required. The full-stack compose sets this for you.
DATABASE_URL=postgresql+asyncpg://research_user:research_pass@localhost:5432/research_db
```

Plus one way to reach a model — a provider key, or an Ollama server.

> **Postgres must be a pgvector image.** Migration 0006 enables the `vector` extension and
> 0007 creates a vector column, so a stock `postgres` image fails `alembic upgrade head`
> outright. Every compose file pins `pgvector/pgvector:pgNN`.

## Startup validation

The app fails fast rather than failing at 3am. It refuses to boot when:

- `JWT_SECRET_KEY` is shorter than 32 characters or matches a known placeholder;
- a routed model has no price entry in the catalog (a silent `0.0` would turn the cost cap
  into a no-op, so an unpriced model is refused rather than assumed free);
- `ENVIRONMENT=production` and `LLM_MODE=real` and a routed provider has no API key.
  Keyless providers (`ollama`, `custom`) are exempt from that last check.

## Choosing models

Routing is `"provider:model"`, split on the **first** colon only — so
`ollama:qwen2.5:7b` is provider `ollama`, model `qwen2.5:7b`.

Five roles route independently:

```bash
MODEL_PLANNER=google:gemini-2.5-pro
MODEL_EXECUTOR=google:gemini-2.5-flash
MODEL_CRITIC=google:gemini-2.5-flash
MODEL_SYNTHESIZER=google:gemini-2.5-pro
MODEL_CHAT=google:gemini-2.5-flash
```

Those are the defaults. Role specialisation is a quality argument, not just flexibility:
the executor does tool-calling breadth, the synthesizer does long-form writing with
citation markers, and they are not the same job.

| Provider | Key variable | Notes |
|---|---|---|
| `google` | `GOOGLE_API_KEY` | Default routing. Key from Google AI Studio. |
| `anthropic` | `ANTHROPIC_API_KEY` | |
| `openai` | `OPENAI_API_KEY` | |
| `openrouter` | `OPENROUTER_API_KEY` | One key, many upstream models. **Not priced by the catalog** — see the warning below. |
| `custom` | `CUSTOM_API_KEY`, `CUSTOM_BASE_URL` | Any OpenAI-compatible endpoint. Also unpriced. |
| `ollama` | — | Keyless. See [Local LLM setup](22-local-llm.md). |

Routing resolves most-specific-first: **the session's snapshot → the user's saved
preference → the deployment's `MODEL_*`.** A session snapshots what it actually ran, so a
resumed run keeps its models and a finished report stays attributable to whatever wrote it.

## Search

Optional. The chain is Tavily → Brave → DuckDuckGo, first success wins, results cached in
Redis for 24 hours.

```bash
TAVILY_API_KEY=
BRAVE_API_KEY=
```

With neither set, DuckDuckGo is the only retriever. It works, but it is rate-limited and
slow, and report quality tracks retrieval quality closely.

## Run limits

**Every run limit is `0 = unlimited`, and `0` is the default.** Nothing stops a long run
out of the box; set these when you want a hard stop.

```bash
MAX_CRITIC_LOOPS=2            # retries per task before it contributes what it has
MAX_COST_PER_SESSION_USD=0    # 0 = unlimited
MAX_WALLCLOCK_SECONDS=0       # 0 = unlimited
MAX_INPUT_TOKENS=0            # cumulative across critic loops and rework; 0 = unlimited
MAX_PARALLEL_TASKS=4          # research tasks running at once
CELERY_TASK_TIMEOUT_SECONDS=660
```

> **`MAX_COST_PER_SESSION_USD` is inert on `openrouter` and `custom`.** Their prices are not
> in the catalog, so estimated cost is always `0.00` and the cap never fires. A `$0.00` in
> the UI does not mean a run was free. Cap real spend at the provider's own dashboard. The
> token ceiling is the guard that works everywhere, because it counts what the models were
> actually sent.

A guard that fires says which one and by how much — `cost ceiling reached: $0.5100 of
$0.50`, not a generic "budget exceeded".

`MAX_PARALLEL_TASKS=1` is the only setting where a run can never overshoot the cost cap:
with N workers, up to N calls may already be in flight when the ceiling is crossed.

## Per-user limits

```bash
DEFAULT_MONTHLY_TOKEN_LIMIT=0   # applied to every NEW account; 0 = unlimited
RESEARCH_RATE_LIMIT_PER_HOUR=0  # 0 = unlimited
CHAT_RATE_LIMIT_PER_HOUR=0      # 0 = unlimited
```

All three default to unlimited, because this ships as a single-tenant self-hosted app where
the operator is the only user and pays their own provider bill — throttling them protects
nobody. **A public deployment should set all three.** A user who adds their own API key
raises their own ceiling.

Login and registration limits are separate, are brute-force protection rather than usage
caps, and are **not** configurable.

## Bring your own key

Users can paste their own provider key. It is encrypted at rest with Fernet, never returned
by any endpoint, and decrypted only inside the worker for the duration of that user's run.

```bash
ENCRYPTION_KEY=$(openssl rand -hex 32)
```

Unset, it derives from `JWT_SECRET_KEY` via HKDF under a distinct label, which works but
means rotating your JWT secret makes every stored key undecryptable. **Set it explicitly in
production so the two rotate independently.** Details in
[Security](../architecture/06-security.md).

## Embeddings

Project memory and corpus search need an embedder.

```bash
EMBEDDINGS_PROVIDER=auto   # auto | ollama | google | openai | none
EMBEDDINGS_MODEL=          # blank = the provider's documented default
```

`auto` prefers a local Ollama — free, no egress — and falls back to whichever hosted
provider has a key. `none` disables ingestion and project chat rather than degrading them.

**Changing the model makes existing chunks invisible until they are re-indexed.** Vectors
from different models are not comparable even at equal width, so retrieval filters on the
model that produced them and `GET /projects/{id}/memory/status` reports the mismatch. This
is deliberate: silently mis-ranking is worse than visibly missing.

## Environment and mode

```bash
ENVIRONMENT=development   # development | production | test
LLM_MODE=real             # real | fake
FRONTEND_URL=http://localhost:3031
```

`ENVIRONMENT=production` enables secure cookies and HSTS and disables `/docs` and `/redoc`.

`LLM_MODE=fake` swaps in scripted models and fixture retrievers — deterministic, keyless,
no network. It is what CI and the golden end-to-end tests run on.

`FRONTEND_URL` is the CORS allow-list and is **dev only**: in a real deployment the browser
talks to the same-origin `/api` proxy, so no CORS is involved. In dev the frontend is on
port 3031, and this must match or the API rejects the browser.

## Optional tracing

```bash
LANGCHAIN_TRACING_V2=true
LANGCHAIN_API_KEY=
LANGCHAIN_PROJECT=multi-agent-research-assistant
```

Off by default, and self-host friendly: nothing is sent anywhere unless you turn it on.

## Two configuration paths

The same `RunConfig` is built twice, and the two can drift:

| Path | Built by | Used by |
|---|---|---|
| Server | `app/runtime.py` ← `app/config.py` | API, Celery worker |
| Local | `research_engine/local.py::run_config_from_env` ← `os.environ` | CLI, eval harness, desktop sidecar |

If you add a setting, add it to both. This has drifted twice in the past — once leaving
OpenRouter unreachable from the CLI, once applying the production SSRF guard to a laptop
and rejecting every local model server.
