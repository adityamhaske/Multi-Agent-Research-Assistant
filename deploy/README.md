# Deploying the public demo — Oracle Cloud Always Free

The hosted demo runs the **real stack** (Postgres, Redis, API, Celery worker, Next.js,
Caddy) on a single Oracle Cloud Always Free VM, in `LLM_MODE=fake`.

**Cost: $0/month, indefinitely.** Not a trial, not credits. Always Free compute has no
expiry.

Fake mode matters for more than money: the demo holds no provider key at all, so there
is nothing for an anonymous visitor to drain. The agents are deterministic scripted
stand-ins over fixture retrievers — the UI, the streaming, the HITL approval gate and
the citation chips are all the production code paths.

---

## Why this shape

Every managed PaaS free tier collapsed in 2025–26: Fly.io's is a 2-hour trial, Railway
removed theirs, Koyeb closed Starter to new users after the Mistral acquisition, and
Render's free web services sleep after 15 minutes — a 30–50s cold start on the link you
put in your README. Render also bills background workers from $7/month, and this stack
needs one.

An Always Free VM sidesteps all of it: always-on, no per-service pricing, and it runs the
same `docker compose` topology as production rather than a special demo build.

The trade is that you own the box — patching, and the ARM caveat below.

---

## What you have to do yourself

Three things need your Oracle account and cannot be scripted:

1. **Sign up** — needs a card for identity verification. Always Free resources are not
   charged; to be safe, leave the account in its default "Always Free only" state and do
   not upgrade to Pay As You Go.
2. **Create the VM** (step 1).
3. **Add the ingress rules** (step 2).

Everything after that is `./deploy/oracle-bootstrap.sh`.

---

## Step 1 — Create the instance

**Pick your home region carefully: it cannot be changed later.** Ampere ARM capacity is
routinely exhausted in popular US regions, where you will see `Out of host capacity` for
hours or days. Frankfurt, Zurich, Singapore and Mumbai typically provision in minutes.

Console → **Compute → Instances → Create instance**

| Field | Value |
|---|---|
| Image | Canonical **Ubuntu 24.04** |
| Shape | **Ampere → VM.Standard.A1.Flex** |
| OCPUs / Memory | **2 OCPU / 12 GB** — the Always Free maximum since June 2026 (halved from 4/24) |
| Boot volume | 50 GB is plenty (200 GB total is free) |
| SSH keys | **Download the private key before you click Create.** It is not retrievable afterwards. |
| Networking | Assign a **public IPv4 address** |

> **`Out of host capacity`?** It is a transient regional shortage, not a problem with your
> account. Try another Availability Domain in the same region, or retry periodically —
> capacity is released continuously.

This is why the release workflow builds `linux/arm64`: Ampere is ARM, and an amd64-only
image will not start. `deploy/docker-compose.demo.yml` pulls prebuilt multi-arch images
rather than building on the VM, because compiling the Next.js and Python images on two
Ampere cores takes tens of minutes and can OOM.

---

## Step 2 — Open the cloud firewall

**This is the step everyone misses.** OCI has *two* independent firewalls. The bootstrap
script handles the VM's own `iptables`; only you can open the cloud one, and when it is
shut the site simply hangs — no error, no log line, nothing to debug.

Console → **Networking → Virtual Cloud Networks →** your VCN **→** your subnet **→**
its **Security List → Add Ingress Rules**:

| Stateless | Source CIDR | IP Protocol | Destination Port |
|---|---|---|---|
| No | `0.0.0.0/0` | TCP | `80` |
| No | `0.0.0.0/0` | TCP | `443` |
| No | `0.0.0.0/0` | UDP | `443` (optional — HTTP/3) |

Port 80 is not optional: Let's Encrypt validates over it before any certificate exists.

---

## Step 3 — Bootstrap

SSH in (`ubuntu` is the default user on the Canonical image):

```bash
ssh -i /path/to/your-key.pem ubuntu@YOUR_PUBLIC_IP
```

Then:

```bash
sudo apt-get update && sudo apt-get install -y git
git clone https://github.com/adityamhaske/Multi-Agent-Research-Assistant.git
cd Multi-Agent-Research-Assistant
./deploy/oracle-bootstrap.sh
```

The script is idempotent — re-run it freely. It installs Docker, opens `iptables`
(inserting the rules *above* the image's catch-all `REJECT`, not after it, where they
would be dead weight), adds a 2 GB swapfile, generates `deploy/.env` with fresh secrets,
and starts the stack.

### The domain, for free

With no domain, the script derives one from your public IP using **sslip.io** —
`203-0-113-7.sslip.io` resolves to `203.0.113.7`, and Let's Encrypt issues a genuine
certificate for it. Real HTTPS, no registrar, no cost.

Own a domain? Point an `A` record at the VM and run:

```bash
DOMAIN=research.yourdomain.com ./deploy/oracle-bootstrap.sh
```

### Images must exist first

The stack pulls from GHCR, and images are published only by the **Release** workflow. To
publish without cutting a public release, run it manually — Actions → **Release** → *Run
workflow* → tag `edge`. Then on the VM set `IMAGE_TAG=edge` in `deploy/.env`.

Once you tag a real `v1.0.0`, switch back to `IMAGE_TAG=latest`.

---

## Step 4 — Verify

From your **laptop**, not the VM — the whole point is to test the path through both
firewalls:

```bash
curl -sSf -o /dev/null -w '%{http_code}\n' https://YOUR_DOMAIN/login
```

`200` means done. Allow ~30s on the first request while Caddy obtains its certificate.

Then set the repo's homepage so the URL appears on the GitHub sidebar:

```bash
gh repo edit adityamhaske/Multi-Agent-Research-Assistant --homepage https://YOUR_DOMAIN
```

---

## Operating it

```bash
docker compose -f deploy/docker-compose.demo.yml logs -f          # tail everything
docker compose -f deploy/docker-compose.demo.yml ps               # health
docker compose -f deploy/docker-compose.demo.yml up -d --pull always   # update
./deploy/backup-postgres.sh                                       # dump the database
```

Unattended security upgrades are worth enabling, since you own patching now:

```bash
sudo apt-get install -y unattended-upgrades && sudo dpkg-reconfigure -plow unattended-upgrades
```

---

## Troubleshooting

| Symptom | Cause |
|---|---|
| Connection times out, no logs anywhere | Security List ingress missing (step 2). By far the most common. |
| Times out, Security List looks right | Host `iptables`. Re-run the bootstrap; check `sudo iptables -L INPUT -n --line-numbers` and confirm the ACCEPT rules sit *above* the `REJECT`. |
| Certificate never issues | Port **80** blocked, or DNS not yet pointing at the VM. Check `docker compose -f deploy/docker-compose.demo.yml logs caddy`. |
| `exec format error` | An amd64-only image on ARM. Confirm the multi-arch manifest: `docker buildx imagetools inspect ghcr.io/adityamhaske/multi-agent-research-assistant-api:latest` |
| `manifest unknown` on pull | No images published yet — see *Images must exist first*. |
| Rules vanish after reboot | `sudo apt-get install -y iptables-persistent` |
| Instance disappeared | Oracle reclaims Always Free compute that stays idle for ~7 days. A live demo generally stays above the threshold, but do not treat this box as durable storage — take backups. |

---

## Security posture

- Caddy is the only service binding a host port. Postgres, Redis and the API are
  reachable only on the internal Docker network — `frontend` has no `ports:` mapping, so
  nothing can bypass TLS.
- `ENVIRONMENT=production` disables `/docs` and `/redoc` and enforces `Secure` cookies.
- Registration is open but IP-rate-limited (`backend/app/services/rate_limit.py`).
- `REQUIRE_EMAIL_VERIFICATION=false`, deliberately: there is no SMTP on this box, so
  verification mail could never arrive and every signup would be locked out of the demo
  it had just created.
- `deploy/.env` is generated at mode `600` and is covered by `.gitignore`.

**Before switching this box to `LLM_MODE=real`:** open registration plus a live provider
key is an unmetered bill in someone else's hands. Put it behind an invite or a fixed
`DEFAULT_MONTHLY_TOKEN_LIMIT` first.
