"""
The desktop host's run routes must work with no server configuration present.

AGENTS.md's recurring bug is "two hosts, one contract", and every instance so far has been
a *missing* route — a control the UI rendered and the sidecar had no handler for.
`test_host_parity` was built to catch that shape and does. This is the next shape along:
the route exists on both hosts, registration is identical, and parity is satisfied — but
invoking it on the desktop raises.

`app/config.py` builds its `Settings` at import time and requires `database_url` and
`jwt_secret_key`. The sidecar's run routes import their handlers from `app.api.v1.runs`
rather than restating them, and that module reaches `app.config` through `app.db.base`, so
absent those two variables every run route answers 500 on its first request.

What let it reach a release build is that nothing in the test environment resembles an
installed app: `conftest.py` sets both variables via `setdefault` and `ci.yml` exports them
as job env, so the entire suite runs with server configuration the desktop never has. This
is AGENTS.md's "a test that stubs the thing it is testing proves nothing" one level out —
the fixtures replaced nothing, but the *environment* supplied precisely what was missing.

So the assertion has to be made from a process that does not inherit it, which is why this
runs a subprocess rather than a fixture. Two things are scrubbed, not one: the variables
themselves, and the working directory — `Settings` reads `env_file="../.env"` relative to
cwd, so a test run from `backend/` on a contributor's machine with a populated repo-root
`.env` would otherwise pass without the fix, which is the decorative-test failure mode.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[2]

# Probed against a run id that does not exist, so a handler that imports and executes
# answers 404. Any 500 here is the import failing, not the query.
MISSING_RUN = "00000000-0000-0000-0000-000000000000"

# One route per distinct handler import in `create_sidecar_app`'s run block. `GET /runs`
# is the cheapest positive: it lists an empty table, so a working import answers 200.
PROBES = [
    ("/api/v1/runs", 200),
    (f"/api/v1/runs/{MISSING_RUN}", 404),
    (f"/api/v1/runs/{MISSING_RUN}/bundle.json", 404),
    (f"/api/v1/runs/{MISSING_RUN}/verification", 404),
    (f"/api/v1/runs/{MISSING_RUN}/export.md", 404),
]

# A template rather than an f-string or `.format` target: the body is mostly dict and set
# literals, and brace-escaping them is a source of bugs in the test itself.
_CHILD = """
import asyncio, json, os, sys

# Proves the scrub reached the child. If either name is present the run below would pass
# for the same reason the whole suite did, so this is an assertion and not a log line.
leaked = [n for n in ("DATABASE_URL", "JWT_SECRET_KEY") if n in os.environ]
if leaked:
    print(json.dumps({"error": "server config leaked into the child: " + repr(leaked)}))
    raise SystemExit(0)

sys.path.insert(0, __BACKEND__)

import httpx
from desktop.sidecar import create_sidecar_app

TOKEN = "desktop-v2-env-probe"


async def main():
    app = create_sidecar_app(data_dir=__DATA_DIR__, token=TOKEN, fake=True)
    async with app.router.lifespan_context(app):
        # `raise_app_exceptions=False` so a handler that raises is recorded as the 500 a
        # real client receives, rather than crashing the child. The point of the test is
        # what the shipped app answers, and a crash here would bypass the assertions.
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:9") as c:
            out = {}
            for path in __PATHS__:
                r = await c.get(path, headers={"Authorization": "Bearer " + TOKEN})
                out[path] = [r.status_code, r.text[:200]]
            print(json.dumps({"results": out}))


asyncio.run(main())
"""


@pytest.fixture(scope="module")
def probe_results(tmp_path_factory) -> dict:
    """Boot the sidecar in a child with no server config and probe its run routes."""
    data_dir = tmp_path_factory.mktemp("desktop-data")
    # cwd is deliberately *not* `backend/`: it is what `env_file="../.env"` resolves
    # against, and a real repo checkout has one.
    cwd = tmp_path_factory.mktemp("scrubbed-cwd")

    env = {k: v for k, v in os.environ.items() if k not in ("DATABASE_URL", "JWT_SECRET_KEY")}

    script = (
        _CHILD.replace("__BACKEND__", repr(str(BACKEND)))
        .replace("__DATA_DIR__", repr(str(data_dir)))
        .replace("__PATHS__", repr([p for p, _ in PROBES]))
    )
    proc = subprocess.run(
        [sys.executable, "-c", script],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert proc.returncode == 0, f"child failed:\nstdout={proc.stdout}\nstderr={proc.stderr}"
    payload = json.loads(proc.stdout.strip().splitlines()[-1])
    assert "error" not in payload, payload["error"]
    return payload["results"]


@pytest.mark.parametrize(("path", "expected"), PROBES)
def test_a_v2_route_answers_without_server_configuration(path, expected, probe_results):
    status, body = probe_results[path]
    assert status != 500, (
        f"{path} raised on the desktop host with no server config — this is what the "
        f"shipped app does on every run request. Body: {body}"
    )
    assert status == expected, f"{path} -> {status}, expected {expected}. Body: {body}"


def _drive(fake_app_dir, *, skip_plan_gate: bool):
    """Create a scripted run on the desktop host and drive it through its gates.

    Returns the run's terminal projection. Scripted (`fake=True`) throughout: this is the
    offline verification path, so it must work with no provider, no key and no network.
    """
    import asyncio

    import httpx

    from desktop.sidecar import create_sidecar_app

    async def poll(client, head, run_id, wanted, *, timeout=60.0):
        """Wait for the in-process driver to reach a status.

        The driver is an `asyncio.Task` on this same loop, so yielding is what lets it run;
        a bare sleep-free loop would spin without ever handing it control.
        """
        deadline = asyncio.get_running_loop().time() + timeout
        last = None
        while asyncio.get_running_loop().time() < deadline:
            r = await client.get(f"/api/v1/runs/{run_id}", headers=head)
            last = r.json()["run"]["status"] if r.status_code == 200 else f"HTTP {r.status_code}"
            if last in wanted:
                return last
            await asyncio.sleep(0.05)
        raise AssertionError(f"run never reached {wanted}; last status was {last!r}")

    async def go(tmp):
        app = create_sidecar_app(data_dir=tmp, token="tok", fake=True)
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
            async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:9") as c:
                head = {"Authorization": "Bearer tok"}
                pid = (await c.post("/api/v1/projects", json={"name": "p"}, headers=head)).json()[
                    "id"
                ]
                created = await c.post(
                    "/api/v1/runs",
                    json={
                        "question": "What is retrieval-augmented generation?",
                        "depth": "fast",
                        "project_id": pid,
                        "skip_plan_gate": skip_plan_gate,
                        "dispatch": True,
                    },
                    headers=head,
                )
                assert created.status_code == 201, (
                    f"create failed: {created.status_code} {created.text[:300]}"
                )
                run_id = created.json()["run_id"]

                if not skip_plan_gate:
                    await poll(c, head, run_id, {"AWAITING_PLAN"})
                    approved = await c.post(
                        f"/api/v1/runs/{run_id}/plan-review",
                        json={"decision": "APPROVED"},
                        headers=head,
                    )
                    assert approved.status_code == 201, approved.text[:300]

                await poll(c, head, run_id, {"AWAITING_REVIEW"})
                approved = await c.post(
                    f"/api/v1/runs/{run_id}/report-review",
                    json={"decision": "APPROVED"},
                    headers=head,
                )
                assert approved.status_code == 201, approved.text[:300]

                final = (await c.get(f"/api/v1/runs/{run_id}", headers=head)).json()
                exports = {}
                for suffix in ("export.md", "bundle.json"):
                    r = await c.get(f"/api/v1/runs/{run_id}/{suffix}", headers=head)
                    exports[suffix] = (r.status_code, r.text)
                return final, exports

    return asyncio.run(go(fake_app_dir))


def test_the_desktop_host_starts_and_completes_a_research_run_in_process():
    """The packaged app's primary control has to work on the host that ships it.

    This previously asserted the opposite — that dispatch answered 501 — because executing a
    run meant Redis, Postgres and a Celery worker the desktop has none of. That made
    "Start research", the one action the product is named after, a button that could not
    work in the packaged app; the desktop UI calls `POST /runs` and always has.

    The fix is a different *mechanism*, not a different contract: the same engine, the same
    shared handlers, driven by an asyncio task against this host's SQLite saver. So the
    assertion is the whole journey rather than a status code — created, driven to the review
    gate, approved, completed, with an artifact and a bundle at the end.
    """
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        final, exports = _drive(tmp, skip_plan_gate=True)

    assert final["run"]["status"] == "COMPLETED", final["run"]
    # An approval that produced no artifact is not an approval this product recognises.
    assert final["artifact"] is not None, "approval recorded no artifact"
    # Scripted models mean the row must say so, whatever the request asked for — the
    # fourth home of that rule now that the desktop drives research runs too.
    assert final["run"]["demo"] is True, "a scripted run must be recorded as a demo run"

    md_status, md_body = exports["export.md"]
    assert md_status == 200, f"markdown export failed: {md_status}"
    bundle_status, bundle_body = exports["bundle.json"]
    assert bundle_status == 200, f"bundle export failed: {bundle_status}"
    assert bundle_body.strip(), "bundle export was empty"


def test_the_desktop_host_pauses_at_the_design_gate_and_resumes_after_approval():
    """Both gates, not just the last one.

    The plan gate resumes through a different dispatcher operation than a fresh start, and
    a driver that wires only the start path leaves a run suspended forever with the UI
    showing "Running" — the failure this exercises rather than reasons about.
    """
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        final, _ = _drive(tmp, skip_plan_gate=False)

    assert final["run"]["status"] == "COMPLETED", final["run"]
    assert final["artifact"] is not None


# The child that proves the export path survives the bundle's own exclude list.
#
# `_drive` above runs from a source checkout, where `celery` and `redis` are installed, so
# it cannot see a function-level import of a server-only module — and one shipped: the
# Markdown export reached `_DEMO_STAMP` through `app.api.v1.research`, which imports
# `app.workers.tasks` at module scope, so every `.md` export on the packaged app answered
# 500 with `ModuleNotFoundError: No module named 'celery'`. It was unreachable until the
# desktop could complete a run, which is exactly how a latent break ships.
#
# `test_lazy_v2_imports_pull_in_no_excluded_package` walks *module-level* imports and is
# blind to this by construction. Blocking the packages and then exercising the route is
# what closes that gap without building a 1.7 GB bundle to do it.
_BLOCKED_CHILD = """
import asyncio, importlib.abc, importlib.machinery, json, sys, tempfile

BLOCKED = __BLOCKED__


class _Blocker(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".")[0] in BLOCKED:
            raise ModuleNotFoundError("No module named " + repr(fullname))
        return None


sys.meta_path.insert(0, _Blocker())
sys.path.insert(0, __BACKEND__)

import httpx
from desktop.sidecar import create_sidecar_app

TOKEN = "blocked-probe"


async def poll(c, head, run_id, wanted, timeout=90.0):
    deadline = asyncio.get_running_loop().time() + timeout
    last = None
    while asyncio.get_running_loop().time() < deadline:
        r = await c.get("/api/v1/runs/" + run_id, headers=head)
        last = r.json()["run"]["status"] if r.status_code == 200 else "HTTP %d" % r.status_code
        if last in wanted:
            return last
        await asyncio.sleep(0.05)
    raise AssertionError("never reached %r, last=%r" % (wanted, last))


async def main():
    app = create_sidecar_app(data_dir=tempfile.mkdtemp(), token=TOKEN, fake=True)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:9") as c:
            head = {"Authorization": "Bearer " + TOKEN}
            pid = (await c.post("/api/v1/projects", json={"name": "p"}, headers=head)).json()["id"]
            created = await c.post(
                "/api/v1/runs",
                json={"question": "q about RAG", "depth": "fast", "project_id": pid,
                      "skip_plan_gate": True, "dispatch": True},
                headers=head,
            )
            run_id = created.json()["run_id"]
            await poll(c, head, run_id, {"AWAITING_REVIEW"})
            await c.post("/api/v1/runs/" + run_id + "/report-review",
                         json={"decision": "APPROVED"}, headers=head)
            out = {"create": created.status_code}
            for suffix in ("export.md", "bundle.json"):
                r = await c.get("/api/v1/runs/" + run_id + "/" + suffix, headers=head)
                out[suffix] = [r.status_code, r.text[:300]]
            print(json.dumps(out))


asyncio.run(main())
"""


def test_the_export_path_works_with_the_bundle_s_excluded_packages_unavailable():
    """A desktop export must not import a package the bundle refuses to ship.

    The spec excludes celery/redis/asyncpg because this host speaks SQLite and drives its
    own runs. Anything the sidecar imports *at request time* has to fit inside that, and a
    function-level import is the shape that escapes every static check.
    """
    # Read from the spec itself, via the module that already parses it — a second copy
    # of the exclude list is a second thing to forget. WeasyPrint is left available:
    # its own guard covers it, and PDF export is a documented 501 on this host anyway.
    from tests.workflow.test_sidecar_startup import _spec_excludes

    blocked = [n for n in _spec_excludes() if n != "weasyprint"]
    script = _BLOCKED_CHILD.replace("__BACKEND__", repr(str(BACKEND))).replace(
        "__BLOCKED__", repr(set(blocked))
    )
    env = {k: v for k, v in os.environ.items() if k not in ("DATABASE_URL", "JWT_SECRET_KEY")}
    proc = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(BACKEND),
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert proc.returncode == 0, (
        f"child failed:\nstdout={proc.stdout}\nstderr={proc.stderr[-3000:]}"
    )
    out = json.loads(proc.stdout.strip().splitlines()[-1])

    assert out["create"] == 201, out
    md_status, md_body = out["export.md"]
    assert md_status == 200, (
        f"Markdown export answered {md_status} with the bundle's excluded packages "
        f"unavailable — this is what the packaged app does. Body: {md_body}"
    )
    bundle_status, _ = out["bundle.json"]
    assert bundle_status == 200, f"bundle export answered {bundle_status}"
