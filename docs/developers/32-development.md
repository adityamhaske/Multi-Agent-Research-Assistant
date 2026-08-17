# Development guide

Getting set up to change the code.

## Prerequisites

Python 3.11+, Node 22+, and Docker (for Postgres and Redis).

## Setup

```bash
git clone https://github.com/adityamhaske/Multi-Agent-Research-Assistant.git
cd Multi-Agent-Research-Assistant
cp .env.example .env
# Set JWT_SECRET_KEY (openssl rand -hex 32) and a provider key, or use LLM_MODE=fake
```

Run the datastores in Docker and the application natively, so you get reload:

```bash
make infra-up                              # Postgres (pgvector) + Redis
make backend-setup                         # creates backend/.venv, installs deps
make migrate                               # alembic upgrade head
make backend-dev                           # API  → http://localhost:8000
make worker                                # Celery worker (separate terminal)
make frontend-setup && make frontend-dev   # UI   → http://localhost:3031
```

**The frontend dev port is 3031, not 3000.** `FRONTEND_URL` in `.env` is the dev-only CORS
allow-list and must match, or the API rejects the browser.

You need the worker running. Without it, sessions sit on `PENDING` forever.

## Repository layout

```
backend/
  research_engine/   the pipeline. No FastAPI, Celery, SQLAlchemy, or Redis
  app/               the server host: API, workers, models, services
    api/v1/          HTTP only — no business logic
    services/        reusable and HTTP-free: auth, crypto, rate limits, export, memory
    workers/         Celery tasks and the pipeline runner
    models/          SQLAlchemy 2.0 typed mappings
  desktop/           the desktop host (sidecar)
  evals/             measurement harness and committed results
  alembic/           migrations — the only schema writer
  tests/
frontend/
  app/(app)/         the product, behind login
  app/(site)/        the public site: landing, docs, releases, download
  components/  lib/  hooks/
docs/                this documentation
deploy/              Caddy, backup script, Oracle bootstrap
internal/            engineering notes — not documentation
```

**Layering rule:** `research_engine` never imports from `app`, and never imports a server
dependency. A test AST-scans every engine module and fails on any host import. That boundary
is what lets the whole pipeline run in a test with no HTTP stack, and what makes the desktop
build possible.

## Running things without the server

The engine has its own CLI, useful for iterating on the graph:

```bash
cd backend
python -m research_engine.cli --help
```

It needs no `DATABASE_URL` and no `JWT_SECRET_KEY`, and it can drive a complete run to the
review gate and then finalise from a SQLite checkpoint in a **separate process**.

## Tests

```bash
make test              # backend + frontend
make test-backend      # pytest
make test-frontend     # vitest
```

What CI actually runs — green locally is not green in CI unless you run these:

```bash
cd backend && ruff check app/ research_engine/ tests/ evals/ \
  && ruff format --check app/ research_engine/ tests/ evals/ \
  && python -m pytest
```

```bash
cd frontend && npm run lint && npm run typecheck && npm test && npm run build
```

Note the backend lint path **includes `evals/`** and excludes `desktop/`, `alembic/`, and
repository-root scripts. A lint-clean `app/` is not a green build.

Full strategy: [Testing and evaluation](08-testing-and-evaluation.md).

## The four greps that fail the build

CI runs four bespoke greps over `app/ components/ lib/ hooks/` in the frontend. They are not
lint rules and `npm run lint` will not catch them:

1. No `dangerouslySetInnerHTML`, no `rehype-raw`.
2. No hardcoded hex colours — every colour is a token in `app/globals.css`.
3. No hardcoded backend URLs — the browser calls the same-origin `/api` proxy.
4. No `localStorage` or `sessionStorage` without an inline `ci-allow-web-storage: <reason>`
   marker on the same line.

Two traps worth knowing before you spend an afternoon on them:

**They are GNU grep, and your shell's `grep` may not be.** On a machine where `grep` resolves
to `ugrep`, an alias, or a Homebrew shim, it can report *no match where CI finds one*.
Verify with `/usr/bin/grep`, running the commands from `.github/workflows/ci.yml` verbatim.

**They cannot tell a use from a mention.** They are plain greps over source, so a *comment*
naming a banned token fails the build as surely as calling one. Describe the rule without
writing the names.

A raw control character in a source file compounds this: GNU grep prints `Binary file …
matches` instead of the offending line, so the failure names the file and hides the reason.
Prefer an escape sequence over an embedded NUL byte.

## Frontend specifics

**Three build targets, not two.** `next.config.ts` branches on `NEXT_PUBLIC_PAGES` (a static
export for GitHub Pages, with a `basePath`), then `NEXT_PUBLIC_DESKTOP` (a static export for
Tauri), then the standalone server image. A flag read at build time collapses to dead code in
the other two, which is what keeps them isolated — and also means **a branch is only
exercised by the target that builds it**:

```bash
npm run build           # standalone server image
npm run build:desktop   # Tauri static export
npm run build:pages     # GitHub Pages static export
```

CI runs the first two. Anything touching `app/(site)/` or `app/layout.tsx` needs all three
run locally.

**Session routes are generated.** `app/(app)/session/` is generated and gitignored;
`scripts/prepare-session-routes.mjs` copies from `app-routes/session/{web,desktop}/` before
`dev`, `build`, and `e2e`. Edit `app-routes/`, never the generated directory. Note that
`build:pages` deliberately does **not** run that script — it would recreate a route whose web
variant has no `generateStaticParams` and fail the export.

**In Docker the frontend is a static build**, not a bind mount. Source edits need
`docker compose -f docker-compose.full.yml build frontend`; a reload shows stale UI.

## Migrations

```bash
make migration msg="add the thing"   # autogenerate
make migrate                          # upgrade head
```

- Alembic is the only schema writer. No `create_all` in application code.
- Every migration needs a real `downgrade()`; the round-trip is exercised in CI.
- Migrations are append-only once merged — fixing a merged one means writing a new one.
- **A schema change needs two edits**: the migration (for Postgres) and the ORM model, which
  is what the desktop build's schema sync reads.

## Documentation

`docs/` is rendered by the public site at build time, so a documentation change is a site
change. If you add a page, add its slug to `NAV_ORDER` in `frontend/lib/docs.ts` — a page
missing from that list still renders, it just sorts last in its section.

Documentation that contradicts shipped code must be fixed **in the same pull request** that
changed the behaviour.

## Where things bite

| Change | Watch for |
|---|---|
| Reading a model response's content directly | Use the shared text extractor, or you break providers that return content blocks |
| Adding an SSE endpoint | Use the shared SSE headers, or a proxy buffers it into silence |
| Touching the executor's evidence path | Keep the tool-free fallback and the log line; a silent empty list is the failure mode |
| Touching the critic | Keep it failing closed |
| Adding a model route | Add a catalog entry, or startup refuses to boot — by design |
| Anything with a user's key | It must never enter a response body, a log, or a module global |
| A new graph node | Budgets live on edges; make sure your path passes through one |
| A new session status or pause event | Update the server **and** the desktop sidecar |
