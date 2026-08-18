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
tried. `tests/test_engine_boundary.py` now forbids both roots.

**Claim extraction and the citation regex have exactly one home: `research_engine/claims.py`.**
`evals.metrics` re-exports from it — the dependency runs evals → engine, never back. Three
things must agree about what a claim is, because they act on the same sentences: the
graph's citation-fidelity pass strips markers from claims their evidence does not back,
the eval judge measures how well that worked, and the bundle records them for a third
party to verify. Two definitions is how the published number stops describing the guard.
`tests/test_claim_extraction_parity.py` pins the agreement *by object identity*, so a
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

## Logging and correlation

Log with `structlog.get_logger()`, never `print`. Configuration lives in
`app/logconfig.py` (installed by both `app/main.py` and `app/workers/celery_app.py`).
The correlation identity for a research run is its **session_id**: bind it at boundaries
with `app.logconfig.bind_run_context(...)` instead of threading a new ID through
signatures. Engine logs inherit it via contextvars under `asyncio.run`.

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
