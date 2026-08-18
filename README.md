# Multi-Agent Research Assistant

> A self-hostable, bring-your-own-key research assistant with an auditable
> human-in-the-loop approval gate and verifiable per-claim citations.

[![CI](https://github.com/adityamhaske/Multi-Agent-Research-Assistant/actions/workflows/ci.yml/badge.svg)](https://github.com/adityamhaske/Multi-Agent-Research-Assistant/actions/workflows/ci.yml)
[![citation support](https://img.shields.io/badge/citation%20support-90%25%20(interim)-red)](backend/evals/results/eval-2026-08-13-ollama-run7.json)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

<!-- Direct link to the release asset — this downloads the file, no landing page.
     Bump the version in BOTH the badge label and the href when cutting a release. -->
[![Download for macOS](https://img.shields.io/badge/Download-macOS%20Apple%20Silicon%20·%20.dmg-000000?style=for-the-badge&logo=apple&logoColor=white)](https://github.com/adityamhaske/Multi-Agent-Research-Assistant/releases/download/v1.0.2/Research.Assistant_1.0.2_aarch64.dmg)

Apple Silicon only (81 MB, installs to ~182 MB). The app is unsigned, so macOS blocks it on
first launch — right-click the app → **Open** → **Open**. Windows `.msi`, Linux `.deb` and
`.AppImage` are on the
[releases page](https://github.com/adityamhaske/Multi-Agent-Research-Assistant/releases/latest);
[install notes](docs/getting-started/23-desktop-app.md) cover every platform.

---

Ask a research question. A pipeline of specialized agents searches the web, gathers
evidence with sources, drafts a cited report, and **pauses for your approval** before
finalizing.

> **V2 — research that can show its work.** A run is no longer a report with citations
> attached to it. The evidence, the sources, the claims, the links between them, the
> conflicting sources and your review decision are all structured records you can inspect,
> and the report is a rendering of *them*. Three distinctions are enforced everywhere and
> never blurred: **retrieved is not verified**, **retrieved is not cited**, and **a citation
> marker is not evidence**. Approving a report freezes an artifact that a stranger can check
> offline with the verifier in this repository — no network, no model, no account.
> See [the V2 research model](docs/getting-started/24-v2-research-model.md).

Approve it, or send it back with feedback. Completed reports support grounded follow-up
chat and export as `.md`, `.pdf`, or a hash-verifiable `.bundle.json` that a third party
can check offline — no AI, no network, no account.

Verify an artifact yourself, without this application running:

```bash
python -m research_engine.verify_bundle research-abc12345.bundle.json
```

Six checks — bundle integrity, report integrity, evidence integrity, citation resolution,
claim/evidence linkage and the approval chain. Exit `0` when they all pass. A pass means the
artifact is internally consistent and unaltered since approval; it does not mean the research
is correct, which is a judgement no checker can make.

Every claim carries an inline `[n]` citation that resolves to a real source with the
verbatim supporting snippet. A citation that *doesn't* resolve renders as a visible ⚠
"unverified" chip — the system surfaces its own failures instead of hiding them.

## How it works

The pipeline is a compiled [LangGraph](https://langchain-ai.github.io/langgraph/)
`StateGraph`. Each agent has one job, and the graph's conditional edges enforce budgets
and retries.

```
                              ┌────────────── rework (bounded) ──────────────┐
                              ▼                                              │
  Query → Planner → ⏸ DESIGN GATE → Executor ⇄ Critic → Synthesizer → ⏸ REVIEW GATE → Finalizer → Report
                     (edit topics,    (tools)   (fail-   (cited draft)  (approve /              (+ chat,
                      pick outline)             closed)                  send back)              export)
```

- **Planner** decomposes the question into research tasks. Depth (`fast` / `balanced` /
  `comprehensive`) sets how many, and is therefore the main cost dial.
- **Design gate** pauses *before* anything is searched, so you edit the subtopics and pick
  the report outline while the run is still free. Drop a task and it is never researched;
  reword one and that is what gets searched. This is the difference between "the agent
  picked six queries" and "these are my six subtopics, in my review's structure".
- **Executor** runs real tool calls (`web_search`, `read_webpage`) and returns structured
  evidence.
- **Critic** grades that evidence and **fails closed** — invalid or missing critic output
  counts as a failure, never a pass — sending weak tasks back within a bounded retry limit.
- **Review gate** is a real `interrupt()` checkpoint, not a polling loop. State is durably
  checkpointed and the worker exits; approval **resumes** rather than re-running research
  you already paid for.
- **Finalizer** produces the report. Every `[n]` is a chip you can hover for the source
  title, domain, and the verbatim snippet supporting that claim.

## Self-host — one command

Prerequisites: Docker with Compose v2.

```bash
./start.sh
```

The script creates `.env` if missing (generating a JWT secret), checks your config, builds
and starts all five services, waits until every one reports healthy, and opens the app.

```bash
./start.sh --logs      # start, then follow logs
./start.sh --stop      # stop (data preserved)
./start.sh --reset     # stop and delete all data (asks first)
```

Or drive compose yourself:

```bash
cp .env.example .env
# In .env set:  JWT_SECRET_KEY=$(openssl rand -hex 32)  and a provider key.
docker compose -f docker-compose.full.yml up --build
```

Open **http://localhost:3031** → register → ask a question → watch the pipeline → approve
→ read the cited report.

The API container runs `alembic upgrade head` before serving, and the worker and frontend
wait on its readiness, so migrations apply exactly once. **The frontend is the only
published service** — it proxies `/api/*` internally, so auth cookies stay first-party and
the database is never exposed.

### Native development

```bash
make infra-up                              # Postgres + Redis only
make backend-setup && make migrate
make backend-dev                           # API  → :8000
make worker                                # Celery worker (new terminal)
make frontend-setup && make frontend-dev   # UI   → :3031 (new terminal)

make test / test-backend / test-frontend   # pytest + Vitest
make eval                                  # report-quality eval suite
make lint / format
```

## Bring your own key

Users can paste their own provider key and run research on their own account. The key is
**encrypted at rest** (Fernet/AES), never returned by any endpoint, and never sent back to
the browser — the UI shows only the last four characters.

Supported providers: **Anthropic**, **Google**, **OpenAI**, **OpenRouter**, plus any
OpenAI-compatible endpoint (`custom:`) and local models via **Ollama**. A user without a
key falls back to the deployment's shared server key, subject to their monthly token limit.

For a public deployment, require BYOK from everyone and leave the server key unset:

```bash
ENVIRONMENT=production                  # secure cookies, /docs disabled
DEFAULT_MONTHLY_TOKEN_LIMIT=50000       # applied to every new account
ENCRYPTION_KEY=<openssl rand -hex 32>   # encrypts users' stored keys
```

> **`ENCRYPTION_KEY` is what protects your users' API keys.** Unset, it derives from
> `JWT_SECRET_KEY` — which works, but rotating your JWT secret then makes every stored key
> undecryptable. Set it explicitly in production so the two rotate independently.

## Architecture

- **Backend** — FastAPI + Celery worker, PostgreSQL 16 (pgvector), Redis 7
- **Agents** — LangGraph `StateGraph` with Postgres checkpointing; HITL via `interrupt()`;
  structured Pydantic outputs; fail-closed critic; per-session cost and wall-clock budgets
- **LLMs** — provider-pluggable via `MODEL_*` routing (`provider:model`), per agent role
- **Search** — Tavily → Brave → DuckDuckGo fallback, Redis-cached, with an SSRF guard on
  page fetching and untrusted-content framing around everything the web returns
- **Frontend** — Next.js 16 (App Router), Tailwind v4, TanStack Query; same-origin `/api`
  proxy so cookies stay first-party and SSE authenticates natively
- **Security** — httpOnly cookie auth with rotating refresh tokens and reuse detection,
  per-operation atomic rate limits, encrypted BYOK keys, strict CSP
  ([Security](docs/architecture/06-security.md))

## Configuration

Every variable is documented in [`.env.example`](.env.example) and validated at startup —
the app refuses to boot with a placeholder or short `JWT_SECRET_KEY`.

| Variable | Required | Notes |
|---|---|---|
| `JWT_SECRET_KEY` | ✅ | ≥ 32 random chars (`openssl rand -hex 32`) |
| `DATABASE_URL`, `REDIS_URL` | ✅ | Set for you by the full-stack compose |
| `MODEL_PLANNER` … `MODEL_CHAT` | ⚪ | `provider:model` per agent role |
| `ENCRYPTION_KEY` | ⚪ (prod) | Encrypts users' stored keys |
| `DEFAULT_MONTHLY_TOKEN_LIMIT` | ⚪ | Token cap for new accounts; `0` = unlimited |
| `MAX_COST_PER_SESSION_USD` | ⚪ | Per-session budget; **`0` = unlimited, and `0` is the default** |
| `ENVIRONMENT` | ⚪ | `development` or `production` |

> **Every run limit is `0 = unlimited`, and `0` is the default** — cost, wall-clock, and
> input tokens alike. Nothing stops a long run out of the box; set them when you want a hard
> stop. And `MAX_COST_PER_SESSION_USD` is a **no-op on `openrouter` and `custom` routes** —
> those providers are skipped by the price catalog, so estimated cost is `0.00` and the cap
> never trips. Cap spend at the provider for those.

Full list with exact defaults: [Configuration reference](docs/reference/36-configuration.md).

## Measured quality

Latest real-model run:
[`eval-2026-08-13-ollama-run7.json`](backend/evals/results/eval-2026-08-13-ollama-run7.json),
10 queries across 8 domains.

| Metric | Result |
|---|---|
| Reports completed | **10 / 10** |
| Citation support rate | **90%** — cited sentences whose snippets actually support them |
| Citation resolution rate | **95%** — inline `[n]` markers pointing at a real source |
| Uncited claims | 14.9 per report (avg) |
| Latency | 514 s per report |

**Stated plainly:** this misses the 0.95 release threshold, and it is **self-judged** — the
grader was the same local model that wrote the report, not a human and not an independent
model. It answers "is this claim supported by what we extracted from the source it cites?",
which is weaker than "is this claim true". Ten queries is a small set. Treat it as a
regression signal, not a benchmark.

Every run records its own method block, and `metrics_version` is bumped whenever a
definition changes, so two runs are never silently compared across incompatible metrics.
Method, caveats, and what a *published* benchmark would require are in
[Citation-fidelity benchmark](docs/research/16-citation-fidelity-benchmark.md).

## Deployment

Single host plus a TLS reverse proxy in front of the frontend
([Deployment](docs/deployment/30-production.md)):

- [`deploy/README.md`](deploy/README.md) — host the whole stack for **$0/month** on an
  Oracle Cloud Always Free VM, HTTPS included, no domain required
- [`deploy/Caddyfile`](deploy/Caddyfile) — automatic-HTTPS reverse proxy
- [`deploy/backup-postgres.sh`](deploy/backup-postgres.sh) — nightly `pg_dump` with cron
  and restore examples

Tagging `vX.Y.Z` triggers [`release.yml`](.github/workflows/release.yml), which builds
multi-arch (`amd64` + `arm64`) api/worker/frontend images to GHCR and cuts a GitHub
Release; [`desktop.yml`](.github/workflows/desktop.yml) builds and attaches the desktop
bundles.

## Documentation

Read it online at
**[adityamhaske.github.io/Multi-Agent-Research-Assistant/docs](https://adityamhaske.github.io/Multi-Agent-Research-Assistant/docs/)**,
or in this repository under [`docs/`](docs/00_INDEX.md).

**New here:** [Overview](docs/getting-started/01-overview.md) →
[Quick start](docs/getting-started/20-quick-start.md) →
[Configuration](docs/getting-started/21-configuration.md)

| | |
|---|---|
| **Using it** | [Running research](docs/user-guide/25-running-research.md) · [Review & approval](docs/user-guide/26-review-and-approval.md) · [Citations](docs/user-guide/27-citations.md) · [Projects & memory](docs/user-guide/28-projects-and-memory.md) · [Exports](docs/user-guide/29-exports.md) |
| **How it works** | [System architecture](docs/architecture/02-system-architecture.md) · [Agent architecture](docs/architecture/04-agent-architecture.md) · [Data model](docs/architecture/05-data-model.md) · [Local & self-hosted](docs/architecture/13-local-and-self-hosted.md) · [Security](docs/architecture/06-security.md) |
| **Running it** | [Docker](docs/deployment/09-docker.md) · [Production](docs/deployment/30-production.md) · [Operations](docs/deployment/31-operations.md) |
| **Changing it** | [Development](docs/developers/32-development.md) · [Testing & evaluation](docs/developers/08-testing-and-evaluation.md) · [Engineering guidelines](docs/developers/11-engineering-guidelines.md) · [Contributing](docs/developers/33-contributing.md) |
| **Reference** | [API](docs/reference/34-api.md) · [SSE protocol](docs/reference/35-sse.md) · [Bundle format](docs/reference/15-bundle-format.md) · [Configuration](docs/reference/36-configuration.md) |
| **Project** | [Roadmap](docs/project/10-roadmap.md) · [Changelog](docs/project/37-changelog.md) · [Benchmark methodology](docs/research/16-citation-fidelity-benchmark.md) |

## License

[MIT](LICENSE) — free to use, modify, and self-host, commercially or otherwise.
