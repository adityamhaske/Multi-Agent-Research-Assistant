# Multi-Agent Research Assistant

> A self-hostable, bring-your-own-key research assistant with an auditable
> human-in-the-loop approval gate and verifiable per-claim citations.

[![CI](https://github.com/adityamhaske/Multi-Agent-Research-Assistant/actions/workflows/ci.yml/badge.svg)](https://github.com/adityamhaske/Multi-Agent-Research-Assistant/actions/workflows/ci.yml)
[![eval](https://img.shields.io/badge/eval-baseline%20recorded-blue)](backend/evals/results/)

A user submits a research question. A pipeline of specialized agents (**Planner →
Executor → Critic → Synthesizer**) searches the web, gathers evidence with sources,
drafts a cited Markdown report, and pauses at a **mandatory human approval gate** —
approve to finalize, or reject with feedback to send the agents back to work. Completed
reports support grounded follow-up chat and Markdown export.

Every claim carries an inline `[n]` citation that resolves to a source with the verbatim
supporting snippet; a citation that doesn't resolve is shown as a visible ⚠ "unverified"
chip rather than hidden.

## Status

All milestones are code-complete and CI-gated; see
[docs/10_Roadmap.md](docs/10_Roadmap.md) for full definitions.

| Milestone | Scope | Status |
|---|---|---|
| M0 | Truth reset: honest docs/README, config validation, test scaffold, CI | ✅ |
| M1 | Agent pipeline on LangGraph with checkpointed HITL resume | ✅ |
| M2 | Auth & API hardening (cookie auth, rate limits, SSRF guard, SSE replay) | ✅ |
| M3 | Frontend rebuild (citations UX, resilient streaming, TanStack Query) | ✅ |
| M4 | Ship: Docker images, full compose, eval harness, deploy guide | ✅ |

The full golden path — **register → cited report → approve → export** — runs end-to-end
through the packaged stack and is exercised in CI by three Playwright golden journeys
against real Postgres + Redis in deterministic fake-LLM mode.

## Quick start — full stack, one command

Prerequisites: Docker with Compose v2.

```bash
# 1. Configure
cp .env.example .env
# In .env, set a real secret:      JWT_SECRET_KEY=$(openssl rand -hex 32)
# For a keyless demo, set:          LLM_MODE=fake      (deterministic fixtures, no API keys)
# For real research instead, set:   LLM_MODE=real  and  GOOGLE_API_KEY=<your key>

# 2. Launch everything (postgres, redis, api, worker, frontend)
LLM_MODE=fake docker compose -f docker-compose.full.yml up --build
#   equivalently:  LLM_MODE=fake make compose-up
```

Then open **http://localhost:3000** → register → ask a question → watch the pipeline in
the live monitor → approve the draft → read the cited report → export `.md`.

The api container runs `alembic upgrade head` before serving, and the worker and frontend
wait on its readiness — so migrations apply exactly once, automatically. The **frontend is
the only published service**; it proxies `/api/*` to the api over the internal network, so
auth cookies stay first-party and the api/database/redis are never exposed.

> A [Gemini API key](https://aistudio.google.com/apikey) is only needed for real research
> (`LLM_MODE=real`). The keyless `fake` mode returns scripted models and fixture sources so
> you can exercise the whole flow — pipeline, approval gate, citations, chat — for free.

## Quick start — native development

Run Postgres + Redis in containers and the app processes natively for hot reload:

```bash
cp .env.example .env          # set JWT_SECRET_KEY and GOOGLE_API_KEY (or LLM_MODE=fake)
make infra-up                 # Postgres + Redis
make backend-setup && make migrate
make backend-dev              # API  → http://localhost:8000  (docs at /docs in dev)
make worker                   # Celery worker (new terminal)
make frontend-setup && make frontend-dev   # UI → http://localhost:3000 (new terminal)
```

### Make targets

```bash
make compose-up / compose-down / compose-logs   # full stack via docker compose
make infra-up / infra-down / infra-clean        # dev: Postgres + Redis only
make backend-setup / backend-dev / worker       # venv + API + Celery worker
make migrate / migration msg="..."              # Alembic
make frontend-setup / frontend-dev              # Next.js
make test / test-backend / test-frontend        # pytest + Vitest
make eval                                       # report-quality eval suite (docs/08 §5)
make lint / format                              # ruff + eslint
```

## Architecture ([docs/02](docs/02_System_Architecture.md))

- **Backend**: FastAPI + Celery worker, PostgreSQL 16, Redis 7
- **Agents**: LangGraph `StateGraph` with Postgres checkpointing; HITL via `interrupt()`
  so approval/rework resume from the gate instead of re-running; structured Pydantic
  outputs; fail-closed quality critic; per-session cost/time budgets
- **LLMs**: BYOK, provider-pluggable — Gemini 2.5 by default (`MODEL_*` env routing);
  `LLM_MODE=fake` swaps in scripted models + fixture retrievers for tests/demos
- **Search**: retriever chain with fallback — Tavily → Brave → DuckDuckGo, Redis-cached;
  SSRF guard on page fetching; untrusted-content framing
- **Frontend**: Next.js 16 (App Router), Tailwind v4, TanStack Query; same-origin `/api`
  proxy so cookies stay first-party and SSE authenticates natively; the live monitor
  streams pipeline events with `Last-Event-ID` replay and a polling fallback
- **Security** ([docs/06](docs/06_Security.md)): httpOnly cookie auth with rotating
  refresh tokens + reuse detection, per-operation atomic rate limits, security headers,
  strict CSP

## Configuration

Every variable is documented in [`.env.example`](.env.example) and validated at startup
(`backend/app/config.py`): the app refuses to boot with a placeholder or short
`JWT_SECRET_KEY`, and in production it verifies every routed model provider has an API key.

| Variable | Required | Notes |
|---|---|---|
| `JWT_SECRET_KEY` | ✅ | ≥ 32 random chars; placeholders refused (`openssl rand -hex 32`) |
| `DATABASE_URL` | ✅ | async PostgreSQL DSN (set for you in the full-stack compose) |
| `REDIS_URL` | ✅ | broker, cache, pub/sub (set for you in compose) |
| `LLM_MODE` | ⚪ | `real` (default) or `fake` (keyless deterministic) |
| `GOOGLE_API_KEY` | with default routing | BYOK; not needed in `fake` mode |
| `MODEL_PLANNER` … `MODEL_CHAT` | ⚪ | `provider:model` routing per agent role |
| `TAVILY_API_KEY`, `BRAVE_API_KEY` | ⚪ | optional retrievers; DuckDuckGo is the keyless fallback |
| `MAX_COST_PER_SESSION_USD` | ⚪ | hard budget per session (default 0.50) |
| `ENVIRONMENT` | ⚪ | `development` (default) or `production` (Secure cookies, `/docs` off) |

## Testing & quality ([docs/08](docs/08_Testing_and_Quality.md))

- **Backend**: pytest — unit, pipeline (fake-LLM graph), and integration (real
  Postgres + Redis) suites; migrations are applied on every CI run.
- **Frontend**: Vitest (SSE parser, citation renderer, derivations) + `next build`.
- **Golden E2E**: three Playwright journeys through the packaged stack in fake-LLM mode.
- **Evals**: `make eval` runs a fixed query set and records report-quality metrics to
  `backend/evals/results/` as dated JSON, diffable over time.

## Deployment ([docs/09](docs/09_Deployment_and_Operations.md))

Single host + a TLS reverse proxy in front of the frontend. Example artifacts:

- [`deploy/Caddyfile`](deploy/Caddyfile) — automatic-HTTPS reverse proxy (set your
  domain and `ENVIRONMENT=production`).
- [`deploy/backup-postgres.sh`](deploy/backup-postgres.sh) — nightly `pg_dump` with a
  cron example; a single dump captures full state (reports, audit rows, checkpoints).

Tagging `vX.Y.Z` triggers [`release.yml`](.github/workflows/release.yml), which builds and
pushes the api/worker/frontend images to GHCR and cuts a GitHub Release.

## Documentation

The build contract lives in [`docs/`](docs/00_INDEX.md):
[Vision](docs/01_Product_Vision.md) ·
[Architecture](docs/02_System_Architecture.md) ·
[Tech Stack](docs/03_Tech_Stack.md) ·
[Agent Design](docs/04_Agent_Design.md) ·
[Data & API](docs/05_Data_and_API.md) ·
[Security](docs/06_Security.md) ·
[UI/UX](docs/07_UIUX_Guidelines.md) ·
[Testing](docs/08_Testing_and_Quality.md) ·
[Deployment](docs/09_Deployment_and_Operations.md) ·
[Roadmap](docs/10_Roadmap.md) ·
[Standards](docs/11_Engineering_Standards.md)

## License

No license has been set yet — add a `LICENSE` file to choose one (MIT is the
conventional choice for a self-hostable BYOK tool). Until then, all rights are reserved.
