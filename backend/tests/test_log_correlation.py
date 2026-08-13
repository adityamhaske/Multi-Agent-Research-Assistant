"""
Structured logging + run correlation (harness Change Validation finding).

structlog must be configured with merge_contextvars, and a run's correlation
identity (= session_id) bound at a boundary must appear on every log emitted in
that context — that is what lets a failed research run be joined across the
API → Celery → engine boundary.
"""

from __future__ import annotations

import json

import pytest
import structlog
from structlog.testing import CapturingLoggerFactory

from app.logconfig import bind_run_context, clear_run_context, configure_logging


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
    bind_run_context("sess-123", user_id="u-1")

    structlog.get_logger().info("research_started")

    rendered = json.loads(capturing_logs.logger.calls[0].args[0])
    assert rendered["correlation_id"] == "sess-123"
    assert rendered["session_id"] == "sess-123"
    assert rendered["user_id"] == "u-1"
    assert rendered["event"] == "research_started"


def test_clear_run_context_stops_identity_leaking(capturing_logs):
    bind_run_context("sess-123")
    clear_run_context()

    structlog.get_logger().info("unrelated")

    rendered = json.loads(capturing_logs.logger.calls[0].args[0])
    assert "correlation_id" not in rendered
    assert "session_id" not in rendered


def test_correlation_id_propagates_into_asyncio_runs(capturing_logs):
    """The engine runs under asyncio.run in the worker; asyncio copies the current
    context, so logs from inside the coroutine must carry the bound identity."""
    import asyncio

    clear_run_context()
    bind_run_context("sess-async")

    async def inner():
        structlog.get_logger().warning("executor_budget_stop")

    asyncio.run(inner())

    rendered = json.loads(capturing_logs.logger.calls[0].args[0])
    assert rendered["correlation_id"] == "sess-async"
