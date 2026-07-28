#!/usr/bin/env bash
#
# start.sh — bring up the whole system (frontend + backend + worker + Postgres + Redis)
# with one command, then open the app.
#
#   ./start.sh              # build if needed, start everything, wait until healthy
#   ./start.sh --fake       # keyless demo mode (scripted models, no API key needed)
#   ./start.sh --rebuild    # force a rebuild of the images
#   ./start.sh --logs       # follow logs after everything is up
#   ./start.sh --stop       # stop the stack
#   ./start.sh --reset      # stop AND delete the database volume (destroys all data)
#
# Everything runs in Docker, so this does not collide with anything you have
# installed natively — the only host port used is the frontend's (3000 by default).

set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

COMPOSE_FILE="docker-compose.full.yml"
FRONTEND_PORT="${FRONTEND_PORT:-3000}"
URL="http://localhost:${FRONTEND_PORT}"

# ── Pretty output ─────────────────────────────────────────────────────────────
if [ -t 1 ]; then
  BOLD=$'\033[1m'; DIM=$'\033[2m'; RED=$'\033[31m'; GREEN=$'\033[32m'
  YELLOW=$'\033[33m'; CYAN=$'\033[36m'; RESET=$'\033[0m'
else
  BOLD=""; DIM=""; RED=""; GREEN=""; YELLOW=""; CYAN=""; RESET=""
fi
say()  { printf '%s\n' "$*"; }
ok()   { printf '%s✓%s %s\n' "$GREEN" "$RESET" "$*"; }
warn() { printf '%s!%s %s\n' "$YELLOW" "$RESET" "$*"; }
die()  { printf '%s✗%s %s\n' "$RED" "$RESET" "$*" >&2; exit 1; }
step() { printf '\n%s%s%s\n' "$BOLD" "$*" "$RESET"; }

# ── Args ──────────────────────────────────────────────────────────────────────
MODE="up"; REBUILD=""; FOLLOW_LOGS=""; FAKE=""
for arg in "$@"; do
  case "$arg" in
    --fake)     FAKE=1 ;;
    --rebuild)  REBUILD=1 ;;
    --logs)     FOLLOW_LOGS=1 ;;
    --stop)     MODE="stop" ;;
    --reset)    MODE="reset" ;;
    -h|--help)  sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *)          die "Unknown option: $arg  (try --help)" ;;
  esac
done

# ── Preflight ─────────────────────────────────────────────────────────────────
command -v docker >/dev/null 2>&1 || die "Docker isn't installed. Get it at https://docker.com"
docker compose version >/dev/null 2>&1 || die "Docker Compose v2 is required (try: docker compose version)"
docker info >/dev/null 2>&1 || die "Docker is installed but not running. Start Docker Desktop and retry."

# ── Stop / reset ──────────────────────────────────────────────────────────────
if [ "$MODE" = "stop" ]; then
  step "Stopping the stack…"
  docker compose -f "$COMPOSE_FILE" down
  ok "Stopped. Your data is preserved — ./start.sh brings it back."
  exit 0
fi

if [ "$MODE" = "reset" ]; then
  step "Reset — this DELETES the database (all users, sessions, and reports)."
  printf 'Type %sreset%s to confirm: ' "$BOLD" "$RESET"
  read -r confirm
  [ "$confirm" = "reset" ] || { say "Aborted — nothing was deleted."; exit 0; }
  docker compose -f "$COMPOSE_FILE" down -v
  ok "Stack stopped and data volumes removed."
  exit 0
fi

# ── .env ──────────────────────────────────────────────────────────────────────
step "Checking configuration…"
if [ ! -f .env ]; then
  cp .env.example .env
  warn "Created .env from .env.example."
  if command -v openssl >/dev/null 2>&1; then
    secret="$(openssl rand -hex 32)"
    # Fill the empty JWT_SECRET_KEY line in place (portable across GNU/BSD sed).
    tmp="$(mktemp)"
    sed "s|^JWT_SECRET_KEY=$|JWT_SECRET_KEY=${secret}|" .env > "$tmp" && mv "$tmp" .env
    ok "Generated a JWT_SECRET_KEY for you."
  fi
  warn "Add an API key to .env (GOOGLE_API_KEY or ANTHROPIC_API_KEY),"
  warn "or run './start.sh --fake' for a keyless demo."
fi

# JWT secret must exist and be long enough or the API refuses to boot (by design).
jwt="$(grep -E '^JWT_SECRET_KEY=' .env | head -1 | cut -d= -f2- || true)"
if [ "${#jwt}" -lt 32 ]; then
  die "JWT_SECRET_KEY in .env must be >= 32 characters.
     Generate one with:  openssl rand -hex 32"
fi
ok "JWT secret present."

# Decide the LLM mode. --fake always wins; otherwise require a key for real mode.
if [ -n "$FAKE" ]; then
  export LLM_MODE=fake
  ok "Mode: fake (deterministic fixtures, no API key needed)."
else
  has_key=""
  for var in GOOGLE_API_KEY ANTHROPIC_API_KEY OPENAI_API_KEY; do
    val="$(grep -E "^${var}=" .env | head -1 | cut -d= -f2- || true)"
    [ -n "$val" ] && has_key=1
  done
  if [ -z "$has_key" ]; then
    warn "No provider API key found in .env — falling back to fake mode."
    warn "Add GOOGLE_API_KEY or ANTHROPIC_API_KEY to .env for real research."
    export LLM_MODE=fake
  else
    ok "Mode: real (using the API key from .env)."
  fi
fi

# ── Port check ────────────────────────────────────────────────────────────────
if lsof -nP -iTCP:"$FRONTEND_PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  # Ours already? Then this is just a restart.
  if docker compose -f "$COMPOSE_FILE" ps --status running 2>/dev/null | grep -q frontend; then
    say "${DIM}Port ${FRONTEND_PORT} is in use by this project — restarting it.${RESET}"
  else
    die "Port ${FRONTEND_PORT} is already in use by something else.
     Free it, or run with a different port:  FRONTEND_PORT=3001 ./start.sh"
  fi
fi

# ── Up ────────────────────────────────────────────────────────────────────────
step "Starting the stack (postgres · redis · api · worker · frontend)…"
say "${DIM}First run builds the images and can take a few minutes.${RESET}"
if [ -n "$REBUILD" ]; then
  docker compose -f "$COMPOSE_FILE" up -d --build --force-recreate
else
  docker compose -f "$COMPOSE_FILE" up -d --build
fi

# ── Wait for health ───────────────────────────────────────────────────────────
step "Waiting for services to become healthy…"
deadline=$(( $(date +%s) + 240 ))
while :; do
  unhealthy=0
  for svc in postgres redis api worker frontend; do
    cid="$(docker compose -f "$COMPOSE_FILE" ps -q "$svc" 2>/dev/null || true)"
    if [ -z "$cid" ]; then unhealthy=1; continue; fi
    state="$(docker inspect --format '{{.State.Health.Status}}' "$cid" 2>/dev/null || echo "none")"
    # Services without a healthcheck report "none" — treat running as good enough.
    if [ "$state" = "none" ]; then
      running="$(docker inspect --format '{{.State.Running}}' "$cid" 2>/dev/null || echo false)"
      [ "$running" = "true" ] || unhealthy=1
    elif [ "$state" != "healthy" ]; then
      unhealthy=1
    fi
  done
  [ "$unhealthy" -eq 0 ] && break
  if [ "$(date +%s)" -ge "$deadline" ]; then
    warn "Services did not all report healthy in time. Current state:"
    docker compose -f "$COMPOSE_FILE" ps
    say ""
    say "Check the logs with:  docker compose -f $COMPOSE_FILE logs -f api worker"
    exit 1
  fi
  printf '.'
  sleep 3
done
printf '\n'
ok "All services healthy (migrations applied automatically)."

# ── Summary ───────────────────────────────────────────────────────────────────
step "Ready"
docker compose -f "$COMPOSE_FILE" ps --format "table {{.Service}}\t{{.Status}}"
say ""
say "  ${BOLD}${CYAN}${URL}${RESET}"
say "  ${DIM}Register an account, ask a research question, approve the draft.${RESET}"
say ""
say "  ${DIM}Logs:${RESET}  docker compose -f $COMPOSE_FILE logs -f"
say "  ${DIM}Stop:${RESET}  ./start.sh --stop"
say ""

# Open the browser on macOS/Linux (never fatal if it fails).
if command -v open >/dev/null 2>&1; then open "$URL" >/dev/null 2>&1 || true
elif command -v xdg-open >/dev/null 2>&1; then xdg-open "$URL" >/dev/null 2>&1 || true
fi

if [ -n "$FOLLOW_LOGS" ]; then
  step "Following logs (Ctrl-C to stop watching; the stack keeps running)…"
  docker compose -f "$COMPOSE_FILE" logs -f
fi
