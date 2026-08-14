# syntax=docker/dockerfile:1
#
# Frontend image (docs/09 §1): Next.js standalone output. Multi-stage, pinned base,
# non-root runtime user, HEALTHCHECK. The frontend is the only public service — it
# proxies /api/* to the backend (same-origin cookies, no CORS).

# ── Dependencies ──────────────────────────────────────────────────────────────────
# NOTE: this image builds from the REPOSITORY ROOT, not from `frontend/`. The docs site
# renders the `docs/` tree at build time, and `docs/` sits above `frontend/` — outside a
# `./frontend` context entirely. Build it with:
#   docker build -f frontend/Dockerfile .
# Compose and the release workflow both set `context: .` for this reason.

FROM node:22-bookworm-slim AS deps
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

# ── Build ─────────────────────────────────────────────────────────────────────────
FROM node:22-bookworm-slim AS builder
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1
# The /api rewrite destination is baked into the build, so the backend origin must be
# known here. Defaults to the compose service name; override with --build-arg.
ARG BACKEND_ORIGIN=http://api:8000
ENV BACKEND_ORIGIN=$BACKEND_ORIGIN
COPY --from=deps /app/node_modules ./node_modules
COPY frontend/ ./
# The documentation set, rendered into static pages at build time by `lib/docs.ts`.
# Copied beside the app rather than above it, because a Dockerfile cannot COPY outside
# WORKDIR — `lib/docs.ts` looks for `project-docs` for exactly this case.
COPY docs/ ./project-docs/
RUN npm run build

# ── Runtime ───────────────────────────────────────────────────────────────────────
FROM node:22-bookworm-slim AS runtime
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3031 \
    HOSTNAME=0.0.0.0
# Also set at runtime in case the config re-reads it on server start.
ARG BACKEND_ORIGIN=http://api:8000
ENV BACKEND_ORIGIN=$BACKEND_ORIGIN
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/* \
    && addgroup --system --gid 1001 nodejs \
    && adduser --system --uid 1001 nextjs
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static
COPY --from=builder --chown=nextjs:nodejs /app/public ./public
USER nextjs
EXPOSE 3031
HEALTHCHECK --interval=15s --timeout=5s --start-period=25s --retries=5 \
    CMD curl -fsS http://localhost:3031/login || exit 1
CMD ["node", "server.js"]
