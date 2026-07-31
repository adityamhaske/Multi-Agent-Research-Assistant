"""
research_engine — the research pipeline, independent of any host.

A compiled LangGraph `StateGraph` (planner → executor ⇄ critic → synthesizer →
`interrupt()` gate → finalizer), its tools, retriever chain, model factory, and
citation-bearing schemas. See docs/architecture/04_Agent_Design.md for the graph contract.

**This package must not import the server host** (`app.*`) or read process
environment. Everything it needs arrives through `runconfig.RunConfig`, installed
by whichever host is running it:

- server  — `app.runtime.install_process_default()` (API, Celery worker, evals)
- desktop — a local builder reading on-disk config + the OS keychain (docs/12 M9)

Side effects are injected the same way: the event sink via `events.set_emitter`,
per-user provider keys via `llm_factory.set_user_keys`. That is what lets the same
graph run against Postgres + Redis on a server and SQLite in a desktop app.

`tests/test_engine_boundary.py` enforces the boundary; docs/13 §3 is the contract.
"""
