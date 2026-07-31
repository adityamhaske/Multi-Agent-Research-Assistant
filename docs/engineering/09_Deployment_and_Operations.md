# 09. Deployment & Operations

> Honest infrastructure: what actually exists and how to run it. Kubernetes is
> deliberately out of scope until a real scaling need exists.

## 1. Artifacts

| Artifact | Path | Contents |
|---|---|---|
| API image | `backend/Dockerfile` (target `api`) | Python slim, non-root user, uvicorn |
| Worker image | `backend/Dockerfile` (target `worker`) | same base, celery entrypoint |
| Frontend image | `frontend/Dockerfile` | Next.js standalone output |
| Dev infra | `docker-compose.yml` | postgres + redis only (app runs natively) |
| Full stack | `docker-compose.full.yml` | api, worker, frontend, postgres, redis |

Image rules: multi-stage builds, non-root runtime user, pinned base images,
`HEALTHCHECK` instructions, no secrets baked into layers.

## 2. Environments

| Env | How | Notes |
|---|---|---|
| Local dev | `make infra-up` + `make backend-dev` + `make worker` + `make frontend-dev` | hot reload; `.env` from `.env.example` |
| Full-stack local / demo | `docker compose -f docker-compose.full.yml up` | one command; the 15-minute clone-to-report path from [01](../product/01_Product_Vision.md) |
| Production (single host) | same compose file + TLS reverse proxy (Caddy/Traefik) in front of the frontend | documented in README; frontend is the only public service |

## 3. Configuration

- All config via environment variables, parsed by `pydantic-settings` in
  `app/config.py`. `.env.example` lists **every** variable with a comment and safe
  default; CI asserts `.env.example` and `Settings` stay in sync.
- Key variables: `DATABASE_URL`, `REDIS_URL`, `JWT_SECRET_KEY`,
  `GOOGLE_API_KEY` (+ optional `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` /
  `TAVILY_API_KEY` / `BRAVE_API_KEY`), `MODEL_*` role routing,
  `MAX_COST_PER_SESSION_USD`, `ENVIRONMENT` (`development`/`production`),
  `LLM_MODE` (`real`/`fake`), `REQUIRE_EMAIL_VERIFICATION`.
- Startup validation fails fast on: placeholder/short JWT secret, unpriced routed
  model, missing provider key for a routed provider, `ENVIRONMENT=production` with
  docs enabled.

## 4. Migrations

- API container entrypoint: `alembic upgrade head` → start uvicorn. The worker waits
  for the API healthcheck (compose `depends_on: condition: service_healthy`), so
  migrations run exactly once per deploy before traffic.
- Rollback: `alembic downgrade -1` is guaranteed to work by the round-trip CI test.
- **No `create_all` anywhere.** LangGraph checkpoint tables are created by an Alembic
  migration that calls the library's setup, keeping one migration history.

## 5. Operations runbook

| Symptom | First checks | Likely cause / action |
|---|---|---|
| Session stuck `PENDING` | worker logs; `celery inspect active`; Redis up? | worker down or broker unreachable — restart worker; task will be picked up |
| Session stuck `RUNNING` | `agent_logs` tail for the session; lock TTL | worker crashed mid-run → lock expires, session is resumable from checkpoint via re-enqueue; if budget/time exceeded it self-FAILs |
| Live feed empty but research completes | SSE endpoint reachable? proxy buffering? | ensure reverse proxy disables buffering for `text/event-stream` (`X-Accel-Buffering: no` is set by the API) |
| All searches failing | retriever chain logs (which retrievers errored) | Tavily/Brave keys missing/exhausted and DDG rate-limited → add keys; check Redis cache hit rate |
| LLM errors / 429s | provider status; per-role model config | switch role routing to a fallback provider (BYOK); budgets prevent runaway retries |
| Cost spike | `sessions.total_cost_usd` by day; evals diff | model/prompt change without eval — revert; check price table matches provider pricing |

## 6. Backups & data

- Postgres: nightly `pg_dump` (documented cron example); checkpoints and reports are
  all in Postgres, so a single dump captures full state.
- Redis is disposable (queues/caches/rate-limits only); no backups. A Redis flush must
  never lose user data — anything durable lives in Postgres.
- User data deletion: deleting a user cascades sessions → logs/messages/audit rows
  (DB-level), satisfying self-host data-removal expectations.

## 7. Observability in production

- Structured JSON logs to stdout (compose/`journald` collects); every line carries
  `session_id`, `request_id`, `node`.
- `/health` (liveness) and `/health/ready` (DB + Redis) wired into compose
  healthchecks.
- LangSmith tracing opt-in via env for debugging agent behavior.
- **[PLANNED M4]** `/metrics` Prometheus endpoint + Grafana dashboard JSON in
  `ops/`.

## 8. Release process

1. Green CI on `main` (includes golden E2E).
2. Eval run recorded if prompts/models changed.
3. Security checklist ([06](06_Security.md) §8) reviewed for public-facing deploys.
4. Tag `vX.Y.Z`; GitHub Actions builds and pushes images tagged with the version;
   changelog entry generated from conventional commits.
