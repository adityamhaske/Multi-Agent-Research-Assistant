"""
research_engine — the research pipeline, independent of any host.

A compiled LangGraph `StateGraph` (planner → executor ⇄ critic → synthesizer →
`interrupt()` gate → finalizer), its tools, retriever chain, model factory, and
citation-bearing schemas. See docs/architecture/04-agent-architecture.md for the graph contract.

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

import sys

# CI runs this package only on the image's Python (AGENTS.md). Run from a checkout — which is
# how a third party runs `python -m research_engine.verify_bundle` — pip's requires-python
# never applies, and an older interpreter would stop at a SyntaxError in 3.14-only syntax
# instead of saying which Python it needs. A RuntimeError, so no caller reads it as optional.
if sys.version_info < (3, 14):  # noqa: UP036 — the floor is enforced here, not assumed
    raise RuntimeError(f"research_engine needs Python 3.14+, this is {sys.version.split()[0]}")
