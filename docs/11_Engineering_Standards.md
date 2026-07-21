# 11. Engineering Standards

> DOs, DON'Ts, and conventions. Most of these are scar tissue from the July 2026
> audit — each banned pattern shipped a real bug in the previous iteration.

## 1. Non-negotiables (the DON'T list)

1. **DON'T ship "temporarily simplified" versions of core mechanisms.** The
   hand-rolled "M1 graph runner" broke resume, finalization, and tool execution.
   If the design says checkpointed graph, build the checkpointed graph first.
2. **DON'T fail open.** No `except: default_to_pass`, no silent empty-list fallbacks,
   no `except Exception: pass`. Parse/validation failures stop the unit of work with a
   recorded reason.
3. **DON'T let docs and code diverge.** Behavior change → doc change in the same PR.
   README claims are verified by the review checklist.
4. **DON'T bind tools without executing them.** Any `bind_tools` call must have a
   corresponding tool-execution loop (ToolNode). Grep-able rule.
5. **DON'T use DB sessions outside their scope.** One `async with` per unit of work;
   the ORM objects it loads don't outlive it.
6. **DON'T put tokens in localStorage or URLs.** Auth is httpOnly cookies, full stop.
7. **DON'T add dependencies without an import site in the same PR.** No résumé deps.
8. **DON'T hardcode** URLs, hex colors, model IDs, prices, or secrets in code — all
   of these live in config/tokens.
9. **DON'T use `create_all`** outside tests. Alembic owns the schema.
10. **DON'T render raw HTML from model output.** No `rehype-raw`, no
    `dangerouslySetInnerHTML` (CI-guarded).
11. **DON'T write assistant history back as system messages.** Roles are sacred:
    `SystemMessage` = us, `AIMessage` = model, `HumanMessage`/untrusted-tagged = data.
12. **DON'T catch-and-retry non-idempotent expensive work automatically.** A timed-out
    pipeline is FAILED with a reason; resume is explicit and checkpoint-based.

## 2. DOs

1. **Vertical slices with tests.** Every feature lands with its unit/integration tests;
   milestones end with green golden E2E.
2. **Fail fast at startup.** Validate config (secrets, model prices, provider keys)
   before serving traffic.
3. **Structured everything.** Pydantic at every LLM boundary; structured outputs over
   "return only JSON" prompts; typed SSE events.
4. **Log with context.** Every log line binds `session_id` (and `node` in the
   pipeline). Never log secrets, tokens, or full page content.
5. **Name things by role, not implementation.** `retriever_chain`, not
   `tavily_client`; roles allow swapping providers.
6. **Small PRs mapped to roadmap items.** Reference the milestone (e.g. `M1:`) in the
   PR title.

## 3. Code style

### Python
- ruff (lint + format), line length 100; full type hints on public functions;
  `from __future__` not needed (3.11+).
- Async by default in API/worker paths; blocking calls only via `asyncio.to_thread`.
- Module layout: `app/api/` (routers), `app/agent/` (graph, nodes, prompts, schemas,
  tools, guards), `app/models/` (ORM), `app/schemas/` (API DTOs), `app/services/`
  (auth, rate-limit, export), `app/workers/` (celery), `app/db/`.
- Exceptions: domain exceptions (`PipelineBudgetExceeded`, `SSRFBlocked`) over
  generic ones; handlers translate to HTTP at the router layer only.

### TypeScript/React
- `tsc --noEmit` clean; eslint (next config) clean.
- Server components by default; `"use client"` only where interaction demands it.
- Data fetching through the shared API client + TanStack Query hooks in
  `lib/api/`; components never call `fetch` directly.
- Immutable state updates only; keys are stable ids, never array indexes for
  dynamic lists.
- Styling via Tailwind utilities + CSS-variable tokens; no inline hex, no inline
  style objects for themable properties.

## 4. Git conventions

- Conventional commits (`feat:`, `fix:`, `docs:`, `test:`, `refactor:`, `chore:`),
  imperative mood, ≤ 72-char subject.
- Branch names: `m1/executor-tool-loop`, `fix/sse-replay-order`.
- `main` is protected: PRs only, green CI required. No force-push to `main`.
- Migrations are append-only once merged; fixing a merged migration means a new one.

## 5. PR review checklist

Reviewer confirms before approving:

- [ ] Tests included and meaningful (not just coverage theater); regression test if
      fixing a bug
- [ ] Docs updated if behavior/config/API changed; README still truthful
- [ ] New config keys added to `.env.example` + startup validation where applicable
- [ ] No banned patterns (§1) — especially fail-open handlers and unscoped sessions
- [ ] Prompt/model changes include an eval run result in the PR description
- [ ] Error paths produce user-visible, actionable states (no silent degradation)
- [ ] DB changes: migration + round-trip works; indexes for new query patterns
- [ ] No secrets, tokens, or personal data in code, fixtures, or logs

## 6. When docs and reality must diverge temporarily

Sometimes a slice lands in pieces. The rule: the doc gains a **[PLANNED — Mx]** marker
in the same PR, so no reader ever mistakes intention for implementation. A doc
statement without that marker is a claim that the thing exists and works — and the
golden E2E suite is the proof.
