# 08. Testing & Quality

> The previous iteration shipped four fatal bugs that any single end-to-end test would
> have caught, while its Makefile advertised a test suite that did not exist. This doc
> defines the test strategy that prevents a recurrence. **A feature without its tests
> is not done** ([10_Roadmap.md](10_Roadmap.md) DoD).

## 1. Test pyramid

| Layer | Tooling | Scope | Speed |
|---|---|---|---|
| Unit (backend) | pytest | schemas, guards (SSRF, rate-limit Lua, password rules), cost math, prompt/citation validators | ms |
| Integration (backend) | pytest + httpx ASGI client + Postgres/Redis (docker) | API endpoints against real DB/Redis; auth flows; migrations round-trip | s |
| Pipeline (backend) | pytest + **FakeListChatModel-style scripted LLMs** | the compiled LangGraph end-to-end with deterministic fake models & fake retrievers — no network, no API keys | s |
| Unit (frontend) | Vitest + Testing Library | SSE parser, citation renderer, state reducers | ms |
| Golden E2E | Playwright against `docker compose up` with fake-LLM mode | the three golden journeys (§2) through the real stack | min |
| Evals | custom harness | report quality vs. fixed query set with real models (manual/nightly, not per-commit) | min–$ |

## 2. The three golden E2E tests

These encode the product's core promise. CI blocks merge to `main` if any fails.
The backend supports `LLM_MODE=fake` (env): the LLM factory returns scripted models
and the retriever chain returns fixture results, so E2E runs are deterministic and free.

1. **Research reaches the gate.** Register → login → submit query → live feed shows
   planner/executor/critic/synthesizer events via SSE → session reaches
   `AWAITING_APPROVAL` **in the database** → draft + sources render.
   *(Would have caught: tools never executing, DB writes on a closed session,
   unauthenticated EventSource, missing typography plugin.)*
2. **Approval completes the session.** From the gate: approve → session reaches
   `COMPLETED` without re-running planner/executor (asserted via fake-model call
   counts) → final report + sources render → export `.md` and `.pdf` download →
   audit row exists.
   *(Would have caught: finalizer never called, approve re-running the pipeline,
   unreachable chat.)*
3. **Rework loops and chat works.** From the gate: reject with feedback → synthesizer
   re-runs with the feedback (asserted) → gate again → approve → chat question streams
   an answer grounded in the report; history persists on reload.
   *(Would have caught: resume-from-scratch, SystemMessage role corruption, SSE
   chunk-boundary parsing loss.)*

## 3. Regression tests for the July 2026 audit findings

Every confirmed critical/high finding gets a named regression test:

- `test_executor_executes_tool_calls` — fake model emits tool calls; asserts the tool
  actually ran and evidence contains its results.
- `test_pipeline_persists_within_open_session` — status transitions visible in a fresh
  DB connection immediately after each node.
- `test_resume_enters_graph_at_gate` — planner is invoked exactly once across
  submit + approve.
- `test_critic_fails_closed_on_invalid_output`.
- `test_session_lock_outlives_task_timeout` and `test_lock_release_is_owner_only`.
- `test_rate_limit_keys_are_per_operation`.
- `test_sse_replays_history_and_supports_last_event_id`.
- `test_ssrf_guard_blocks_metadata_and_private_ranges` (parameterized IP corpus).
- `test_empty_migration_rejected` — upgrade→downgrade→upgrade round-trip equality.
- Frontend: `test_sse_parser_handles_split_utf8_and_partial_events`.

## 4. CI (GitHub Actions)

Pipeline on every PR and push to `main`:

1. `ruff check` + `ruff format --check`; `eslint`; `tsc --noEmit`
2. gitleaks secret scan; markdown-safety grep guard (`rehype-raw`,
   `dangerouslySetInnerHTML`)
3. Backend unit + pipeline tests (no services)
4. Backend integration tests (Postgres + Redis service containers; run
   `alembic upgrade head` first — migrations are exercised on every CI run)
5. Frontend unit tests + `next build`
6. Golden E2E (compose up in fake-LLM mode + Playwright)
7. `pip-audit` + `npm audit --audit-level=critical` (non-blocking report)

`main` is a protected branch; merges require green CI.

## 5. Evals — report quality measurement

Per-commit tests use fake models; **evals** measure real-model quality. Harness in
`backend/evals/`:

- Fixed query set (10 queries across domains, versioned in the repo).
- Metrics per run: **citation support rate** (does the cited snippet actually support
  the claim — judged by a strong model), source count, uncited-claim count, cost,
  latency, pipeline completion rate.
- Run manually (`make eval`) and before any model/prompt change is merged; results
  committed to `backend/evals/results/` as dated JSON so quality is diffable over time.
- Release criterion: citation support ≥ 95%, completion rate ≥ 90% on the fixed set.

## 6. Quality gates summary

| Gate | Enforced by |
|---|---|
| No merge with failing golden E2E | branch protection |
| No schema change without migration round-trip test | CI step 4 |
| No prompt/model change without an eval run in the PR | review checklist ([11](11_Engineering_Standards.md)) |
| No new dependency without an import site | review checklist |
| Docs updated in the same PR as behavior changes | review checklist |
