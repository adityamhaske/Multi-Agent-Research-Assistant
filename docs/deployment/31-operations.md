# Operations

Running it day to day: what to look at, what the common symptoms mean, and what is
intentionally absent.

## Observability

**Logs.** Structured JSON via `structlog` to stdout, collected by Compose or journald.
Every line in a run carries `session_id` as a correlation id, bound once at the API and
carried through the Celery task and the engine. There is no `print` in application code.

**The trace.** The `agent_logs` table *is* the run trace. It is durable, ordered, and
replayable after the fact — the same rows the live feed replays are the ones you read when
debugging a run that finished yesterday.

**Health.**

| Endpoint | Meaning |
|---|---|
| `GET /health` | Liveness. The process is up |
| `GET /health/ready` | Readiness. Database and Redis both answered; **503** until they do |

**Tracing.** LangSmith is available via `LANGCHAIN_TRACING_V2`, off by default.

**Not built:** a Prometheus `/metrics` endpoint. [Planned](../project/10-roadmap.md), and
marked as such rather than half-implemented.

## Runbook

| Symptom | First checks | Likely cause and action |
|---|---|---|
| Session stuck `PENDING` | Worker logs; `celery inspect ping`; is Redis up? | The worker is down or the broker is unreachable. Restart the worker; the task is picked up |
| Session stuck `RUNNING` | Tail `agent_logs` for that session; lock TTL | The worker crashed mid-run. The lock expires and the session is resumable from its checkpoint. If a budget or time limit was crossed it self-fails with the reason |
| Live feed empty, research completes | Is the SSE endpoint reachable? Is a proxy buffering? | An intermediary is compressing the stream. The API sets `no-transform` and `X-Accel-Buffering: no`; make sure a CDN or extra proxy honours them |
| All searches failing | Retriever chain logs — which retrievers errored | Tavily/Brave keys missing or exhausted and DuckDuckGo rate-limiting. Add a key; check the cache hit rate |
| Provider 429s or errors | Provider status; per-role routing | Switch a role to a different provider. Budgets prevent runaway retries; nothing auto-retries an expensive task |
| Cost spike | `sessions.total_cost_usd` by day; diff the evaluation results | A model or prompt change without an evaluation run. Revert; check the price catalog matches the provider's published prices |
| Reported cost is `$0.00` but the bill is not | Which provider is routed | `openrouter` and `custom` are unpriced by the catalog, so the cap cannot fire and cost reads zero. Cap at the provider |
| Project chat returns 503 | `GET /projects/{id}/memory/status` | No embeddings provider is reachable. It fails closed rather than answering ungrounded |
| Memory looks incomplete | Same endpoint: `pending_reports`, `stale_models` | An ingestion failed, or chunks were written by an embedding model no longer configured |

## Useful commands

```bash
# Service state and logs
docker compose -f docker-compose.full.yml ps
docker compose -f docker-compose.full.yml logs -f worker

# Is the worker actually consuming?
docker compose -f docker-compose.full.yml exec worker \
  celery -A app.workers.celery_app.celery_app inspect ping
docker compose -f docker-compose.full.yml exec worker \
  celery -A app.workers.celery_app.celery_app inspect active

# Readiness
curl -fsS http://localhost:3031/api/v1/../../health/ready || \
  docker compose -f docker-compose.full.yml exec api curl -fsS http://localhost:8000/health/ready

# Schema state
docker compose -f docker-compose.full.yml exec api alembic current
```

A worker that answers a ping may still be importing LangGraph and the provider clients. That
import cost lands entirely on the first task — measurably tens of seconds — and is why CI
waits for an explicit preload signal rather than for a ping.

## Cost control

Token usage is read from each model response and accumulated on the session, so
`sessions.total_cost_usd` and the token columns are a real record rather than an estimate of
an estimate — with the caveat that the *price* is a catalog lookup, and two providers have
none.

Practical order of controls:

1. **Cap at the provider.** This is the only control that works on every route.
2. **`DEFAULT_MONTHLY_TOKEN_LIMIT`** — counts tokens actually sent, so it works everywhere.
3. **`MAX_INPUT_TOKENS`** per session — likewise.
4. **`MAX_COST_PER_SESSION_USD`** — only binds where the catalog has prices.

Depth is the user-facing cost dial; `MAX_PARALLEL_TASKS` trades wall-clock against how much
can already be in flight when a ceiling is crossed.

## Data and retention

- Deleting a user cascades to their sessions, logs, chat messages, audit rows, and memory
  chunks, at the database level.
- Deleting a session additionally drops its LangGraph checkpoints explicitly — cascades
  cannot reach them, and they hold fetched page content.
- Archiving is reversible and loses nothing.
- Corpus documents live in per-project SQLite files under `CORPUS_DIR`, outside Postgres.

## Housekeeping

Runtime artifacts must not be committed: `data/corpus/*.sqlite`, `__pycache__`, `.venv`,
`.next`, and build output are ignored. Note that an ignore rule does not untrack a file that
is already tracked.

`CORPUS_DIR` defaults to a path resolved against the backend package root rather than the
process working directory, so running from the repository root and from `backend/` cannot
produce two different corpus roots.

**Committed evaluation results are write-once.** Never modify a file under
`backend/evals/results/`; add a new one named `eval-<date>-<routing>-run<N>.json`, because a
date alone is not a run identity. CI enforces this — a frontend commit once silently
overwrote a real measurement, and nothing failed.
