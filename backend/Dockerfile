# syntax=docker/dockerfile:1
#
# Backend image (docs/09 §1). Two runtime targets share one base:
#   --target api     → migrations-on-start entrypoint, then uvicorn
#   --target worker  → celery worker
# Multi-stage, pinned base, non-root runtime user, HEALTHCHECK, no secrets baked in.

# ── Base: runtime libs shared by both targets ─────────────────────────────────────
FROM python:3.14-slim-bookworm AS base
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
# Pango/FT for WeasyPrint (PDF export) + curl for the API healthcheck.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpango-1.0-0 libpangoft2-1.0-0 curl \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app

# ── Builder: compile deps into an isolated venv ───────────────────────────────────
FROM base AS builder
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential libffi-dev \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN python -m venv /venv \
    && /venv/bin/pip install --upgrade pip \
    && /venv/bin/pip install -r requirements.txt

# ── Runtime: non-root, app code + venv only ───────────────────────────────────────
FROM base AS runtime
RUN useradd --create-home --uid 10001 appuser
COPY --from=builder /venv /venv
ENV PATH="/venv/bin:$PATH"
COPY --chown=appuser:appuser . /app
USER appuser

# ── API: migrate then serve ───────────────────────────────────────────────────────
FROM runtime AS api
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=40s --retries=5 \
    CMD curl -fsS http://localhost:8000/health || exit 1
ENTRYPOINT ["sh", "/app/docker/entrypoint-api.sh"]

# ── Worker: celery ────────────────────────────────────────────────────────────────
FROM runtime AS worker
# Pings the broker + this worker; fails the healthcheck if either is unreachable.
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=5 \
    CMD celery -A app.workers.celery_app.celery_app inspect ping || exit 1
CMD ["celery", "-A", "app.workers.celery_app.celery_app", "worker", \
     "--concurrency=4", "--loglevel=info"]
