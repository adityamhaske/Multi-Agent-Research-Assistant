"""
Structured logging configuration for both the API and the Celery worker.

structlog is imported across the app and the research engine, but nothing ever
configured it, so every `get_logger()` fell back to default formatting with no shared
context. This module installs one configuration for both processes and provides the
helper that binds a run's correlation identity into contextvars, so every log between
the API trigger, the Celery task, and the research engine carries the same
`correlation_id` — letting a failed run be joined end to end across the async boundary.

The correlation identity is the session_id: it is the one identity that exists on both
sides of the API → Celery hop, so no new ID needs to be threaded through task arguments.
"""

from __future__ import annotations

import structlog


def configure_logging(*, json_output: bool) -> None:
    """Install the process-wide structlog configuration. Idempotent.

    `merge_contextvars` is the point of this module: context bound at a boundary
    (API trigger, Celery task entry) rides along every log emitted in that context,
    including the engine running under `asyncio.run` in the worker.
    """
    renderer = (
        structlog.processors.JSONRenderer() if json_output else structlog.dev.ConsoleRenderer()
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            renderer,
        ],
        cache_logger_on_first_use=True,
    )


def bind_run_context(session_id: str, **extra) -> None:
    """Bind a research run's correlation identity to the current context.

    Call at the API trigger point and at Celery task entry; all logs in that context
    then carry `correlation_id` (= session_id) without every call site passing it.
    """
    structlog.contextvars.bind_contextvars(
        correlation_id=session_id, session_id=session_id, **extra
    )


def clear_run_context() -> None:
    """Drop all bound context — call at Celery task entry so long-lived worker
    processes never leak one run's identity into the next task's logs."""
    structlog.contextvars.clear_contextvars()
