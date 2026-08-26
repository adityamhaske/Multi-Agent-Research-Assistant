# Deploy with Docker

Everything runs in containers. The only host port used is the frontend's.

## Artifacts

| Artifact | Path | Contents |
|---|---|---|
| API image | `backend/Dockerfile`, target `api` | Python slim, non-root, migrate-on-start, uvicorn |
| Worker image | `backend/Dockerfile`, target `worker` | Same base, Celery entrypoint |
| Frontend image | `frontend/Dockerfile` | Next.js standalone output |
| Dev infrastructure | `docker-compose.yml` | Postgres and Redis only; the app runs natively |
| Full stack | `docker-compose.full.yml` | api, worker, frontend, postgres, redis |

Both images are multi-stage, run as a non-root user, pin their base image, declare a
`HEALTHCHECK`, and bake in no secrets.

**The frontend image builds from the repository root, not from `frontend/`.** The docs site
renders the `docs/` tree at build time, and `docs/` sits outside a `./frontend` context.
Compose and the release workflow both set `context: .` for this reason.

## The full stack

```bash
./start.sh
```

Or directly:

```bash
cp .env.example .env
# Set JWT_SECRET_KEY and a provider key in .env
docker compose -f docker-compose.full.yml up --build
```

Five services come up:

| Service | Image | Published |
|---|---|---|
| `postgres` | `pgvector/pgvector:pg16` | No |
| `redis` | `redis:7-alpine` | No |
| `api` | built from `backend/`, target `api` | No |
| `worker` | built from `backend/`, target `worker` | No |
| `frontend` | built from the repo root | **Yes** — `${FRONTEND_PORT:-3031}` |

**Postgres must be a pgvector image.** Migration 0006 enables the extension and 0007 creates
a vector column, so a stock image fails `alembic upgrade head` outright.

`extra_hosts: host.docker.internal:host-gateway` is declared on `api` and `worker`, so
`OLLAMA_BASE_URL=http://host.docker.internal:11434/v1` reaches an Ollama on the host —
portably, including on Linux.

Volumes are named distinctly from the dev compose file's, so the full stack can never
collide with a dev database of a different Postgres major version.

**A fourth named volume, `mara_full_corpus_data`, holds per-project corpora** (docs/12
M10) and is mounted at `/app/data` on **both** `api` and `worker`. It must be on both:
they are separate containers with separate writable layers, so a document uploaded
through `api` and not visible to `worker` is exactly the split-brain a shared volume
exists to prevent. Without this volume at all, a corpus lives only in a container's
writable layer and is destroyed by any `up --build` or `down` recreate — `./start.sh
--stop` / a plain `docker compose down` preserves it, and only `./start.sh --reset` /
`down -v` removes it, same as the database.

To back up a project's corpus outside the volume:

```bash
docker run --rm -v mara_full_corpus_data:/data -v "$PWD":/backup alpine \
  tar czf /backup/corpus-backup.tar.gz -C /data .
```

## Startup ordering

Migrations run exactly once per deploy, and dependants wait for them:

1. `postgres` and `redis` come up and pass their own healthchecks.
2. `api` starts, runs `alembic upgrade head` in its entrypoint, then serves.
3. `api`'s healthcheck polls `/health/ready`, which checks the **database and Redis are
   actually reachable** rather than merely that the process is alive.
4. `worker` and `frontend` declare `depends_on: api: {condition: service_healthy}`, so
   neither starts against an unmigrated schema.

This is why readiness is a separate endpoint from liveness. Gating on "the process is up"
would start the worker against a database that has not been migrated yet.

## Development infrastructure only

For working on the code, run the datastores in Docker and the app natively:

```bash
make infra-up          # postgres + redis
make infra-down
make infra-clean       # also removes volumes
```

Details in the [Development guide](../developers/32-development.md).

## Configuration

All configuration is environment variables, read from `./.env`. Secrets are never baked into
images.

Compose overrides `DATABASE_URL` and `REDIS_URL` with the internal service hostnames, so the
values in `.env` only matter for a native run.

See [Configuration](../getting-started/21-configuration.md) and the
[configuration reference](../reference/36-configuration.md).

## Rebuilding after a change

The frontend container is a **static build**, not a bind-mounted dev server. Source edits
need a rebuild; a browser reload shows you stale UI:

```bash
docker compose -f docker-compose.full.yml build frontend
docker compose -f docker-compose.full.yml up -d frontend
```

## Migrations

- The API entrypoint runs `alembic upgrade head` before starting uvicorn.
- Rolling back one revision is `alembic downgrade -1`, and the forward/backward round-trip
  is exercised in CI.
- **No `create_all` in application code** — Alembic owns the schema. The LangGraph
  checkpoint tables are created by the library's own setup, invoked from a migration, so
  there is one history.

Running a migration by hand:

```bash
docker compose -f docker-compose.full.yml exec api alembic upgrade head
docker compose -f docker-compose.full.yml exec api alembic current
```

## Health checks

| Endpoint | Meaning |
|---|---|
| `GET /health` | Liveness — the process is up. Used by the container healthcheck |
| `GET /health/ready` | Readiness — database and Redis both answered. **503** until they do |

The worker's healthcheck pings the broker and the worker itself, and fails if either is
unreachable.

## Images and releases

Tagging `vX.Y.Z` triggers the release workflow, which builds multi-architecture (`amd64` and
`arm64`) api, worker, and frontend images to GHCR and cuts a GitHub Release. The desktop
workflow builds and attaches the desktop bundles with a `SHA256SUMS` file.

Next: [Production deployment](30-production.md) · [Operations](31-operations.md)
