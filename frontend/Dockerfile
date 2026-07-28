# syntax=docker/dockerfile:1
#
# Frontend image (docs/09 §1): Next.js standalone output. Multi-stage, pinned base,
# non-root runtime user, HEALTHCHECK. The frontend is the only public service — it
# proxies /api/* to the backend (same-origin cookies, no CORS).

# ── Dependencies ──────────────────────────────────────────────────────────────────
FROM node:26-bookworm-slim AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

# ── Build ─────────────────────────────────────────────────────────────────────────
FROM node:26-bookworm-slim AS builder
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1
# The /api rewrite destination is baked into the build, so the backend origin must be
# known here. Defaults to the compose service name; override with --build-arg.
ARG BACKEND_ORIGIN=http://api:8000
ENV BACKEND_ORIGIN=$BACKEND_ORIGIN
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build

# ── Runtime ───────────────────────────────────────────────────────────────────────
FROM node:26-bookworm-slim AS runtime
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
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
EXPOSE 3000
HEALTHCHECK --interval=15s --timeout=5s --start-period=25s --retries=5 \
    CMD curl -fsS http://localhost:3000/login || exit 1
CMD ["node", "server.js"]
