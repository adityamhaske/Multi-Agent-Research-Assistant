#!/usr/bin/env bash
#
# One-shot setup for the public demo on an Oracle Cloud Always Free VM.
#
#   git clone https://github.com/adityamhaske/Multi-Agent-Research-Assistant.git
#   cd Multi-Agent-Research-Assistant
#   ./deploy/oracle-bootstrap.sh
#
# Installs Docker, opens the host firewall, writes deploy/.env with freshly generated
# secrets, and brings the stack up behind HTTPS. Safe to re-run: every step checks
# before acting, and an existing .env is never overwritten.
#
# What this script CANNOT do for you — it needs the Oracle web console:
#   • create the VM
#   • add ingress rules for TCP 80 and 443 to the subnet's Security List / NSG
# Both are covered step by step in deploy/README.md. The firewall has two independent
# layers on OCI (cloud Security List *and* the VM's own iptables); this script handles
# the second, and without the first the site stays unreachable with no error anywhere.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$REPO_ROOT/deploy/.env"
COMPOSE_FILE="$REPO_ROOT/deploy/docker-compose.demo.yml"

log()  { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m  ! %s\033[0m\n' "$*"; }
die()  { printf '\n\033[1;31mERROR: %s\033[0m\n' "$*" >&2; exit 1; }

[ "$(id -u)" -ne 0 ] || die "Run as your normal user (the script calls sudo itself).
Running the whole thing as root leaves the stack owned by root and breaks the
rootless docker-group step below."

# ── 1. Docker ────────────────────────────────────────────────────────────────────
if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
  log "Docker already present — skipping install"
else
  log "Installing Docker Engine + Compose plugin"
  curl -fsSL https://get.docker.com | sudo sh
  sudo systemctl enable --now docker
fi

if ! id -nG "$USER" | tr ' ' '\n' | grep -qx docker; then
  log "Adding $USER to the docker group"
  sudo usermod -aG docker "$USER"
  NEED_RELOGIN=1
fi

# ── 2. Host firewall ─────────────────────────────────────────────────────────────
# OCI images ship a default-deny INPUT chain. The cloud Security List is a *separate*
# layer — opening one without the other still leaves the port closed.
log "Opening TCP 80/443 on the host firewall"
if command -v firewall-cmd >/dev/null 2>&1 && sudo firewall-cmd --state >/dev/null 2>&1; then
  # Oracle Linux / RHEL-family images.
  for port in 80 443; do
    sudo firewall-cmd --permanent --add-port="${port}/tcp" >/dev/null
  done
  sudo firewall-cmd --permanent --add-port=443/udp >/dev/null   # HTTP/3
  sudo firewall-cmd --reload >/dev/null
  echo "  firewalld: 80/tcp, 443/tcp, 443/udp opened"
elif command -v iptables >/dev/null 2>&1; then
  # Ubuntu images: rules must be inserted *above* the catch-all REJECT, not appended
  # after it, or they are dead weight. Find where that REJECT sits rather than
  # hardcoding a line number, which differs between image versions.
  reject_line="$(sudo iptables -L INPUT --line-numbers -n | awk '/REJECT/ {print $1; exit}')"
  for spec in 80/tcp 443/tcp 443/udp; do
    port="${spec%/*}" proto="${spec#*/}"
    if sudo iptables -C INPUT -p "$proto" --dport "$port" -j ACCEPT 2>/dev/null; then
      echo "  iptables: ${port}/${proto} already allowed"
      continue
    fi
    if [ -n "$reject_line" ]; then
      sudo iptables -I INPUT "$reject_line" -p "$proto" --dport "$port" -j ACCEPT
    else
      sudo iptables -A INPUT -p "$proto" --dport "$port" -j ACCEPT
    fi
    echo "  iptables: ${port}/${proto} allowed"
  done
  if command -v netfilter-persistent >/dev/null 2>&1; then
    sudo netfilter-persistent save >/dev/null
  else
    warn "iptables-persistent not installed — rules will be lost on reboot."
    warn "Install it with: sudo apt-get install -y iptables-persistent"
  fi
else
  warn "No firewalld or iptables found; assuming the host firewall is already open."
fi

# ── 3. Swap ──────────────────────────────────────────────────────────────────────
# 12 GB is comfortable for this stack, but the image ships with no swap at all, so a
# single memory spike during an image pull becomes an OOM kill instead of a slowdown.
if [ "$(swapon --show --noheadings | wc -l)" -eq 0 ]; then
  log "Creating a 2G swapfile"
  sudo fallocate -l 2G /swapfile
  sudo chmod 600 /swapfile
  sudo mkswap /swapfile >/dev/null
  sudo swapon /swapfile
  grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab >/dev/null
else
  log "Swap already configured — skipping"
fi

# ── 4. Configuration ─────────────────────────────────────────────────────────────
if [ -f "$ENV_FILE" ]; then
  log "deploy/.env exists — keeping it (delete it to regenerate secrets)"
else
  log "Generating deploy/.env"
  command -v openssl >/dev/null 2>&1 || die "openssl not found — needed to generate secrets."

  # sslip.io turns a bare IP into a hostname Let's Encrypt will issue for, so the demo
  # gets a real certificate without buying a domain. Override by exporting DOMAIN.
  if [ -z "${DOMAIN:-}" ]; then
    public_ip="$(curl -fsS --max-time 10 https://api.ipify.org || true)"
    [ -n "$public_ip" ] || die "Could not detect the public IP. Re-run with: DOMAIN=your.host $0"
    DOMAIN="${public_ip//./-}.sslip.io"
    echo "  Detected public IP $public_ip"
  fi
  echo "  DOMAIN=$DOMAIN"

  umask 077
  cat > "$ENV_FILE" <<EOF
# Generated by deploy/oracle-bootstrap.sh — contains secrets, never commit.

DOMAIN=$DOMAIN
# 'edge' is published by running the Release workflow manually and is what exists before
# a version is tagged. Switch to 'latest' once you tag a v*.*.* release — 'latest' is
# deliberately not moved by manual builds, so it stays absent until then and pulling it
# would fail with "manifest unknown".
IMAGE_TAG=edge
GITHUB_REPOSITORY=adityamhaske/multi-agent-research-assistant

ENVIRONMENT=production
# fake = deterministic scripted agents and fixture retrievers. No provider key is read,
# so no visitor can spend your money. Switch to real only behind an invite.
LLM_MODE=fake

POSTGRES_USER=research_user
POSTGRES_PASSWORD=$(openssl rand -hex 24)
POSTGRES_DB=research_db

JWT_SECRET_KEY=$(openssl rand -hex 32)
ENCRYPTION_KEY=$(openssl rand -hex 32)
JWT_ALGORITHM=HS256
JWT_ACCESS_TOKEN_EXPIRE_MINUTES=15
JWT_REFRESH_TOKEN_EXPIRE_DAYS=14
# No SMTP on this box, so verification mail could never arrive and every signup
# would be locked out of the demo it just created.
REQUIRE_EMAIL_VERIFICATION=false

# Irrelevant while LLM_MODE=fake (nothing is spent), but set so that flipping to real
# mode cannot hand an anonymous signup an unlimited budget.
DEFAULT_MONTHLY_TOKEN_LIMIT=100000
MAX_CRITIC_LOOPS=2
MAX_COST_PER_SESSION_USD=0.50
MAX_WALLCLOCK_SECONDS=600
MAX_PARALLEL_TASKS=4
EOF
  echo "  Wrote $ENV_FILE (mode 600)"
fi

# ── 5. Launch ────────────────────────────────────────────────────────────────────
log "Pulling images and starting the stack"
DOCKER=(docker)
if ! docker info >/dev/null 2>&1; then
  # Group membership from step 1 isn't active in this shell yet.
  DOCKER=(sudo docker)
fi

"${DOCKER[@]}" compose -f "$COMPOSE_FILE" pull
"${DOCKER[@]}" compose -f "$COMPOSE_FILE" up -d

DOMAIN_VALUE="$(grep -E '^DOMAIN=' "$ENV_FILE" | cut -d= -f2-)"

log "Done"
cat <<EOF

  Demo URL:  https://${DOMAIN_VALUE}

  The first request may take ~30s while Caddy obtains its certificate.
  If it hangs, the Security List ingress rules are the usual cause — see
  deploy/README.md step 3. Confirm from your laptop, not the VM:

    curl -sSf -o /dev/null -w '%{http_code}\\n' https://${DOMAIN_VALUE}/login

  Logs:     docker compose -f deploy/docker-compose.demo.yml logs -f
  Stop:     docker compose -f deploy/docker-compose.demo.yml down
  Update:   git pull && docker compose -f deploy/docker-compose.demo.yml up -d --pull always
EOF

if [ -n "${NEED_RELOGIN:-}" ]; then
  warn "Log out and back in (or run: newgrp docker) to use docker without sudo."
fi
