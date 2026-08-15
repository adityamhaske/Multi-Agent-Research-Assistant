# Agent guidance — repository root

Read this first. Package-specific traps live in [`backend/AGENTS.md`](backend/AGENTS.md)
and [`frontend/AGENTS.md`](frontend/AGENTS.md); read the one you are about to touch.

**Keep this file current.** It describes traps, not features. When a change invalidates a
rule here, update it in the same commit — a stale rule is worse than no rule, because it
gets trusted. Add a rule only after something has actually bitten; this is not a style
guide.

---

## What this project is

A self-hostable, bring-your-own-key research assistant. A LangGraph pipeline
(Planner → Executor ⇄ Critic → Synthesizer → **human gate** → Finalizer) searches, gathers
cited evidence, and pauses at a durable checkpoint for human approval before finalizing.

**Input:** a research question + depth (`fast` | `balanced` | `comprehensive`), optionally
scoped to a project and an uploaded corpus.
**Output:** a cited Markdown report where every `[n]` resolves to a real source and a
verbatim supporting snippet, exportable to `.md`/`.pdf`, plus grounded follow-up chat over
approved reports.

## The invariant everything else serves

**The product claim is verifiability, so a false measurement is a P0 bug, not a cosmetic
one.** A citation that cannot be resolved must render its ⚠ unverified chip rather than
render clean. An eval or benchmark that could not measure something must say so — never
print `0.0`, never record a model id you did not actually call, never score a baseline
against placeholder text.

This has been violated before. In August 2026 a benchmark shipped that published all-zero
results as findings, recorded `claude-sonnet-4-6` in every trace while calling
`claude-3-5-sonnet-20241022`, and scored the competing baseline against the literal string
`"Content extracted by gpt-researcher"`. If you touch `backend/evals/`, re-read
`benchmark.py`'s `_build_judge` and `calc_support_rate` and preserve the distinction
between *unmeasured* and *zero*.

## Docs are the build contract

`docs/` is authoritative — see [`docs/00_INDEX.md`](docs/00_INDEX.md). Code that
contradicts the docs is wrong; docs that contradict shipped code must be fixed **in the
same PR** that changed the behavior. Nothing aspirational: every statement describes what
is built, or is explicitly marked `[PLANNED]`.

Cite the doc section in code comments when encoding a decision from it (`docs/13 §6`), the
way the existing code does. That is how a reader knows a line is deliberate.

## Configuration has two paths, and they drift

The same `RunConfig` is built by two independent code paths. **Change one, change both**,
or the CLI and the server silently disagree:

| Path | Built by | Used by |
|---|---|---|
| Server | `app/runtime.py` ← `app/config.py` (pydantic-settings) | API, Celery worker |
| Local | `research_engine/local.py::run_config_from_env` ← `os.environ` | CLI, eval harness, benchmark, desktop sidecar |

This has drifted twice. The local path once knew only Google/Anthropic/OpenAI keys, so
OpenRouter was unreachable and a `custom:` route silently fell through to
`api.openai.com`. It also defaulted `enforce_ssrf_guards` to `True`, applying the
production guard to a laptop and rejecting every local model server.

**Local endpoints:** `research_engine.llm_factory.map_local_host()` is the single
implementation that rewrites `localhost` → `host.docker.internal` inside a container. Use
it; do not re-implement it. Three copies of this logic existed once and two were wrong.

## The recurring bug: two hosts, one contract

Server and desktop are **parallel implementations of the same contract**. Every shared
behaviour has two homes, and the second one gets forgotten. Not hypothetical — each of
these was found in shipped code, not imagined:

| Behaviour | Copies | How many were wrong |
|---|---|---|
| `localhost` → `host.docker.internal` | 3 | 2 |
| Request fields reaching `Session(...)` (`corpus_mode`, `demo`) | 3 | 3 |
| Resolving `corpus_dir` | 2 | 2 — both relative, so upload and run disagreed |
| Validating a `provider:model` route | 2 | 1 — routing accepted what pricing refused |
| Where the bundled sidecar lives | 3 | 3 — see below |

**When you change any of these, grep for the other copy before you finish:**

- Config → `app/runtime.py` *and* `research_engine/local.py`
- Request → session → `app/api/v1/research.py` *and* `desktop/sidecar.py`
- Per-session run config → `app/workers/pipeline_runner.py` *and*
  `desktop/sidecar.py::_drive_session`
- Route validation → `app/services/model_routing.py::validate` *and*
  `research_engine/llm_factory.py::validate_pricing`
- Schema → an Alembic migration for Postgres *and* the ORM model, which is what the
  desktop's `create_all` plus startup column sync reads
- Sidecar location → `desktop/tauri.conf.json` (`bundle.resources`), `desktop/src/lib.rs`
  (`sidecar_command`), *and* `.github/workflows/desktop.yml` (the `shell` job must
  `needs: sidecar` and download the artifact)

That last row is the worst case so far, because all three copies were wrong at once and
nothing failed until someone ran the build: `tauri.conf.json` had no `resources` key, so
the sidecar was never copied in; `lib.rs` looked for it next to the executable, which is
not where `resources` puts it; and the CI `shell` job raced `sidecar` instead of depending
on it, so even a correct config would have bundled nothing. The result was a 5 MB `.app`
that passed CI, uploaded cleanly, and died on first launch. **A desktop bundle that has
not been launched is not verified** — check the artifact is ~180 MB, not ~5 MB.

The failure mode is always the same: the server path is exercised constantly, the desktop
path only at release time, so a divergence ships. Prefer extracting the shared logic into
one function over keeping two copies in step by discipline — `map_local_host` is the
worked example of doing that after the fact.

## Provider and cost rules

- Routing is `"provider:model"`, split on the **first** colon only — `ollama:qwen2.5:7b`
  is provider `ollama`, model `qwen2.5:7b`.
- `validate_pricing()` skips `openrouter` and `custom`, so `estimate_cost()` returns `0.0`
  for them and **`MAX_COST_PER_SESSION_USD` is a no-op on those providers**. A `$0.00` in
  the UI does not mean a run was free. Cap spend at the provider.
- Router aliases (`auto/*`) are **not** pinned models: they resolve differently per call
  and the alias can disagree with what served the request. Never treat one as a disclosed
  model — record what actually answered.

## Never fake, never swallow

- No `print` in application code — `structlog.get_logger()`, correlation bound to
  `session_id` (see `backend/AGENTS.md`).
- A caught provider error must surface its message. `graph.py::_structured` swallowing an
  exception into `None` once produced "planner: could not produce a valid task list" for
  what was actually an exhausted quota, sending debugging in the wrong direction for days.

## What CI actually enforces

Green locally ≠ green in CI. Run what CI runs:

```bash
cd backend && ruff check app/ research_engine/ tests/ evals/ && ruff format --check app/ research_engine/ tests/ evals/ && python -m pytest
cd frontend && npm run lint && npm run typecheck && npm test && npm run build
```

Note the backend lint path **includes `evals/`** and excludes `desktop/`, `alembic/`, and
repo-root scripts. A lint-clean `app/` is not a green build.

The frontend job also runs four bespoke greps that fail the build (see
`.github/workflows/ci.yml`): no `dangerouslySetInnerHTML`/`rehype-raw`, no hardcoded hex
colors, no hardcoded backend URLs, and no web-storage access without an inline
`ci-allow-web-storage: <reason>` marker.

## Local development

- Whole stack: `./start.sh` (Docker; `--fake` for a keyless demo, `--stop`, `--reset`).
- Frontend dev port is **3031**, not 3000. `FRONTEND_URL` in `.env` is the CORS allow-list
  and must match, or the API rejects the browser.
- The frontend container is a **static `next build` image**, not a bind-mounted dev
  server: source edits need `docker compose -f docker-compose.full.yml build frontend`,
  not a page reload.
- Postgres must be a **pgvector** image — migration 0006 enables the extension and 0007
  creates a vector column, so stock Postgres fails `alembic upgrade head` outright.
- Research and chat rate limits default to **0, which means unlimited**
  (`research_rate_limit_per_hour` / `chat_rate_limit_per_hour` in `app/config.py`). They
  were once a hardcoded 5/hour that applied even to a free local model; if you set a
  non-zero value, note it is enforced before model routing is consulted.

## Skills worth reaching for

All of these are already available in this environment — nothing to install. Listed
because a skill nobody remembers exists is the same as one that does not.

| Working on | Skill |
|---|---|
| Anything, before debugging | `superpowers:systematic-debugging` |
| New feature or bugfix | `superpowers:test-driven-development`, `ecc:tdd-workflow` |
| `app/api/`, routes, dependencies | `ecc:fastapi-patterns`, `/ecc:fastapi-review` |
| `research_engine/`, engine internals | `ecc:python-patterns`, `/ecc:python-review` |
| Retrieval, chunking, memory | `ecc:iterative-retrieval`, `ecc:rag-pipeline` |
| `evals/`, measurement claims | `ecc:eval-harness`, `ecc:benchmark-methodology` |
| Model routing, spend | `ecc:cost-aware-llm-pipeline`, `ecc:token-budget-advisor` |
| Alembic, schema changes | `ecc:database-migrations`, `ecc:postgres-patterns` |
| Celery, queues, caching | `ecc:redis-patterns` |
| `frontend/` components | `ecc:react-patterns`, `/ecc:react-review` |
| Frontend tests | `ecc:react-testing`, `ecc:e2e-testing` |
| Contrast, keyboard, ARIA | `ecc:frontend-a11y`, `ecc:accessibility` |
| Auth, SSRF, secrets | `ecc:security-review`, `/ecc:security-scan` |
| Compose, images, deploy | `ecc:docker-patterns`, `ecc:deployment-patterns` |

## Housekeeping

Runtime artifacts must not be committed. `data/corpus/*.sqlite`, `__pycache__`, `.venv`,
`.next`, and tool directories (`.qoder/`) are ignored — but an ignore rule does not
untrack a file that is already tracked. `corpus_dir` defaults to the **relative** path
`data/corpus`, so running from the repo root and from `backend/` creates two different
corpus roots.
