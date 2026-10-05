# Agent guidance — backend

This is the hottest path in the repo (`app/` + `research_engine/`). Read this before
touching either package; the architecture docs in `docs/architecture/` are authoritative
but not exhaustive on these traps.

## Hard boundary: `research_engine` never imports `app` **or `evals`**

`research_engine/` is a local-first engine (docs/architecture/13-local-and-self-hosted.md)
that knows nothing about Postgres, Redis, Celery, or ORM models. The host supplies
everything through ports (`research_engine/ports.py`) and per-run `RunConfig`. If you find
yourself importing `app.config` or an ORM model inside `research_engine`, stop — wire it
through `app/runtime.py` (`install_process_default`, `run_config_from_settings`) or the
runner's ports instead (see `app/workers/pipeline_runner.py` for the canonical example).

`evals` is on the same list, and was added to it late. `bundle.py` imported
`evals.metrics` for claim extraction while `graph.py`'s own docstring asserted the engine
imported nothing from evals — so the "standalone" package could not be bundled into the
desktop app without also shipping the eval harness, and nothing failed until someone
tried. `tests/workflow/test_engine_boundary.py` now forbids both roots.

**Claim extraction and the citation regex have exactly one home: `research_engine/claims.py`.**
`evals.metrics` re-exports from it — the dependency runs evals → engine, never back. Three
things must agree about what a claim is, because they act on the same sentences: the
graph's citation-fidelity pass strips markers from claims their evidence does not back,
the eval judge measures how well that worked, and the bundle records them for a third
party to verify. Two definitions is how the published number stops describing the guard.
`tests/task/test_claim_extraction_parity.py` pins the agreement *by object identity*, so a
copy-paste back into `evals/metrics.py` fails the suite rather than drifting quietly.

Two scanning differences between `graph._cited_claims` and `claims.claim_lines` remain on
purpose and are pinned by that same test — a bare `Sources` line, and the conflict block
(which the fidelity pass never sees, because `synthesizer_node` appends it afterwards).
Unifying either changes what the judge counts as a claim, which is a metrics-definition
change and needs a `METRICS_VERSION` bump to be disclosed honestly.

`verify_bundle.py` keeps its own copies of two patterns so it runs on stdlib plus pydantic
alone. That duplication is deliberate and is asserted equal to the canonical ones.

## Schema belongs to Alembic

Never call `create_all()` or mutate tables from application code. Schema changes go
through `alembic revision --autogenerate` + a review of the generated migration
(docs/architecture/05-data-model.md).

## The pipeline is not idempotent

A crashed research run is resumed from its LangGraph checkpoint by an explicit action,
never by broker redelivery or Celery auto-retry. Do not add `autoretry_for` /
`retry_backoff` to tasks in `app/workers/tasks.py` — double execution would double-spend
LLM budget (docs/architecture/02 §6).

## One event loop per worker process

A Celery task runs its coroutine through `app/workers/event_loop.run`, never a loop of its
own. Provider SDKs cache their HTTP client process-wide (`langchain_openai` and
`langchain_anthropic` keep one per base URL), and its pooled keep-alive connections belong
to the loop that opened them. With a loop per task, the next task in the same prefork child
met a connection from a closed loop: every gated run on an OpenAI-compatible route failed at
plan approval with `RuntimeError: Event loop is closed`. openai 2.x had retried that away
(sending the request twice), and anthropic still does, so a call that *succeeds* proves
nothing. `tests/workflow/test_worker_event_loop.py` makes real keep-alive HTTP calls across
the task boundary and forbids a per-task loop anywhere in `app/workers/`.

**The worker must run the prefork (default) or solo pool.** The clients this loop keeps
valid are per *process*. A threads pool would put several loops on one cached client — the
same defect — so `event_loop.run` refuses a second thread by name rather than serving it.

**`tests/workflow/test_worker_task_lifecycle.py` drives the production path in real mode**:
the real Celery task bodies, `execute_run`, Postgres, Redis and the event sink, with the real
factory's `ChatOpenAI` over keep-alive HTTP to `tests/fake_provider.py`. It covers five gated
runs in one process, a provider failure followed by a healthy next run, and concurrent runs
on one loop. Fake mode cannot stand in for it, because fake mode never builds a provider
client. The fake provider's executor reads a page before quoting it, so real-mode citation
verification passes honestly rather than being bypassed.

## Provider SDKs are pinned

`constraints.txt` pins the provider SDKs, their LangChain integrations and the HTTP stack
beneath them to exact versions. `requirements.txt` applies it with a `-c` line, so every
install that reads requirements gets the same set with no flag of its own: the image, both
CI jobs, `pip-audit` and the desktop sidecar build. These packages decide what a provider
call retries, raises, pools and verifies. openai 2.x → 3.x arrived as a transitive float
with no diff here, and turned the loop bug above from silently retried into failed runs.

`tests/task/test_dependency_constraints.py` requires exact pins for the governed set, and
requires `requirements.txt` floors to admit them. **It also fails when the running
environment is not on the pinned versions.** A stale venv is how that bug hid locally, so
reinstall rather than skip the test.

**Upgrading is a reviewed change:**

1. See what floating would pick: `sed '/^-c /d' requirements.txt | uv pip compile -`. Use
   this, not `--upgrade-package`, which cannot move a package past an exact constraint.
2. Edit the pin, then run `uv pip compile requirements.txt`, which applies the constraints.
   It either resolves or names the governed package that has to move with it. Move that one
   in the same change.
3. Read the SDK's changelog for retry, error-type, timeout and connection-pool changes, and
   say in the PR what changed.
4. Reinstall, then run the suite. `tests/workflow/test_worker_event_loop.py` is the one that
   makes real keep-alive HTTP calls through each SDK across a task boundary.

**Two signals mean it is time to move a pin.** `pip-audit` flags a pinned version, since
pins no longer float to a patched release. Or a build fails to resolve naming a governed
package, meaning an unpinned dependency such as langgraph now needs a newer one. Both are
loud by design; neither is a reason to loosen a pin to a range.

## A node's fan-out never outlives the node

Graph nodes fan out with `research_engine.concurrency.gather_or_cancel`, not
`asyncio.gather`. `gather` returns the first failure while the siblings run on. Those
siblings then call the model for a run that has already failed, and write events through a
sink bound to the session the run driver is closing. SQLAlchemy's refusal of that close
became the run's recorded failure reason in place of the provider error.

**What it reports is the earliest failure, not the first argument's.** A failure often breaks
state its siblings share, so a sibling fails as a consequence in the same turn of the loop.
Argument order would record the consequence.

**Cancellation waits for writes.** `emit` finishes a write already under way before a
cancellation lands, because cancelling mid-commit leaks the aiosqlite connection. The worker
loop depends on that too: on a soft time limit it cancels the task's own coroutine first
(`event_loop._unwind`) so cancellation travels this path. Sweeping every task at once would
cancel the shielded write directly.

The regression, `tests/workflow/test_node_failure_is_not_masked.py`, needs Postgres: the
masking reproduced 200/200 on asyncpg and 0/200 on aiosqlite.

## Logging and correlation

Log with `structlog.get_logger()`, never `print`. Configuration lives in
`app/logconfig.py` (installed by `app/main.py`, `app/workers/celery_app.py` and
`desktop/sidecar.py`). Bind the identity at boundaries instead of threading an ID through
signatures; engine logs inherit it via contextvars — `app/workers/event_loop.run` hands each
task a fresh copy of the caller's context, and `create_task` copies it again.

**Two pipelines, two binders, and they are not interchangeable.**
`bind_session_context(session_id)` is for a `sessions.id`; `bind_research_run_context(run_id)`
is for a `research_runs.id`. Both write `correlation_id` — the join key — plus the key that
names what it is. There was one binder once, hard-coded to write `session_id`, and the three
*run* Celery tasks called it with run ids, so every server-side run log claimed a session
that did not exist. **A run id under `session_id` is a defect**, pinned by
`tests/workflow/test_run_correlation.py`.

Bind sites are few and shared on purpose: `runs.py::_run_or_404` covers twelve run routes on
**both** hosts (a `Depends` would not — the sidecar wraps these handlers in its own routes),
`create_run` covers the thirteenth, and each host's driver binds inside the task that drives
the run. `GET /runs` binds nothing: it names no run.

`app/metrics.py` is the sibling module for counters, and the same rule holds there — every
label value comes from a closed list, so no identifier can reach `/metrics`.

## Model catalog is a fact source, not a guess

Model capabilities (sampling support, pricing, context windows) are declared in
`research_engine/catalog.py` and validated at startup by `validate_pricing()`. When a
provider rejects a parameter or a model mis-routes, update the catalog entry — do not
special-case it in `llm_factory.py`.

## Tests run with no network, no keys

`python -m pytest` runs entirely on `LLM_MODE=fake` determinism
(`research_engine/fakes.py`). If a new graph feature changes the executor/critic/
synthesizer contract, the scripted fakes must be updated in the same change or the whole
suite goes red. Real-model evals are opt-in: `LLM_MODE=real GOOGLE_API_KEY=… make eval`.
