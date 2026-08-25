"""Regression: a Celery worker must finish its heavy imports before it reports ready.

Measured in CI (run 31958153365), from `/tmp/worker.log`:

    Task run_agent_pipeline[28d1...] received      16:21:04.795
    pipeline_task_started                          16:21:05.851
    ...35 seconds of silence, no graph events...
    Task ... succeeded in 35.338s                  16:21:40.135
    Task run_agent_pipeline[1de4...] succeeded in 0.264s

Identical code and input, 135x apart. The gap is LangGraph, LangChain and the provider
clients importing inside the *first* task — `AsyncPostgresSaver` is imported in the body
of `_execute`, and the graph module follows it in.

`celery inspect ping` answers during that window, because the process is alive and its
event loop responds. CI used that as its readiness gate, so it started the golden E2E
against a worker that could not yet run anything, and a journey waiting on the first
pipeline event sat on "Waiting for the pipeline to start…". The same 35s is paid by the
first real request after every deploy.
"""

import sys

from app.workers import celery_app as celery_app_mod


def test_worker_boot_preloads_the_pipeline_imports():
    """Preloading is what makes 'ready' mean ready — pay the import cost at boot."""
    celery_app_mod.preload_pipeline_imports()

    # The graph is the expensive one: it pulls in LangGraph and the provider clients.
    assert "research_engine.graph" in sys.modules
    assert "langgraph.checkpoint.postgres.aio" in sys.modules


def test_preloading_is_safe_to_repeat():
    """Runs once per forked child, and a failed import must never kill the worker."""
    celery_app_mod.preload_pipeline_imports()
    celery_app_mod.preload_pipeline_imports()
