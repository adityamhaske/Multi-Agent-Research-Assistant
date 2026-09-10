"""
A research run is joinable end to end, and its id never masquerades as a session id.

Two pipelines exist in this backend and only one is the product (`AGENTS.md`). Until now
the correlation helper had a single entry point that wrote `session_id=<whatever it was
given>`, and the three *run* Celery tasks called it with a `research_runs.id` — so every
server-side run log claimed a session that did not exist. That is the identifier collapse
this file exists to prevent, and `test_a_run_id_never_appears_as_a_session_id` is the
assertion that keeps it prevented.

**What is proved where.** Correlation has three links and each is asserted against the real
thing rather than a stand-in:

1. *Binding rides logs* — `bind_research_run_context` then a real `structlog` render, over
   the real configured processor chain, including across `asyncio.run` and `create_task`.
2. *Every run route binds* — all fourteen operations driven over HTTP against **both**
   hosts, observed through a recorder that wraps (and still calls) the real
   `structlog.contextvars.bind_contextvars`.
3. *Both drivers bind* — `run_execution.execute_run` and the sidecar's in-process driver,
   each entered for real.

**Why the route test observes bindings rather than log lines.** A fake-mode run emits no
engine log at all (verified: zero records), and most run routes log nothing of their own, so
asserting over captured output would assert over an empty list — the degenerate pass this
repository refuses. What a route can be held to is that it *bound the identity*, which is
exactly what makes any later log line carry it; link 1 above is what proves that second
half, separately and for real.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import uuid

import pytest
import structlog
from structlog.testing import CapturingLoggerFactory

from app.logconfig import (
    bind_research_run_context,
    bind_session_context,
    clear_run_context,
    configure_logging,
)

RUN_ID = "11111111-2222-3333-4444-555555555555"
SESSION_ID = "99999999-8888-7777-6666-555555555555"


@pytest.fixture()
def rendered():
    """The real configuration, capturing what a log line would actually carry."""
    configure_logging(json_output=True)
    factory = CapturingLoggerFactory()
    structlog.configure(logger_factory=factory, processors=structlog.get_config()["processors"])
    clear_run_context()
    yield lambda index=0: json.loads(factory.logger.calls[index].args[0])
    structlog.reset_defaults()
    clear_run_context()


# ── 1. The binders are semantically distinct ──────────────────────────────────────


def test_a_run_id_never_appears_as_a_session_id(rendered):
    """The defect this work exists to end: `research_runs.id` under the key `session_id`."""
    bind_research_run_context(RUN_ID, user_id="u-1")

    structlog.get_logger().info("run_started")

    line = rendered()
    assert line["run_id"] == RUN_ID
    assert line["correlation_id"] == RUN_ID
    assert "session_id" not in line, "a run id was logged as a session id"
    assert line["user_id"] == "u-1"


def test_a_session_id_never_appears_as_a_run_id(rendered):
    bind_session_context(SESSION_ID, user_id="u-1")

    structlog.get_logger().info("research_started")

    line = rendered()
    assert line["session_id"] == SESSION_ID
    assert line["correlation_id"] == SESSION_ID
    assert "run_id" not in line


def test_the_session_binder_is_unchanged(rendered):
    """`bind_session_context` is the old `bind_run_context` renamed, and the rename must be
    the whole of the change — the session surface's correlation is not part of this work."""
    bind_session_context(SESSION_ID)

    structlog.get_logger().info("x")

    line = rendered()
    assert line["correlation_id"] == line["session_id"] == SESSION_ID


def test_one_correlation_id_per_context(rendered):
    """Binding a run after a session replaces the identity rather than accumulating two."""
    bind_session_context(SESSION_ID)
    clear_run_context()
    bind_research_run_context(RUN_ID)

    structlog.get_logger().info("x")

    line = rendered()
    assert line["correlation_id"] == RUN_ID
    assert "session_id" not in line


def test_clearing_stops_a_run_identity_leaking(rendered):
    bind_research_run_context(RUN_ID)
    clear_run_context()

    structlog.get_logger().info("unrelated")

    line = rendered()
    assert "correlation_id" not in line
    assert "run_id" not in line


def test_a_run_identity_survives_asyncio_run(rendered):
    """Both drivers hand the engine to the event loop; `asyncio` copies the current context,
    so a binding taken before that hop has to arrive on the other side of it."""
    bind_research_run_context(RUN_ID)

    async def inner():
        structlog.get_logger().warning("executor_budget_stop")

    asyncio.run(inner())

    assert rendered()["run_id"] == RUN_ID


async def test_two_concurrent_runs_do_not_cross(rendered):
    """The desktop drives runs as `asyncio.Task`s in one process. A task gets a *copy* of
    the context, so binding inside the task keeps two runs apart — which is why the sidecar
    binds inside `_drive_run` and not before `create_task`."""
    seen: dict[str, str] = {}

    async def drive(run_id: str) -> None:
        bind_research_run_context(run_id)
        await asyncio.sleep(0)
        seen[run_id] = structlog.contextvars.get_contextvars()["run_id"]

    await asyncio.gather(drive("run-a"), drive("run-b"))

    assert seen == {"run-a": "run-a", "run-b": "run-b"}
    assert "run_id" not in structlog.contextvars.get_contextvars(), (
        "a task's binding escaped into its parent"
    )


# ── 2. Every run route binds, on both hosts ───────────────────────────────────────


class _BindRecorder:
    """Wraps the real `bind_contextvars` and records the context it produced.

    An observer, not a substitute: the real call still happens, and what is recorded is the
    resulting context rather than the arguments — the same thing `merge_contextvars` would
    put on a log line.
    """

    def __init__(self, monkeypatch):
        self.bindings: list[dict] = []
        real = structlog.contextvars.bind_contextvars

        def recording(**kw):
            token = real(**kw)
            self.bindings.append(dict(structlog.contextvars.get_contextvars()))
            return token

        monkeypatch.setattr(structlog.contextvars, "bind_contextvars", recording)

    def run_ids(self) -> list[str]:
        return [b["run_id"] for b in self.bindings if "run_id" in b]

    def session_ids(self) -> list[str]:
        return [b["session_id"] for b in self.bindings if "session_id" in b]

    def clear(self) -> None:
        self.bindings.clear()


#: Every run operation, in an order that leaves the run reachable until the last one.
#: A route that refuses (no plan yet, no revision yet, cancelled) still binds first — the
#: identity is established when ownership resolves, before any product rule runs.
def _route_calls(run_id: str) -> list[tuple[str, str, str, dict]]:
    return [
        ("get the run", "GET", f"/runs/{run_id}", {}),
        ("list runs", "GET", "/runs", {}),
        ("plan review", "POST", f"/runs/{run_id}/plan-review", {"json": {"decision": "APPROVED"}}),
        (
            "report review",
            "POST",
            f"/runs/{run_id}/report-review",
            {"json": {"decision": "APPROVED"}},
        ),
        ("bundle", "GET", f"/runs/{run_id}/bundle.json", {}),
        ("verification", "GET", f"/runs/{run_id}/verification", {}),
        ("export markdown", "GET", f"/runs/{run_id}/export.md", {}),
        ("export pdf", "GET", f"/runs/{run_id}/export.pdf", {}),
        ("cancel", "POST", f"/runs/{run_id}/cancel", {}),
        ("archive", "POST", f"/runs/{run_id}/archive", {}),
        ("unarchive", "POST", f"/runs/{run_id}/unarchive", {}),
        ("delete", "DELETE", f"/runs/{run_id}", {}),
    ]


#: `GET /runs` names no run, so there is nothing to bind — recorded rather than silently
#: skipped, so that a future route which *should* bind cannot join it by accident.
BINDS_NOTHING = {"list runs"}

#: The desktop answers `export.pdf` with a bare 501 before any run is resolved, so it has
#: no run identity to bind. That exemption is only legitimate because the difference is a
#: *declared capability* rather than a gap — `test_the_desktop_pdf_501_is_a_declared_capability`
#: is what holds it to that, and correlation plumbing is deliberately NOT added to a route
#: that performs no run operation.
DESKTOP_BINDS_NOTHING = BINDS_NOTHING | {"export pdf"}

#: The server's stream route declares `get_redis` as a dependency, and this harness runs
#: the server on SQLite with no Redis — so FastAPI fails dependency resolution before the
#: handler runs, and nothing in the product is being observed. A harness limit, not a gap,
#: which is why the parity journeys do not drive this route on the server either. What
#: covers it: both hosts' stream handlers resolve ownership through the **same**
#: `app.api.v1.runs._run_or_404` (`desktop/sidecar.py::v2_stream_run` imports it), the
#: desktop half of this very test drives that route and sees the binding, and eleven other
#: server routes here prove the same helper binds on the server.
SERVER_BINDS_NOTHING = BINDS_NOTHING | {"stream"}


def test_the_desktop_pdf_501_is_a_declared_capability():
    """Grounds the exemption above in the contract, not in a comment.

    Three things have to be true together, or `export pdf` belongs in the bound set: the
    route exists on both hosts (so it is not a parity gap), the frontend calls it on both
    (so its absence would reach a user), and the host says in `GET /capabilities` that it
    cannot render one. `desktop/sidecar.py`'s route raises before touching a run, which is
    why there is no identity to correlate — the request performs no run operation."""
    from app.schemas.capabilities import DESKTOP, SERVER
    from tests.workflow.test_host_parity import (
        DESKTOP_UI_CALLS,
        INTENTIONAL_SERVER_ONLY,
        KNOWN_DESKTOP_GAPS,
    )

    operation = "GET /runs/{run_id}/export.pdf"
    assert operation in DESKTOP_UI_CALLS
    assert operation not in INTENTIONAL_SERVER_ONLY, "the route exists on both hosts"
    assert operation not in KNOWN_DESKTOP_GAPS, "a 501 with a reason is not a shipped gap"
    assert SERVER.server_pdf is True
    assert DESKTOP.server_pdf is False


async def _create_run(driver) -> str:
    project = await driver.request("POST", "/projects", json={"name": f"corr-{uuid.uuid4().hex}"})
    assert project.status_code in (200, 201), project.text
    created = await driver.request(
        "POST",
        "/runs",
        json={
            "project_id": project.json()["id"],
            "question": "Does every run route carry its correlation identity?",
            "depth": "fast",
            "dispatch": False,
        },
    )
    assert created.status_code == 201, created.text
    return created.json()["run_id"]


async def _drive_every_run_route(driver, recorder: _BindRecorder, *, binds_nothing: set[str]):
    run_id = await _create_run(driver)
    assert recorder.run_ids() == [run_id], (
        "POST /runs must bind the identity of the run it just created"
    )

    # The SSE route, driven first while the run is still live, and abandoned rather than
    # read. `httpx.ASGITransport` runs an ASGI app to completion before returning, so it
    # cannot stream: a request to this route never returns until the stream ends, which for
    # a live run means never. The bound below is on the harness, not on the assertion — the
    # identity is established in `_run_or_404`, before the `StreamingResponse` is even
    # constructed, so what `recorder` holds afterwards does not depend on timing.
    recorder.clear()
    # Tolerated, not swallowed: a host whose stream declares infrastructure this harness
    # does not provide raises during dependency resolution, before the handler runs. The
    # per-host `binds_nothing` declaration is what decides whether that is acceptable —
    # a host expected to bind here and raising instead still fails below, with an empty
    # `bound["stream"]`.
    with contextlib.suppress(Exception):  # the timeout below raises here too
        async with asyncio.timeout(5):
            async with driver.client.stream("GET", f"/api/v1/runs/{run_id}/stream"):
                pass
    bound: dict[str, list[str]] = {"stream": recorder.run_ids()}

    for name, method, path, kwargs in _route_calls(run_id):
        recorder.clear()
        await driver.request(method, path, **kwargs)
        bound[name] = recorder.run_ids()

    return run_id, bound


async def _assert_every_route_bound(run_id, bound, *, binds_nothing, host):
    missing = [name for name, ids in bound.items() if name not in binds_nothing and not ids]
    assert not missing, f"{host}: these run routes established no correlation identity: {missing}"

    wrong = {name: ids for name, ids in bound.items() if ids and set(ids) != {run_id}}
    assert not wrong, f"{host}: routes bound the wrong run id: {wrong}"

    unexpected = [name for name in binds_nothing if bound.get(name)]
    assert not unexpected, (
        f"{host}: {unexpected} bound a run identity, but is declared as binding none — "
        "either the declaration is stale or the route changed"
    )


async def test_every_run_route_binds_its_run__server(tmp_path, monkeypatch):
    from tests.parity.drivers import server_driver

    recorder = _BindRecorder(monkeypatch)
    async with server_driver(tmp_path / "server") as driver:
        run_id, bound = await _drive_every_run_route(
            driver, recorder, binds_nothing=SERVER_BINDS_NOTHING
        )
    await _assert_every_route_bound(
        run_id, bound, binds_nothing=SERVER_BINDS_NOTHING, host="server"
    )


async def test_every_run_route_binds_its_run__desktop(tmp_path, monkeypatch):
    from tests.parity.drivers import desktop_driver

    recorder = _BindRecorder(monkeypatch)
    async with desktop_driver(tmp_path / "desktop") as driver:
        run_id, bound = await _drive_every_run_route(
            driver, recorder, binds_nothing=DESKTOP_BINDS_NOTHING
        )
    await _assert_every_route_bound(
        run_id, bound, binds_nothing=DESKTOP_BINDS_NOTHING, host="desktop"
    )


async def test_no_run_route_binds_a_session_id__desktop(tmp_path, monkeypatch):
    """The parity half of the invariant: neither host may file a run under `session_id`."""
    from tests.parity.drivers import desktop_driver

    recorder = _BindRecorder(monkeypatch)
    async with desktop_driver(tmp_path / "desktop-sessions") as driver:
        await _drive_every_run_route(driver, recorder, binds_nothing=DESKTOP_BINDS_NOTHING)

    assert recorder.session_ids() == []


# ── 3. Both drivers bind ──────────────────────────────────────────────────────────


async def test_the_server_driver_binds_before_it_touches_anything(monkeypatch):
    """`execute_run` binds at entry — before the Redis pool, the lock and the row lookup —
    so that everything it logs on the way, including the failures, carries the run."""
    from app import run_execution
    from app.db import redis as redis_module

    recorder = _BindRecorder(monkeypatch)
    run_id = str(uuid.uuid4())

    class _Stop(Exception):
        pass

    async def _boom() -> None:
        raise _Stop

    async def _noop() -> None:
        return None

    monkeypatch.setattr(redis_module, "init_redis_pool", _boom)
    monkeypatch.setattr(redis_module, "close_redis_pool", _noop)

    with pytest.raises(_Stop):
        await run_execution.execute_run(run_id)

    assert recorder.run_ids() == [run_id]
    assert recorder.session_ids() == []


async def test_the_desktop_driver_binds_inside_its_own_task(tmp_path, monkeypatch):
    """A dispatched desktop run binds its identity in the task that drives it."""
    from tests.parity.drivers import desktop_driver

    recorder = _BindRecorder(monkeypatch)
    async with desktop_driver(tmp_path / "desktop-driver") as driver:
        project = await driver.request("POST", "/projects", json={"name": "driver"})
        created = await driver.request(
            "POST",
            "/runs",
            json={
                "project_id": project.json()["id"],
                "question": "Does the desktop driver bind its run?",
                "depth": "fast",
                "dispatch": True,
            },
        )
        run_id = created.json()["run_id"]
        for _ in range(200):
            await asyncio.sleep(0.05)
            status = (await driver.request("GET", f"/runs/{run_id}")).json()["run"]["status"]
            if status != "PENDING":
                break

    assert run_id in recorder.run_ids(), "the desktop driver never bound the run it drove"
    assert recorder.session_ids() == []


# ── 4. The Celery entry points ────────────────────────────────────────────────────


def test_the_run_tasks_bind_a_run_and_not_a_session(monkeypatch):
    """The three run tasks are where the collapse actually shipped.

    Synchronous, because a Celery task is: it calls `asyncio.run` itself, which refuses to
    nest inside a running loop."""
    from app import run_execution
    from app.workers import tasks

    recorder = _BindRecorder(monkeypatch)
    run_id, user_id = str(uuid.uuid4()), str(uuid.uuid4())

    async def _noop(*_a, **_kw) -> None:
        return None

    monkeypatch.setattr(run_execution, "execute_run", _noop)

    tasks.run_research_pipeline(run_id, user_id)
    tasks.resume_research_pipeline(run_id, user_id, True, None)
    tasks.resume_research_plan_gate(run_id, user_id, {"tasks": []})

    assert recorder.run_ids() == [run_id, run_id, run_id]
    assert recorder.session_ids() == [], "a run task filed its run under session_id"


def test_the_session_tasks_still_bind_a_session(monkeypatch):
    """The other half of the split: sessions keep the semantics they had.

    The pipeline itself is replaced rather than `asyncio.run`, which is shared global
    machinery this test has no business reaching into."""
    from app.workers import pipeline_runner, tasks

    recorder = _BindRecorder(monkeypatch)
    session_id = str(uuid.uuid4())

    async def _noop(*_a, **_kw) -> None:
        return None

    monkeypatch.setattr(pipeline_runner, "run_pipeline", _noop)

    tasks.run_agent_pipeline(session_id, "u-1")

    assert recorder.session_ids() == [session_id]
    assert recorder.run_ids() == []


# ── 5. The invariant, held over real log output ───────────────────────────────────


#: Every `logger.*()` call that passes a `session_id=` keyword, by the function it sits in.
#: All of them are on the session pipeline, where the field means what it says. A new entry
#: is a claim that the value there can only ever be a `sessions.id` — if it can also be a
#: `research_runs.id`, the field is wrong and the fix is a neutral name, not a new row.
SESSION_ONLY_LOG_SITES: dict[tuple[str, str], str] = {
    ("app/api/v1/projects.py", "delete_project"): "iterates `session_ids`; runs are `v2_run_ids`",
    ("app/api/v1/research.py", "start_research"): "the session router",
    ("app/api/v1/research.py", "submit_plan"): "the session router",
    ("app/api/v1/research.py", "approve_or_rework"): "the session router",
    ("app/api/v1/research.py", "cancel_session"): "the session router",
    ("app/api/v1/research.py", "delete_session"): "the session router",
    ("app/workers/pipeline_runner.py", "_execute"): "the session worker",
    ("app/workers/pipeline_runner.py", "_persist_outcome"): "the session worker",
    ("app/workers/pipeline_runner.py", "_ingest_into_project_memory"): "the session worker",
    ("app/workers/pipeline_runner.py", "_ingest_report_into_corpus"): "the session worker",
    ("desktop/sidecar.py", "lifespan"): "seeds a demo *session*",
    ("desktop/sidecar.py", "_drive_session"): "the desktop session driver",
    ("desktop/sidecar.py", "gen"): "report chat, which exists only on sessions",
}


def _log_sites_passing_session_id() -> dict[tuple[str, str], list[int]]:
    """`(file, enclosing function) → line numbers`, for every log call naming `session_id`."""
    import ast
    from pathlib import Path

    backend = Path(__file__).resolve().parents[2]
    found: dict[tuple[str, str], list[int]] = {}
    files = sorted(backend.glob("app/**/*.py")) + [backend / "desktop" / "sidecar.py"]
    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        parents = {c: n for n in ast.walk(tree) for c in ast.iter_child_nodes(n)}
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not ast.unparse(node.func).startswith("logger."):
                continue
            if not any(k.arg == "session_id" for k in node.keywords):
                continue
            cur, name = node, "<module>"
            while cur in parents:
                cur = parents[cur]
                if isinstance(cur, ast.AsyncFunctionDef | ast.FunctionDef):
                    name = cur.name
                    break
            key = (str(path.relative_to(backend)), name)
            found.setdefault(key, []).append(node.lineno)
    return found


def test_no_undeclared_code_path_logs_a_session_id():
    """`session_id` in a log line is a promise that the value is a `sessions.id`.

    Two places broke that promise and both are fixed: `report_corpus.ingest_report` logged
    an approved *run* under `session_id`, and the desktop's `PersistingSink` — which serves
    both drivers — did the same on a persistence failure. This is the guard that stops a
    third: a new `session_id=` log field fails here until someone states, in the table
    above, why that field can only ever hold a session's id."""
    undeclared = {
        k: v for k, v in _log_sites_passing_session_id().items() if k not in SESSION_ONLY_LOG_SITES
    }
    assert not undeclared, (
        "These log calls pass `session_id=` and are not declared session-only:\n  "
        + "\n  ".join(f"{f}::{fn} lines {lines}" for (f, fn), lines in sorted(undeclared.items()))
        + "\n\nIf the value can be a `research_runs.id`, rename the field. If it cannot, "
        "add it to SESSION_ONLY_LOG_SITES with the reason."
    )


def test_the_session_only_log_table_has_not_gone_stale():
    """The other direction: an entry that no longer describes any code is an entry nobody
    will notice is wrong — the same anti-rot rule the parity tables carry."""
    live = set(_log_sites_passing_session_id())
    stale = set(SESSION_ONLY_LOG_SITES) - live
    assert not stale, f"no longer log a session_id — remove from the table: {sorted(stale)}"


@pytest.mark.parametrize("host", ["server", "desktop"])
async def test_an_approved_run_reports_its_auto_ingest_without_claiming_a_session(
    tmp_path, host, monkeypatch
):
    """The fixed path, driven for real on both hosts.

    Approving a run auto-saves the report into the project corpus, and that call used to
    log `report_auto_ingested session_id=<a research_runs.id>` — a session that does not
    exist, in the one field a reader uses to tell the two pipelines apart. The parameter is
    polymorphic (a session's id or a run's), so it is `report_id` now, the way
    `app/services/memory.py::ingest_report` already names the same thing.

    The module's own logger is captured rather than the process's: `structlog.get_logger()`
    at import time binds and caches on first use, so a module logger already used earlier in
    the session ignores a later factory swap — a global capture here would silently record
    nothing and the test would pass by proving nothing."""
    from structlog.testing import CapturingLogger

    from app.services import report_corpus
    from tests.parity.drivers import desktop_driver, server_driver
    from tests.workflow.test_metrics_recording import _run_to_approval

    captured = CapturingLogger()
    monkeypatch.setattr(report_corpus, "logger", captured)

    driver_for = {"server": server_driver, "desktop": desktop_driver}[host]
    async with driver_for(tmp_path / f"{host}-invariant") as driver:
        run_id = (await _run_to_approval(driver))["run_id"]
        approved = await driver.request(
            "POST", f"/runs/{run_id}/report-review", json={"decision": "APPROVED"}
        )
        assert approved.status_code == 201, approved.text

    events = [call.kwargs | {"event": call.args[0]} for call in captured.calls]
    assert events, "the approval did not auto-ingest — the path under test never ran"

    ingested = [e for e in events if e["event"] == "report_auto_ingested"]
    assert ingested, f"{host}: no report was ingested; captured {events}"
    assert ingested[0]["report_id"] == run_id
    assert not [e for e in events if e.get("session_id") == run_id], (
        f"{host}: a research run id was logged under `session_id`: {events}"
    )


def test_the_polymorphic_ingest_parameter_is_not_named_for_one_pipeline():
    """`ingest_report` serves both pipelines from one function, so its id parameter cannot
    be named after either. The rename is the whole fix — the *value* is unchanged, so the
    filename it keys (`report-<id>.md`) and every document already stored are untouched."""
    import inspect

    from app.services.report_corpus import ingest_report

    params = inspect.signature(ingest_report).parameters
    assert "report_id" in params
    assert "session_id" not in params
