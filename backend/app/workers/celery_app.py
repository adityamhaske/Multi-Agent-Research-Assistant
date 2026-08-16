"""Celery application configuration (docs/02 §6)."""

import structlog
from celery import Celery
from celery.signals import worker_process_init

from app.config import settings
from app.logconfig import configure_logging
from app.runtime import install_process_default

logger = structlog.get_logger(__name__)

# Worker processes never import app.main, so structlog is configured here too
# — same merge_contextvars pipeline the API uses, so a run's correlation_id joins
# logs across the API → Celery boundary.
configure_logging(json_output=settings.is_production)

# `research_engine` does not read `app.config` (docs/13 §2) — the worker process installs
# the engine's baseline config here, before any task can import the graph.
install_process_default()

celery_app = Celery(
    "research_worker",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.workers.tasks"],
)

# Hard limit from config; soft limit derived so raising one never inverts them.
_HARD = settings.celery_task_timeout_seconds
_SOFT = max(60, _HARD - 60)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_ignore_result=True,
    # The pipeline is NOT idempotent; a crashed run is resumed from the LangGraph
    # checkpoint by an explicit retry, never by broker redelivery (docs/02 §6).
    task_acks_late=False,
    worker_prefetch_multiplier=1,
    task_soft_time_limit=_SOFT,
    task_time_limit=_HARD,
)


def preload_pipeline_imports() -> None:
    """Import LangGraph, the graph and the checkpointer now, not inside the first task.

    Measured in CI: the first `run_agent_pipeline` took **35.3s** and the second **0.26s**
    on identical input, with 35 seconds of silence between `pipeline_task_started` and
    any further log line. That is import time, paid by whoever submits the first request
    after a worker starts — a real user after every deploy, and the golden E2E in CI.

    It also made the worker's readiness signal a lie: `celery inspect ping` answers while
    this import is still pending, because the process is alive and its event loop
    responds. CI gated the E2E on that ping, started the journeys against a worker that
    could not yet run anything, and the live feed sat on "Waiting for the pipeline to
    start…" — a symptom that points at SSE and costs hours before anyone reads the worker
    log.

    Import failures are logged, never raised: a worker that cannot preload should still
    boot and let the task surface the real error with its own context. Idempotent, since
    every forked child runs it and repeated imports are served from `sys.modules`.
    """
    try:
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver  # noqa: F401

        import research_engine.graph  # noqa: F401  — pulls in LangGraph + provider clients
    except Exception as e:  # noqa: BLE001 — a preload miss must not stop the worker booting
        logger.warning("worker_preload_failed", error=str(e))
    else:
        logger.info("worker_preload_complete")


@worker_process_init.connect
def _preload_on_worker_boot(**_: object) -> None:
    """Per forked child: prefork copies-on-write, but each child imports on its own."""
    preload_pipeline_imports()
