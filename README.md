# Multi-Agent Research Assistant

> A self-hostable, bring-your-own-key research assistant with an auditable
> human-in-the-loop approval gate and verifiable per-claim citations.

A user submits a research question. A pipeline of specialized agents (Planner →
Executor → Critic → Synthesizer) searches the web, gathers evidence with sources,
drafts a cited Markdown report, and pauses at a **mandatory human approval gate** —
approve to finalize, or reject with feedback to send the agents back to work. Completed
reports support grounded follow-up chat and export to Markdown/PDF.

## ⚠️ Project status: active rebuild

This codebase is mid-overhaul against the specifications in [`docs/`](docs/00_INDEX.md).
The table below is the truth about what works today — see
[docs/10_Roadmap.md](docs/10_Roadmap.md) for full milestone definitions.

| Milestone | Scope | Status |
|---|---|---|
| M0 | Truth reset: honest docs/README, config validation, test scaffold, CI | ✅ done |
| M1 | Agent pipeline rebuilt on LangGraph with checkpointed HITL resume | ☐ next |
| M2 | Auth & API hardening (cookie auth, rate limits, SSRF guard, SSE replay) | ☐ |
| M3 | Frontend rebuild (citations UX, resilient streaming, TanStack Query) | ☐ |
| M4 | Ship: Docker images, full compose, eval harness, deploy guide | ☐ |

**Until M1 lands, the research pipeline is not functional end-to-end.** The previous
implementation had critical defects (tool calls never executed, approval could not
complete a session, unauthenticated event stream) that are documented in the roadmap
and being replaced rather than patched.

## Architecture (target — see [docs/02](docs/02_System_Architecture.md))

- **Backend**: FastAPI + Celery worker, PostgreSQL 16, Redis 7
- **Agents**: LangGraph `StateGraph` with Postgres checkpointing; HITL via
  `interrupt()`; structured Pydantic outputs; fail-closed quality gate
- **LLMs**: BYOK, provider-pluggable — Gemini 2.5 by default (`MODEL_*` env routing)
- **Search**: retriever chain with fallback — Tavily → Brave → DuckDuckGo, Redis-cached
- **Frontend**: Next.js 16 (App Router), Tailwind v4, TanStack Query; same-origin
  `/api` proxy so auth cookies stay first-party and SSE works natively
- **Security**: httpOnly cookie auth with refresh rotation, SSRF guard on page
  fetching, prompt-injection framing, per-operation rate limits
  ([docs/06](docs/06_Security.md))

## Quick start (development)

Prerequisites: Docker Desktop, Python 3.11+, Node.js 18+, and a
[Gemini API key](https://aistudio.google.com/apikey) (or run `LLM_MODE=fake` with no
keys).

```bash
# 1. Environment
cp .env.example .env
# Edit .env: set JWT_SECRET_KEY (openssl rand -hex 32) and GOOGLE_API_KEY

# 2. Infrastructure (Postgres + Redis)
make infra-up

# 3. Backend
make backend-setup
make migrate
make backend-dev        # API on http://localhost:8000

# 4. Worker (new terminal)
make worker

# 5. Frontend (new terminal)
make frontend-setup
make frontend-dev       # UI on http://localhost:3000
```

API docs (dev only): http://localhost:8000/docs

### Make targets

```bash
make infra-up / infra-down / infra-clean   # Postgres + Redis containers
make backend-setup / backend-dev / worker  # venv + API + Celery worker
make migrate / migration msg="..."         # Alembic
make frontend-setup / frontend-dev         # Next.js
make test                                  # backend pytest suite
make lint / format                         # ruff + eslint
```

## Configuration

Every variable is documented in [`.env.example`](.env.example) and validated at
startup (`backend/app/config.py`) — the app refuses to boot with a placeholder or
short `JWT_SECRET_KEY`, and in production it verifies that every routed model
provider has an API key.

| Variable | Required | Notes |
|---|---|---|
| `DATABASE_URL` | ✅ | async PostgreSQL DSN |
| `REDIS_URL` | ✅ | broker, cache, pub/sub |
| `JWT_SECRET_KEY` | ✅ | ≥ 32 random chars; placeholders refused |
| `GOOGLE_API_KEY` | with default routing | BYOK; `LLM_MODE=fake` needs no keys |
| `MODEL_PLANNER` … `MODEL_CHAT` | ⚪ | `provider:model` routing per agent role |
| `TAVILY_API_KEY`, `BRAVE_API_KEY` | ⚪ | optional retrievers; DuckDuckGo is the keyless fallback |
| `MAX_COST_PER_SESSION_USD` | ⚪ | hard budget per session (default 0.50) |

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
