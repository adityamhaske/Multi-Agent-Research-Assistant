# 10. Roadmap & Milestones

> Vertical slices: every milestone ends with a working, tested, demoable increment.
> A milestone is **done** only when its Definition of Done passes verbatim — including
> its tests. No milestone starts until the previous one's DoD is green in CI.
>
> Status legend: ☐ not started · ◐ in progress · ✅ done

## M0 — Truth reset & foundations  *(≈ 1 day)*

Scope: make the repo honest and buildable before adding anything.

- Replace stale docs with this doc set (done — you are reading it)
- Rewrite `README.md` to describe reality (correct stack, correct paths, no
  unbuilt claims); commit `.env.example` matching `app/config.py`
- Fix `Makefile` targets (`test`, `lint` point at real paths)
- Remove unused dependencies (passlib, zustand, unused langchain pins); upgrade
  backend pins to current (LangGraph ≥ 1.0, current langchain-google-genai, `ddgs`)
- Rotate/remove the stray OpenAI key from `.env`; replace placeholder JWT secret;
  add startup secret validation
- Scaffold `backend/tests/` with pytest config and one smoke test; GitHub Actions
  running lint + tests

**DoD:** `make lint` and `make test` exit 0 locally and in CI · README quick-start
works on a clean clone · gitleaks clean.

## M1 — The pipeline actually works  *(≈ 1–2 weeks)*  ← the critical milestone

**Status: ✅ code complete.** Compiled `StateGraph` (planner → executor ToolNode loop →
critic → synthesizer → `interrupt()` gate → finalizer/rework), structured Pydantic outputs
(fail-closed critic), budget guards, retriever chain, SSRF guard, untrusted-content framing,
provider-pluggable LLM factory with `LLM_MODE=fake`, event indirection, real token/cost
accounting. Celery worker rewired (`pipeline_runner.py`): single DB-session scope,
token-based lock, `AsyncPostgresSaver` checkpointing, resume-from-checkpoint on approve/rework.
Proven by the three golden journeys at graph level (`tests/test_pipeline.py`) + regressions
(`tests/test_ssrf_guard.py`, `tests/test_critic_failclosed.py`). The live API-level golden
E2E (real Postgres/Redis) runs in CI.

Scope: rebuild the agent layer on real LangGraph; fix the worker persistence scope.

- Compiled `StateGraph` per [04_Agent_Design.md](04_Agent_Design.md): planner →
  executor (ToolNode loop) → critic → synthesizer → `interrupt()` gate → finalizer /
  rework path; `AsyncPostgresSaver` checkpointing; budgets at conditional edges
- Structured outputs (Pydantic) for planner/executor/critic; fail-closed everywhere
- Worker: single DB-session scope per run; token-based lock with correct TTL;
  resume task that enters the graph at the checkpoint
- Retriever chain (Tavily → Brave → ddgs) with Redis cache; SSRF guard on
  `read_webpage`; untrusted-content framing
- Durable `agent_logs` + Redis pub/sub events from every node; real token/cost
  accounting from `usage_metadata`
- `LLM_MODE=fake` scripted models + fixture retrievers for tests
- Approval endpoint → audit row + resume; rework loop bounded

**DoD:** golden E2E tests 1 and 2 pass (API-level, fake-LLM mode) · regression tests
`test_executor_executes_tool_calls`, `test_resume_enters_graph_at_gate`,
`test_pipeline_persists_within_open_session`, `test_critic_fails_closed_on_invalid_output`
pass · one real-model smoke run produces a cited report end-to-end.

## M2 — Auth & API hardening  *(≈ 1 week)*

**Status: ✅ backend code complete.** Cookie auth with rotating refresh tokens + reuse
detection (`services/tokens.py`, `services/auth_service.py`), bcrypt-direct password policy
(`services/passwords.py`), per-operation atomic Lua rate limits (`services/rate_limit.py`),
security-headers middleware, `/docs` off in prod, SSE endpoint with agent_logs replay +
`Last-Event-ID`, slim list schemas, audit_log on approve. Next.js same-origin `/api` proxy +
CSP in `next.config.ts`. New v2 Alembic baseline (`0001_initial_v2_schema.py`) renders and
round-trips. 34 backend tests + 9 security-service unit tests green. Live auth/SSRF/rate-limit
integration suites run in CI with service containers. Remaining polish: `.md`/`.pdf` export
endpoints (weasyprint wiring), email verification toggle.

Scope: the security layer per [06_Security.md](06_Security.md).

- Cookie auth (access + rotating refresh), revocation, logout; bcrypt direct;
  password policy; neutral registration
- Same-origin proxy in Next.js (`rewrites`); remove all CORS config
- Per-operation rate limits (atomic Lua); login/register limits + lockout
- Security headers middleware (API + frontend); prod config gates (`/docs` off)
- SSE endpoint: cookie auth, history replay, `Last-Event-ID`
- Slim list schemas; export endpoints (`.md`, `.pdf`)

**DoD:** auth integration suite passes (register→login→refresh rotation→reuse
detection→logout revocation) · rate-limit and SSRF test suites pass · security
checklist items buildable-now all checked · OpenAPI reflects real contracts.

## M3 — Frontend rebuild  *(≈ 1–2 weeks)*

**Status: ✅ code complete.** TanStack Query owns all server state (`hooks/queries.ts`);
same-origin API client with transparent refresh-on-401 (`lib/api.ts`) — no `localStorage`,
no cross-origin URL (both grep-guarded in CI). Server-side cookie auth guard
(`app/(app)/layout.tsx`) plus client `AppShell` recovery. The session page renders all
five states: the PENDING/RUNNING brain-monitor (`PipelineRail` + `StatusBar` + `LiveFeed`)
driven by native `EventSource` with `Last-Event-ID` reconnect and a 5 s polling fallback
(`useSessionStream`); the AWAITING_APPROVAL split draft/decision gate with optimistic
re-subscribe; COMPLETED report with metrics + export (Copy / `.md` / print-to-PDF) and
grounded streaming chat; FAILED with reason, partial sources, and restart. Citations UX
(`lib/citations.tsx`): `[n]` chips with snippet popovers, sources panel, and a visible ⚠
"unverified" chip for unresolved markers — via a dependency-free rehype plugin (no
`rehype-raw`). Chat uses a UTF-8-safe buffered SSE parser (`lib/sse.ts`) with immutable
replace-by-id state, stop affordance, and input-restore. Design tokens are both-theme
first-class with WCAG-AA values; typography plugin, `next/font` (Inter + JetBrains Mono),
and react-hot-toast are wired. 39 Vitest unit tests (SSE parser incl. the split-UTF-8
regression, citation renderer, pipeline derivations, formatters) pass; Playwright golden
E2E 1–3 are wired to run against the real stack in `LLM_MODE=fake` via a new CI
`golden-e2e` job. Frontend CI now runs lint → typecheck → markdown/token-hygiene guards →
unit tests → build, then the golden E2E. Remaining polish: server-side `.md`/`.pdf` export
endpoints (M4; currently client-side).

Scope: the UI per [07_UIUX_Guidelines.md](07_UIUX_Guidelines.md).

- TanStack Query everywhere; shared API client; server-side auth guard via cookies
- Session page: five states, SSE with replay/reconnect/polling fallback,
  approve/rework flows that re-subscribe correctly
- Citations UX: `[n]` chips with snippet popovers + sources panel
- Chat with correct streaming parser (UTF-8-safe, buffered) and immutable state
- Dashboard + history (real API, no hardcoded URLs/tokens); theming via tokens only;
  typography plugin; `next/font`; react-hot-toast
- Frontend unit tests (SSE parser, citation renderer); Playwright golden E2E 1–3
  wired to compose fake-LLM mode

**DoD:** all three golden E2E tests pass in CI · both themes pass the WCAG AA
contrast check on core pages · no hardcoded hex/URLs/tokens (grep-guarded).

## M4 — Ship it  *(≈ 1 week)*

Scope: packaging, deployment, quality measurement per
[09](09_Deployment_and_Operations.md) / [08 §5](08_Testing_and_Quality.md).

- Dockerfiles (api/worker/frontend) + `docker-compose.full.yml`; migration-on-start
  entrypoint; healthchecks
- Full CI pipeline (lint → tests → E2E → audits) + release tagging workflow
- Eval harness + fixed query set + first recorded eval run; README badges (CI, eval)
- Production deploy guide (single host + TLS proxy); backup cron example
- Final README rewrite with screenshots/GIF of the golden path

**DoD:** clean-machine `docker compose -f docker-compose.full.yml up` →
register → cited report → approve → export, in under 15 minutes following only the
README · CI fully green on `main` · eval baseline committed · release `v1.0.0` tagged.

## v2 candidates (unscheduled, in rough priority order)

1. Document upload & hybrid research (user PDFs/notes as first-class sources)
2. Scheduled/recurring research with diff reports and notifications — the
   "research as a monitored pipeline" wedge
3. Shareable read-only report links
4. Team features: shared workspaces, reviewer roles, approval policies
5. Prometheus/Grafana observability pack
6. Additional export formats (DOCX, HTML) and Notion/Obsidian integrations

## Risk register

| Risk | Mitigation |
|---|---|
| Model deprecations break routing | config-driven IDs + price-table startup check + eval before switch ([03](03_Tech_Stack.md)) |
| Search APIs cost/limits | retriever chain + cache; DDG as keyless fallback; degradation is explicit, not silent |
| Scope creep past the wedge | [01](01_Product_Vision.md) out-of-scope list is binding; v2 list absorbs ideas |
| Solo-dev burnout mid-rebuild | vertical slices — every milestone is independently demoable and stoppable |
