#!/bin/sh
# API entrypoint (docs/09 §4): run migrations, then serve. The worker and frontend
# wait on this container's /health readiness, so the schema is applied exactly once
# per deploy before any traffic. Schema is owned entirely by Alembic — no create_all.
set -eu

echo "[entrypoint] applying database migrations (alembic upgrade head)…"
alembic upgrade head

echo "[entrypoint] starting API on :8000…"
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips='*'
