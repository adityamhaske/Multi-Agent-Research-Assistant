"""A Celery child runs every task on one event loop, so nothing a task binds to it goes stale.

The defect this pins: each task used to open and close its own loop, while the provider SDKs
keep their HTTP client process-wide (`langchain_openai` and `langchain_anthropic` cache one
async client per base URL). The keep-alive connections pooled in that client belong to the
loop that opened them, so the next task in the same prefork child reused or expired one on
a closed loop. A gated run's plan approval — routinely handed to the child that ran its
start — died on its first model call with `RuntimeError: Event loop is closed`; before
openai 3 the SDK retried that away and sent the request twice.

**The provider test must make real HTTP calls over HTTP/1.1 keep-alive.** A fake model has
no client to cache, and an HTTP/1.0 stub closes every connection, so the pool never holds
one across the task boundary — both hide the defect entirely. And success alone is not the
assertion: on openai 2.x and on anthropic the SDK retries the stale connection and the call
*succeeds*, so the test also requires that nothing was retried and nothing sent twice.
"""

from __future__ import annotations

import asyncio
import contextvars
import json
import logging
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from app.workers import event_loop

WORKERS = Path(__file__).resolve().parents[2] / "app" / "workers"


@pytest.fixture(autouse=True)
def _fresh_worker_loop():
    event_loop.shutdown()
    yield
    event_loop.shutdown()


# ── The loop itself ─────────────────────────────────────────────────────────────────


def test_consecutive_tasks_share_one_open_loop():
    async def current():
        return asyncio.get_running_loop()

    first = event_loop.run(current())
    second = event_loop.run(current())

    assert first is second
    assert not first.is_closed()


def test_work_a_task_leaves_running_is_cancelled_before_the_next_task():
    """What the per-task loop did besides closing: nothing outlives the task that spawned it."""
    started = []

    async def leaves_a_straggler():
        async def straggler():
            started.append(True)
            await asyncio.sleep(3600)

        task = asyncio.get_running_loop().create_task(straggler())
        await asyncio.sleep(0)
        return task

    straggler = event_loop.run(leaves_a_straggler())

    assert started == [True]
    assert straggler.cancelled()


def test_a_task_that_raises_still_has_its_stragglers_cancelled():
    holder = {}

    async def fails_leaving_a_straggler():
        holder["task"] = asyncio.get_running_loop().create_task(asyncio.sleep(3600))
        await asyncio.sleep(0)
        raise ValueError("task body failed")

    with pytest.raises(ValueError, match="task body failed"):
        event_loop.run(fails_leaving_a_straggler())

    assert holder["task"].cancelled()


_bound: contextvars.ContextVar[str | None] = contextvars.ContextVar("bound", default=None)


def test_each_task_sees_the_callers_context_and_leaks_nothing_into_the_next():
    """Log identity (`bind_research_run_context`) and run config are ContextVars bound in the
    Celery task body before the coroutine runs. A runner that kept one context for every
    task would show the next run the previous run's identity."""

    async def read_then_overwrite():
        seen = _bound.get()
        _bound.set("written-inside-the-task")
        return seen

    token = _bound.set("run-a")
    try:
        assert event_loop.run(read_then_overwrite()) == "run-a"
        _bound.set("run-b")
        assert event_loop.run(read_then_overwrite()) == "run-b"
        assert _bound.get() == "run-b"
    finally:
        _bound.reset(token)


def test_an_interrupted_task_unwinds_through_its_own_cleanup(monkeypatch):
    """Celery's soft time limit raises out of the loop with the task's coroutine still pending.
    Cancelling every task at once would also cancel the event write `emit` had shielded — the
    commit cut off halfway, the very collision the fan-out fix exists to prevent. The coroutine
    is cancelled first, so cancellation arrives the structured way and the write lands."""
    from research_engine.events import emit, reset_emitter, set_emitter

    class SoftTimeLimit(KeyboardInterrupt):
        """Stands in for SoftTimeLimitExceeded: an exception escaping `run_until_complete`
        from outside any task, which only a BaseException raised in a callback can do."""

    written: list[str] = []
    unwound: list[str] = []

    async def slow_sink(_sid, event):
        await asyncio.sleep(0.1)
        written.append(event["message"])

    def time_limit():
        raise SoftTimeLimit

    async def body():
        token = set_emitter(slow_sink)
        asyncio.get_running_loop().call_later(0.02, time_limit)
        try:
            await emit("sid", "agent_log", message="in flight when the limit hit")
            await asyncio.sleep(3600)
        finally:
            reset_emitter(token)
            unwound.append("finally ran")

    with pytest.raises(SoftTimeLimit):
        event_loop.run(body())

    assert written == ["in flight when the limit hit"]
    assert unwound == ["finally ran"]


def test_a_forked_child_does_not_reuse_its_parents_loop(monkeypatch):
    async def current():
        return asyncio.get_running_loop()

    parent_loop = event_loop.run(current())
    parent_runner = event_loop._runner
    try:
        with monkeypatch.context() as child:
            child.setattr(event_loop.os, "getpid", lambda: -1)
            child_loop = event_loop.run(current())
            # Closed while the pid still reads as the child's, or shutdown() would skip it.
            event_loop.shutdown()
        assert child_loop is not parent_loop
        assert child_loop.is_closed()
    finally:
        parent_runner.close()


def test_no_worker_entry_point_opens_a_loop_of_its_own():
    """A new task written the obvious way would reintroduce the defect for its journey."""
    offenders = [
        f"{path.name}:{n}"
        for path in sorted(WORKERS.glob("*.py"))
        for n, line in enumerate(path.read_text().splitlines(), 1)
        if re.search(r"\basyncio\.run\(|\bnew_event_loop\(", line) and path.name != "event_loop.py"
    ]
    assert offenders == [], f"route these through app.workers.event_loop.run: {offenders}"


# ── Real provider clients across a task boundary ────────────────────────────────────

_OPENAI_BODY = {
    "id": "chatcmpl-stub",
    "object": "chat.completion",
    "created": 0,
    "model": "stub-model",
    "choices": [
        {"index": 0, "message": {"role": "assistant", "content": "pong"}, "finish_reason": "stop"}
    ],
    "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
}
_ANTHROPIC_BODY = {
    "id": "msg_stub",
    "type": "message",
    "role": "assistant",
    "model": "stub-model",
    "content": [{"type": "text", "text": "pong"}],
    "stop_reason": "end_turn",
    "stop_sequence": None,
    "usage": {"input_tokens": 1, "output_tokens": 1},
}
_GOOGLE_BODY = {
    "candidates": [
        {"content": {"role": "model", "parts": [{"text": "pong"}]}, "finishReason": "STOP"}
    ],
    "usageMetadata": {"promptTokenCount": 1, "candidatesTokenCount": 1, "totalTokenCount": 2},
    "modelVersion": "stub-model",
}


@pytest.fixture
def keepalive_provider():
    """A provider endpoint that keeps connections open between requests, as real ones do."""
    requests: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):
            pass

        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length") or 0))
            # Counted on arrival, before responding: counted after, the client could read the
            # reply and the test assert on the count while this thread had not yet appended.
            requests.append(self.path)
            if self.path.endswith("/chat/completions"):
                body = _OPENAI_BODY
            elif self.path.endswith("/messages"):
                body = _ANTHROPIC_BODY
            else:
                body = _GOOGLE_BODY
            raw = json.dumps(body).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}", requests
    finally:
        server.shutdown()
        server.server_close()


# Longer than the keep-alive expiry langchain_openai's pool uses (5s), which is the branch
# the production failure took: the plan was approved ~2 minutes after the start task's last
# call, and the pool closed the expired connection on the loop that had opened it.
_PAST_KEEPALIVE_EXPIRY = 5.5


@pytest.mark.parametrize("provider", ["custom", "anthropic", "google"])
@pytest.mark.parametrize("idle", [0.0, _PAST_KEEPALIVE_EXPIRY], ids=["reused", "expired"])
def test_a_provider_call_survives_the_task_boundary(
    provider, idle, keepalive_provider, monkeypatch, caplog
):
    from research_engine import llm_factory
    from research_engine.runconfig import RunConfig, reset_run_config, set_run_config

    base_url, requests = keepalive_provider
    # Only a container rewrites localhost; this test talks to a stub on this host.
    monkeypatch.setattr(llm_factory, "map_local_host", lambda url: url)
    keys = {
        "custom": {"custom": "stub-key", "custom_base_url": f"{base_url}/v1"},
        "anthropic": {"anthropic": "stub-key"},
        "google": {"google": "stub-key"},
    }[provider]
    monkeypatch.setenv("ANTHROPIC_BASE_URL", base_url)
    monkeypatch.setenv("GOOGLE_GEMINI_BASE_URL", base_url)
    token = set_run_config(
        RunConfig(
            llm_mode="real",
            models={
                role: f"{provider}:stub-model"
                for role in ("planner", "executor", "critic", "synthesizer", "chat")
            },
            provider_keys=keys,
            enforce_ssrf_guards=False,
        )
    )

    async def one_task():
        # What every node does: a fresh model from the factory, called on the task's loop.
        return (await llm_factory.get_llm("executor").ainvoke("ping")).content

    caplog.set_level(logging.INFO)
    try:
        first = event_loop.run(one_task())
        time.sleep(idle)
        second = event_loop.run(one_task())
    finally:
        reset_run_config(token)

    assert (first, second) == ("pong", "pong")
    retried = [r.getMessage() for r in caplog.records if "Retrying request" in r.getMessage()]
    assert retried == [], "the SDK retried a stale connection — the defect, masked"
    assert len(requests) == 2, f"expected one request per call, the provider saw {requests}"
