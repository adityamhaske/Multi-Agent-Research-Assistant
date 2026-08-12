"""Celery application configuration (docs/02 §6)."""

from celery import Celery

from app.config import settings
from app.logconfig import configure_logging
from app.runtime import install_process_default

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
