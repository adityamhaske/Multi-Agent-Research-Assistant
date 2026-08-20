"""
The desktop host's V2 routes must work with no server configuration present.

AGENTS.md's recurring bug is "two hosts, one contract", and every instance so far has been
a *missing* route — a control the UI rendered and the sidecar had no handler for.
`test_host_parity` was built to catch that shape and does. This is the next shape along:
the route exists on both hosts, registration is identical, and parity is satisfied — but
invoking it on the desktop raises.

`app/config.py` builds its `Settings` at import time and requires `database_url` and
`jwt_secret_key`. The sidecar's V2 routes import their handlers from `app.api.v1.v2_runs`
rather than restating them, and that module reaches `app.config` through `app.db.base`, so
absent those two variables every V2 route answers 500 on its first request.

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

BACKEND = Path(__file__).resolve().parents[1]

# Probed against a run id that does not exist, so a handler that imports and executes
# answers 404. Any 500 here is the import failing, not the query.
MISSING_RUN = "00000000-0000-0000-0000-000000000000"

# One route per distinct handler import in `create_sidecar_app`'s V2 block. `GET /v2/runs`
# is the cheapest positive: it lists an empty table, so a working import answers 200.
PROBES = [
    ("/api/v1/v2/runs", 200),
    (f"/api/v1/v2/runs/{MISSING_RUN}", 404),
    (f"/api/v1/v2/runs/{MISSING_RUN}/bundle.json", 404),
    (f"/api/v1/v2/runs/{MISSING_RUN}/verification", 404),
    (f"/api/v1/v2/runs/{MISSING_RUN}/export.md", 404),
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
    """Boot the sidecar in a child with no server config and probe its V2 routes."""
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
        f"shipped app does on every V2 request. Body: {body}"
    )
    assert status == expected, f"{path} -> {status}, expected {expected}. Body: {body}"


def test_asking_the_desktop_host_to_execute_a_v2_run_is_refused_not_crashed():
    """Dispatch is the one V2 capability this host does not have, and it must say so.

    `v2_execution.execute_run` takes a Redis lock, opens the server engine and checkpoints
    to Postgres; on the server, `dispatch` enqueues a Celery task. The desktop has none of
    those, and `research-sidecar.spec` excludes `celery` — so the packaged app answered
    this with `ModuleNotFoundError: No module named 'celery'` behind a 500.

    501 rather than 500 because the distinction is the product's own: a capability the host
    lacks is a documented answer, a crash is a defect. Asserted before the row is created,
    so a refused dispatch also leaves nothing behind for a driver that will never come.
    """
    import asyncio
    import tempfile

    import httpx

    from desktop.sidecar import create_sidecar_app

    async def go(tmp) -> tuple[int, int]:
        app = create_sidecar_app(data_dir=tmp, token="tok", fake=True)
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
            async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:9") as c:
                head = {"Authorization": "Bearer tok"}
                proj = await c.post("/api/v1/projects", json={"name": "p"}, headers=head)
                pid = proj.json()["id"]
                body = {"question": "q", "depth": "fast", "project_id": pid}
                dispatched = await c.post(
                    "/api/v1/v2/runs", json={**body, "dispatch": True}, headers=head
                )
                created = await c.post(
                    "/api/v1/v2/runs", json={**body, "dispatch": False}, headers=head
                )
                return dispatched.status_code, created.status_code

    with tempfile.TemporaryDirectory() as tmp:
        refused, created = asyncio.run(go(tmp))

    assert refused == 501, f"dispatch should be refused as unimplemented, got {refused}"
    assert created == 201, f"creating a run without dispatch should still work, got {created}"
