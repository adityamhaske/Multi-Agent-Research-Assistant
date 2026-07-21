# 03. Tech Stack

> Exact technologies and the reason each earns its place. Versions are minimums;
> pin exact versions in `requirements.txt` / `package.json` and record upgrades in PRs.
> **Rule:** a dependency that is not imported anywhere gets removed. No résumé deps.

## Backend

| Layer | Technology | Version | Why |
|---|---|---|---|
| Language | Python | 3.11+ | Async maturity, typing, ecosystem |
| API framework | FastAPI | current | Async-native, Pydantic v2, OpenAPI out of the box |
| Agent orchestration | **LangGraph** | ≥ 1.0 | Real `StateGraph` with `ToolNode`, conditional edges, `interrupt()` for HITL, and Postgres checkpointing. This is the load-bearing choice: checkpoint-resume is what makes the approval gate correct |
| Checkpointer | `langgraph-checkpoint-postgres` | current | Durable graph state in the same Postgres we already run; resume survives worker restarts |
| LLM abstraction | `langchain-core` + provider packages | current | Uniform tool-calling & structured output across providers (BYOK) |
| Default LLM provider | Google Gemini (`langchain-google-genai`) | current | Best price/quality at default tier. **Model IDs live in config, never in code.** Defaults: `gemini-2.5-pro` (planner/synthesizer), `gemini-2.5-flash` (executor/critic/chat). Verify current IDs at implementation time — 1.5-generation models are retired |
| Optional providers | `langchain-anthropic`, `langchain-openai` | current | BYOK pluggability via the LLM factory; enabled by env config only |
| Web search | Tavily API → Brave Search API → `ddgs` | current | Ordered fallback chain. Tavily/Brave are reliable, keyed APIs; DuckDuckGo scraping is the keyless fallback of last resort (endemic rate-limiting — never the sole retriever). Results cached in Redis (24h TTL, keyed by normalized query) |
| Page fetching | httpx + BeautifulSoup4 + lxml | current | Async fetch with the SSRF guard from [06_Security.md](06_Security.md) |
| Database | PostgreSQL | 16 | Relational core + JSONB + LangGraph checkpoints |
| ORM | SQLAlchemy (async) + asyncpg | 2.0+ | Typed 2.0-style mappings |
| Migrations | Alembic | current | **Single source of schema truth. No `create_all` anywhere in app code** |
| Queue | Celery + Redis broker | 5.x | Boring, proven background execution; worker scales independently |
| Cache/pub-sub | Redis | 7 | SSE fan-out, rate limits, locks, search cache |
| Auth | PyJWT + bcrypt (direct, no passlib) | current | passlib is unmaintained and conflicts with bcrypt ≥ 4.1; use `bcrypt` directly |
| Logging | structlog | current | JSON structured logs with bound context |
| PDF export | WeasyPrint | current | Markdown → HTML → PDF server-side |
| Testing | pytest, pytest-asyncio, httpx ASGI client | current | See [08](08_Testing_and_Quality.md) |
| Lint/format | ruff (lint + format) | current | One tool, enforced in CI |

## Frontend

| Layer | Technology | Version | Why |
|---|---|---|---|
| Framework | Next.js (App Router) | 16.x | Already adopted; server components + `rewrites` proxy give us same-origin API and first-party cookies. **Note:** Next 16 has breaking changes vs. training-data conventions — consult `node_modules/next/dist/docs/` before non-trivial framework usage (per `frontend/AGENTS.md`) |
| UI library | React | 19.x | Ships with Next 16 |
| Styling | Tailwind CSS v4 + `@tailwindcss/typography` | 4.x | Utility CSS; typography plugin is **required** — report/chat rendering depends on `prose` classes |
| Server state | TanStack Query | 5.x | All API reads/mutations go through it: caching, retries, invalidation. No hand-rolled fetch-in-useEffect |
| Client state | React context/useState only | — | Auth state derives from the `/auth/me` query; no separate store until a real need exists (Zustand was removed as an unused dep) |
| Markdown | react-markdown + remark-gfm | 10.x / 4.x | Safe defaults: **never add `rehype-raw`** (CI-guarded, see [06](06_Security.md)) |
| Toasts | react-hot-toast | current | Replaces hand-rolled toast state |
| Fonts | `next/font` (Inter, JetBrains Mono) | — | Self-hosted, no render-blocking external CSS imports |
| Theming | next-themes | current | Class-based dark/light; tokens only — no hardcoded hex in components ([07](07_UIUX_Guidelines.md)) |
| Testing | Vitest + Testing Library; Playwright for E2E | current | See [08](08_Testing_and_Quality.md) |

## Infrastructure

| Concern | Technology | Notes |
|---|---|---|
| Local dev | Docker Compose (`postgres`, `redis`) + native `uvicorn`/`next dev` | `make` targets |
| Full-stack run | Docker Compose (api, worker, frontend, postgres, redis) | One command; migrations run in the api entrypoint before serve |
| CI | GitHub Actions | lint → typecheck → unit → integration → golden E2E; see [09](09_Deployment_and_Operations.md) |
| Production | Docker Compose on a single host (documented) | Kubernetes intentionally **[PLANNED]** — no manifests until a real scaling need exists |
| Tracing | LangSmith (optional, env-gated) | Off by default; self-host friendly |

## Explicitly rejected / removed

| Item | Reason |
|---|---|
| `passlib` | Unmaintained; bcrypt ≥ 4.1 incompatibility. Use `bcrypt` directly |
| `duckduckgo-search` as sole retriever | Endemic `RatelimitException`; demoted to last-resort fallback via `ddgs` |
| Zustand | Installed-but-unused in the previous iteration; add back only with a concrete use case |
| Hand-rolled agent loop | The "simplified for M1" loop caused four shipped critical bugs; LangGraph from slice one |
| `localStorage` tokens | XSS-exfiltratable and incompatible with `EventSource` auth; cookies via same-origin proxy |
| `Base.metadata.create_all` at startup | Masked an empty migration in the previous iteration; Alembic only |

## Upgrade policy

- Dependabot (or a monthly manual pass) for patch/minor updates; majors get a short
  written impact note in the PR.
- Model IDs and the price table live in config; when a provider deprecates a model,
  the config change + price-table update is one small PR, with the eval suite
  ([08](08_Testing_and_Quality.md) §5) run against the new model before merge.
