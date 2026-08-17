# Launch Go / No-Go Checklist

> Outcome of the launch-readiness pass. Every ✅ below was verified against the real
> Dockerized stack (`docker-compose.full.yml`, `LLM_MODE=fake`) or the test suites on
> 2026-08-05, not asserted from the code. Items needing a human decision or a real
> provider key are called out explicitly.

## Verdict

**GO for the public web / open-source launch** (self-host + hosted fake-mode demo).
The end-to-end product works through the production topology, the previously-fatal
paths are fixed, and one launch-blocking regression found during this pass was fixed
and verified. Remaining items are launch-*day* toggles (email verification, real keys),
not blockers for the OSS/demo launch.

## What was verified end-to-end (full Docker stack, fake mode)

| Step | Result |
|---|---|
| Register + login via httpOnly cookie through the same-origin proxy | ✅ 201 / cookie set; no token in JS |
| Dashboard, depth selector, validation | ✅ |
| Start research → Planner→Executor(parallel)→Critic→Synthesizer | ✅ live SSE feed, per-task PASS, round summary |
| HITL gate: cited draft, citation chips `[n]`, sources panel, cost/rework | ✅ styled markdown (typography plugin), 2 sources |
| **Approve → finalize → COMPLETED** (the path the old build could never reach) | ✅ worker finalizes in <0.1s; page converges |
| Report view: metrics (duration/cost/tokens/sources) + export | ✅ |
| Export `.md` | ✅ 200, `text/markdown`, valid H1 |
| Export `.pdf` (WeasyPrint) | ✅ 200, `application/pdf`, valid `%PDF-` |
| Follow-up chat (grounded, buffered SSE stream) | ✅ streamed chunk + done, grounded reply |
| History list with status filters | ✅ |

## Bug found and fixed during this pass

**Session monitor could hang on a finished run** (commit `fb07ad9`). After Approve, a
session that finalized quickly stayed on the "Running/Needs review" monitor even though
the DB was COMPLETED. Two independent causes:

1. **SSE race (backend)** — the stream snapshotted the `agent_logs` backlog *before*
   subscribing to Redis, losing any event published in the gap (the fast
   resume→COMPLETED). Fixed: subscribe first, then snapshot, dedupe by durable id.
2. **Poll safety net (frontend)** — the poll stopped at `AWAITING_APPROVAL` and paused
   when the tab was backgrounded, so the documented convergence net never fired. Fixed:
   poll through approval, `refetchIntervalInBackground: true`, and `cache: "no-store"`.

Both verified live: an open, **backgrounded** tab now converges to COMPLETED.

## Health gates

- ✅ Backend: 173 passed / 1 skipped, ruff lint + format clean
- ✅ Frontend: 50 tests passed, eslint clean, `next build` green
- ✅ Migration renders and round-trips; schema built purely from Alembic (no `create_all`)
- ✅ Citation-fidelity eval baseline committed (`backend/evals/results/eval-2026-08-03.json`, badge 95.2%)

## Security release checklist (docs/engineering/06_Security.md §8)

Verified by code + tests in this pass:

- ✅ JWT secret ≥32 bytes with fail-fast startup check (placeholder refused)
- ✅ Refresh rotation + reuse-detection revocation (service + tests)
- ✅ Per-operation rate limits (research/chat/login/register never share a budget)
- ✅ SSRF guard (loopback/RFC-1918/link-local/metadata/rebinding) — test suite
- ✅ Markdown CI guard (no `rehype-raw` / `dangerouslySetInnerHTML`)
- ✅ Security headers on API (verified) and frontend (`next.config.ts` CSP)
- ✅ `/docs` disabled when `ENVIRONMENT=production`
- ✅ `.env.example` matches `app/config.py`; gitleaks in CI

**Launch-day toggles (human decision, not code):**

- ☐ Set `REQUIRE_EMAIL_VERIFICATION=true` for any public multi-user deployment
- ☐ Provision real provider key(s) only if hosting a real-mode (non-demo) instance;
  the public demo stays `LLM_MODE=fake` and holds no key (nothing to drain)
- ☐ Run `pip-audit` + `npm audit` immediately before tagging the release
- ☐ Confirm the deployed JWT secret is unique to that environment (not the dev value)

## Deployment path

- ✅ `docker-compose.full.yml` — full production topology; Postgres/Redis are
  internal-only (no host ports), frontend is the sole public service
- ✅ `deploy/` — Oracle Cloud Always Free demo ($0/month, fake mode): `postgres`,
  `redis`, `api`, `worker`, `frontend`, `caddy` (TLS), plus `oracle-bootstrap.sh`,
  `backup-postgres.sh`, `Caddyfile`
- **Ops note (found this pass):** `docker compose up` reads `FRONTEND_PORT` / `LLM_MODE`
  from shell env with defaults — restarting a single service without those vars
  remaps the port. Put them in `.env` (compose auto-loads it) so restarts are
  consistent. Low severity; documented here for the runbook.

## Recommended launch sequence

1. Final `pip-audit` / `npm audit`; tag `v1.0.0` (CI green on `main`).
2. Deploy the fake-mode demo (Oracle Always Free) behind Caddy TLS; smoke-test the
   golden path on the live URL.
3. Publish: README with the demo link + the citation-fidelity badge, then Show HN /
   relevant subreddits. Lead with the differentiators — auditable human-approval gate,
   verifiable per-claim citations, self-host + BYOK.
4. Then resume the forward roadmap (M9 desktop / M10 airgapped corpus — the plan's
   "LAUNCH HERE" milestone) from [12_Launch_Plan.md](12_Launch_Plan.md).
