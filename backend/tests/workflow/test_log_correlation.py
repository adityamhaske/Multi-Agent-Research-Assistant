"""
Structured logging + run correlation (harness Change Validation finding).

structlog must be configured with merge_contextvars, and a session's correlation
identity (= session_id) bound at a boundary must appear on every log emitted in
that context — that is what lets a failed session be joined across the
API → Celery → engine boundary.

The **session** half. `bind_session_context` is the original binder under an accurate
name; the run surface has its own, and the two are held apart by
`tests/workflow/test_run_correlation.py`. Every assertion below is unchanged.
"""

from __future__ import annotations

import json

import pytest
import structlog
from structlog.testing import CapturingLoggerFactory

from app.logconfig import bind_session_context, clear_run_context, configure_logging


@pytest.fixture()
def capturing_logs():
    """Install the real configuration, capture output, restore defaults after."""
    configure_logging(json_output=True)
    factory = CapturingLoggerFactory()
    structlog.configure(logger_factory=factory, processors=structlog.get_config()["processors"])
    yield factory
    structlog.reset_defaults()
    clear_run_context()


def test_bound_correlation_id_rides_along_every_log(capturing_logs):
    clear_run_context()
    bind_session_context("sess-123", user_id="u-1")

    structlog.get_logger().info("research_started")

    rendered = json.loads(capturing_logs.logger.calls[0].args[0])
    assert rendered["correlation_id"] == "sess-123"
    assert rendered["session_id"] == "sess-123"
    assert rendered["user_id"] == "u-1"
    assert rendered["event"] == "research_started"


def test_clear_run_context_stops_identity_leaking(capturing_logs):
    bind_session_context("sess-123")
    clear_run_context()

    structlog.get_logger().info("unrelated")

    rendered = json.loads(capturing_logs.logger.calls[0].args[0])
    assert "correlation_id" not in rendered
    assert "session_id" not in rendered


def test_correlation_id_propagates_onto_the_worker_loop(capturing_logs):
    """The engine runs on the worker's per-process loop, not a loop per task. That loop is
    an `asyncio.Runner`, which reuses one context for every call unless handed a fresh one —
    so logs from inside the coroutine carry the identity bound just before only because
    `event_loop.run` copies it per task."""
    from app.workers import event_loop

    clear_run_context()
    bind_session_context("sess-async")

    async def inner():
        structlog.get_logger().warning("executor_budget_stop")

    try:
        event_loop.run(inner())
    finally:
        event_loop.shutdown()

    rendered = json.loads(capturing_logs.logger.calls[0].args[0])
    assert rendered["correlation_id"] == "sess-async"
