# Configuration reference

Every environment variable read by the application, with its exact default. Task-oriented
guidance is in [Configuration](../getting-started/21-configuration.md).

Variable names are case-insensitive. The server reads `../.env` relative to `backend/`;
Compose passes `./.env` into the containers.

## Required

| Variable | Default | Notes |
|---|---|---|
| `JWT_SECRET_KEY` | — | **Required.** ≥ 32 characters of real randomness. Startup refuses placeholders and short values |
| `DATABASE_URL` | — | **Required.** e.g. `postgresql+asyncpg://user:pass@host:5432/db`. Postgres must be a **pgvector** image |

## Environment and mode

| Variable | Default | Notes |
|---|---|---|
| `ENVIRONMENT` | `development` | `development` \| `production` \| `test`. Production enables secure cookies and HSTS, and disables `/docs` and `/redoc` |
| `LLM_MODE` | `real` | `real` \| `fake`. Fake uses scripted models and fixture retrievers — deterministic, keyless, no network |
| `FRONTEND_URL` | `http://localhost:3031` | **Dev only.** The CORS allow-list. Production uses the same-origin proxy and enables no CORS at all |

## Provider keys

| Variable | Default | Notes |
|---|---|---|
| `GOOGLE_API_KEY` | `""` | |
| `ANTHROPIC_API_KEY` | `""` | |
| `OPENAI_API_KEY` | `""` | |
| `OPENROUTER_API_KEY` | `""` | |
| `CUSTOM_API_KEY` | `""` | Any OpenAI-compatible endpoint |
| `CUSTOM_BASE_URL` | `""` | Required alongside `CUSTOM_API_KEY` |

With `ENVIRONMENT=production` and `LLM_MODE=real`, startup fails if a routed provider has no
key. `ollama` and `custom` are exempt — they need none.

## Model routing

`"provider:model"`, split on the **first** colon only.

| Variable | Default |
|---|---|
| `MODEL_PLANNER` | `google:gemini-2.5-pro` |
| `MODEL_EXECUTOR` | `google:gemini-2.5-flash` |
| `MODEL_CRITIC` | `google:gemini-2.5-flash` |
| `MODEL_SYNTHESIZER` | `google:gemini-2.5-pro` |
| `MODEL_CHAT` | `google:gemini-2.5-flash` |

Startup refuses a routed model with no price entry in the catalog. `openrouter`, `custom`,
and `ollama` are exempt from that check — with the consequence that the per-session cost cap
**cannot fire** on the first two.

## Local models

| Variable | Default | Notes |
|---|---|---|
| `OLLAMA_BASE_URL` | `http://localhost:11434/v1` | Use `http://host.docker.internal:11434/v1` when the app runs in Docker |

## Search retrievers

| Variable | Default | Notes |
|---|---|---|
| `TAVILY_API_KEY` | `""` | Optional. First in the chain |
| `BRAVE_API_KEY` | `""` | Optional. Second |

With neither set, DuckDuckGo is the only retriever — keyless, but rate-limited and slow.

## Data stores

| Variable | Default | Notes |
|---|---|---|
| `REDIS_URL` | `redis://localhost:6379/0` | Broker, SSE fan-out, rate limits, locks, search cache |
| `CORPUS_DIR` | `data/corpus` | Where per-project corpus SQLite files live. A relative value resolves against the **backend package root**, not the process working directory |

## Authentication

| Variable | Default | Notes |
|---|---|---|
| `JWT_ALGORITHM` | `HS256` | |
| `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` | `15` | |
| `JWT_REFRESH_TOKEN_EXPIRE_DAYS` | `14` | |
| `REQUIRE_EMAIL_VERIFICATION` | `false` | **Set `true` for any public deployment** |
| `ENCRYPTION_KEY` | `""` | Encrypts users' stored provider keys. Empty derives from `JWT_SECRET_KEY` via HKDF under a distinct label. **Set explicitly in production**, so rotating the JWT secret does not invalidate every stored key |

## Run limits

**All of these are `0 = unlimited`, and `0` is the default** unless stated otherwise.

| Variable | Default | Notes |
|---|---|---|
| `MAX_CRITIC_LOOPS` | `2` | Retries per task before it settles with what it has |
| `MAX_COST_PER_SESSION_USD` | `0.0` | **Inert on `openrouter` and `custom`** |
| `MAX_WALLCLOCK_SECONDS` | `0` | |
| `MAX_INPUT_TOKENS` | `0` | Cumulative across critic loops and rework. The guard that works on every provider |
| `MAX_PARALLEL_TASKS` | `4` | `1` is the only value where a run cannot overshoot the cost cap |
| `CELERY_TASK_TIMEOUT_SECONDS` | `660` | Not a `0 = unlimited` setting |

## Per-user limits

| Variable | Default | Notes |
|---|---|---|
| `DEFAULT_MONTHLY_TOKEN_LIMIT` | `0` | Applied to **new** accounts only. 0 = unlimited |
| `RESEARCH_RATE_LIMIT_PER_HOUR` | `0` | 0 = unlimited. Enforced before model routing is consulted |
| `CHAT_RATE_LIMIT_PER_HOUR` | `0` | 0 = unlimited |

Login and registration limits are **not** configurable: 20/min per IP and 5 failures per
15 min per account for login, 5/hour per IP for registration. They are brute-force
protection, not usage caps, and an operator must not be able to disable them while raising a
usage limit.

## Embeddings

| Variable | Default | Notes |
|---|---|---|
| `EMBEDDINGS_PROVIDER` | `auto` | `auto` \| `ollama` \| `google` \| `openai` \| `none`. `auto` prefers a reachable local Ollama, then a hosted provider with a key. `none` disables memory rather than degrading it |
| `EMBEDDINGS_MODEL` | `""` | Blank uses the provider's documented default. **Changing this makes existing chunks invisible until re-indexed** |

## Tracing

| Variable | Default |
|---|---|
| `LANGCHAIN_TRACING_V2` | `false` |
| `LANGCHAIN_API_KEY` | `""` |
| `LANGCHAIN_PROJECT` | `multi-agent-research-assistant` |

## Compose-only variables

Read by `docker-compose.full.yml`, not by the application:

| Variable | Default |
|---|---|
| `POSTGRES_USER` | `research_user` |
| `POSTGRES_PASSWORD` | `research_pass` |
| `POSTGRES_DB` | `research_db` |
| `FRONTEND_PORT` | `3031` |
| `BACKEND_ORIGIN` | `http://api:8000` — baked into the frontend build as the `/api` rewrite target |

## Two configuration paths

The same run configuration is built twice, from two independent code paths:

| Path | Built by | Used by |
|---|---|---|
| Server | `app/runtime.py` ← `app/config.py` (pydantic-settings) | API, Celery worker |
| Local | `research_engine/local.py::run_config_from_env` ← `os.environ` | CLI, evaluation harness, desktop sidecar |

**Adding a setting means adding it to both.** This has drifted twice: once leaving OpenRouter
unreachable from the local path, and once applying the production SSRF guard to a laptop and
rejecting every local model server.

The engine's module defaults deliberately mirror the server settings' defaults exactly, so a
host that forgets to install a configuration degrades to the documented behaviour rather than
to something subtly different. A test pins that equivalence.

## Settings not exposed as environment variables

Some run-configuration fields are set per user or per run rather than by the environment:

| Field | Set by | Default |
|---|---|---|
| `retrieval_k` | User preferences | 5 |
| `min_sources_per_task` | User preferences | 0 (no floor) |
| `snippet_max_chars` | User preferences | 500 |
| `topic_seeds`, `outline_template` | The start request | empty / unset |
| `skip_plan_gate` | The start request; the app's form sends `false` | `true` at the API and engine level, `false` as the database column default |
| `corpus_mode`, `demo` | The start request | `false` |
| `enforce_ssrf_guards` | The host — strict on the server, relaxed on desktop | `true` |
| `max_planner_tasks` | Run configuration | 6 |
| `prompt_overrides` | Declared, no consumer yet | empty |
