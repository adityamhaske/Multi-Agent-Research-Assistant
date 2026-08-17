# Production deployment

A single host plus a TLS reverse proxy in front of the frontend. Kubernetes is deliberately
out of scope until a real scaling need exists.

## Shape

```
Internet → Caddy (TLS) → frontend:3031 → api:8000 → postgres · redis
                                              ↑
                                           worker
```

**The frontend is the only publicly reachable service.** It proxies `/api/*` over the
internal Docker network, which is what keeps auth cookies first-party and leaves the API,
the database, and Redis unexposed.

## Before you expose it

Work through the [hardening checklist](../architecture/06-security.md#12-production-hardening-checklist).
The items that most commonly get missed:

```bash
ENVIRONMENT=production                    # secure cookies, HSTS, /docs disabled
JWT_SECRET_KEY=<openssl rand -hex 32>
ENCRYPTION_KEY=<openssl rand -hex 32>     # set explicitly; do not let it derive
REQUIRE_EMAIL_VERIFICATION=true

DEFAULT_MONTHLY_TOKEN_LIMIT=50000         # applied to every NEW account
RESEARCH_RATE_LIMIT_PER_HOUR=10           # 0 = unlimited, and 0 is the default
CHAT_RATE_LIMIT_PER_HOUR=60
```

The three limits default to **unlimited**, which is right for a single-tenant self-host and
wrong for anything public. A public deployment should require bring-your-own-key from
everyone and leave the server key unset, so there is no shared key to drain.

> Setting `MAX_COST_PER_SESSION_USD` is not sufficient protection on `openrouter` or
> `custom` routes — the catalog cannot price them, so the cap never fires. **Cap real spend
> at the provider.**

## TLS

`deploy/Caddyfile` is a deployment-agnostic reverse proxy with automatic Let's Encrypt
certificates. Both placeholders come from the environment:

```bash
DOMAIN=research.example.com FRONTEND_UPSTREAM=localhost:3031 \
  caddy run --config ./deploy/Caddyfile
```

Or containerised alongside the stack, via `deploy/docker-compose.demo.yml`.

No domain? `sslip.io` resolves `203-0-113-7.sslip.io` to `203.0.113.7`, and Let's Encrypt
will issue a real certificate for it — no registrar, no cost.

**Server-sent events need no extra proxy configuration under Caddy**, which streams by
default. Under nginx you must disable proxy buffering and gzip for `text/event-stream`; the
API already sends `Cache-Control: no-transform` and `X-Accel-Buffering: no`, which nginx
honours, but a CDN or another layer in front may not.

## A worked $0/month deployment

`deploy/README.md` documents running the whole stack on an Oracle Cloud Always Free VM —
always-on, no expiry, HTTPS included, and no domain required. `deploy/oracle-bootstrap.sh`
does everything after the three steps that need your own Oracle account: signing up,
creating the instance, and adding the ingress rules.

That deployment runs in `LLM_MODE=fake` on purpose: a public demo holding no provider key
has nothing for an anonymous visitor to drain, while the UI, the streaming, the approval
gate, and the citation chips are all the production code paths.

## Backups

Everything durable — reports, audit rows, memory chunks, and the graph checkpoints — lives
in Postgres, so one dump captures full state. Redis holds only queues, caches, rate-limit
counters and locks, and is not backed up; a Redis flush must never lose user data.

`deploy/backup-postgres.sh` does a nightly `pg_dump`, gzips it, and prunes by retention:

```bash
# 2am daily, keeping 14 days
0 2 * * * /opt/research-assistant/deploy/backup-postgres.sh >> /var/log/mara-backup.log 2>&1
```

Restore:

```bash
gunzip -c backup-YYYY-MM-DD.sql.gz | \
  docker compose -f docker-compose.full.yml exec -T postgres \
    psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"
```

**A backup you have never restored is a hypothesis.** Test it against a scratch database
before you need it.

The per-project corpus SQLite files live outside Postgres, under `CORPUS_DIR`. Back that
directory up too if users upload documents.

## Upgrading

1. Pull the new images or rebuild.
2. Bring the stack up. The API entrypoint runs `alembic upgrade head` before serving, and
   the worker and frontend gate on its readiness — so migrations apply exactly once, before
   anything else starts.
3. Check `/health/ready` returns `200`.

Rolling back one migration is `alembic downgrade -1`. Rolling back an application version
across a migration that dropped something is not automatic; take a dump first.

## Release process

1. CI green on `main`, including the golden end-to-end journeys.
2. An evaluation run recorded if prompts or models changed.
3. The security checklist reviewed for anything public-facing.
4. Tag `vX.Y.Z`. The release workflow builds multi-architecture images to GHCR and cuts a
   GitHub Release; the desktop workflow attaches the desktop bundles and a `SHA256SUMS`.
5. Update `frontend/lib/releases.ts` and the README download badge — both are hand-written
   and go stale silently, because nothing fails when they do.

## What is not built

Stated so nobody plans around it:

- **No Kubernetes manifests, no autoscaling, no sharding.** See the
  [scaling path](../architecture/02-system-architecture.md#scaling-path) for the order those
  needs would actually arrive in.
- **No Prometheus metrics endpoint.** [Planned](../project/10-roadmap.md); logs and the
  `agent_logs` trace are what exist today.
- **No multi-tenancy beyond per-user isolation.** No organisations, roles, or shared
  workspaces.
