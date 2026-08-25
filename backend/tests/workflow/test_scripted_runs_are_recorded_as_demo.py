"""A run that reached no provider must never be able to present as one that did.

The repository's central invariant is that a false measurement is a P0 bug, and AGENTS.md
names this exact shape: *never record a model id you did not actually call*. It was being
violated by the commonest first-run setup.

`demo` was a per-request flag, and `llm_mode` a deployment setting, and nothing tied them
together. But `start.sh` exports `LLM_MODE=fake` in two cases — `--fake`, and **silently as
a fallback when `.env` carries no provider key** — so the default experience of someone who
has not added a key is a fake deployment. Every run on it was scripted, and every run on it
recorded `demo = false`. Downstream, all of which read the row rather than the config:

* the exported bundle recorded `models: {planner: "google:gemini-2.5-pro", …}` — models
  nothing had called — alongside a plausible non-zero `cost_usd`;
* the `.md` export skipped its demo stamp, because that reads `session.demo`;
* `python -m research_engine.verify_bundle` printed **PASS** with no demo banner, because
  the banner reads `manifest.demo`.

So the artifact the product offers as proof said, in every field a reader would check, that
scripted fixtures were real research. Measured on a live stack before the fix: a run against
a `LLM_MODE=fake` server exported a bundle with `demo: False`, five Google model ids, and
`cost_usd: 0.00126`.

The rule now: **the row records what actually ran, not what was requested.** It has three
homes, one per config resolver, and they must not drift:

    V1 server   `app/workers/pipeline_runner.py::_run_config_for`
    V2          `app/v2_execution.py::run_config_for_run`
    V1 desktop  `desktop/sidecar.py::_drive_session`

Deciding both routes in a single branch is also what keeps a resumed run consistent: `demo`
selects the seeded content (docs/17 §6.1) while `llm_mode` keeps the run offline, so a
`demo` that flipped False→True between a run and its resume could change the content
mid-run.
"""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import UTC, datetime

import httpx
import pytest
from sqlalchemy import insert, select

from app import v2_execution, v2_runtime
from app.models.project import Project
from app.models.session import Session as SessionRow
from app.models.user import User
from app.runtime import run_config_from_settings
from desktop.sidecar import create_sidecar_app
from tests.migration_support import open_db

TOKEN = "test-demo-token"


def _fake_deployment_config():
    """What `run_config_from_settings()` returns on a `LLM_MODE=fake` deployment."""
    return replace(run_config_from_settings(), llm_mode="fake")


def _real_deployment_config():
    return replace(run_config_from_settings(), llm_mode="real")


# ── V1 server ──────────────────────────────────────────────────────────────────────


class _Db:
    """Enough AsyncSession for `_run_config_for`, which commits the routing snapshot."""

    def __init__(self) -> None:
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1

    async def execute(self, *_a, **_k):
        class _R:
            def scalar_one_or_none(self):
                return None

        return _R()


async def test_server_v1_a_fake_deployment_records_the_run_as_a_demo(monkeypatch):
    """The bug as it shipped: scripted models, `demo = false` on the row.

    Negative control: restore the old `if session.demo:` branch and `row.demo` stays False
    while the returned config is still `llm_mode="fake"` — which is the divergence between
    what ran and what was recorded that every downstream field then repeated.
    """
    import app.workers.pipeline_runner as runner_mod

    monkeypatch.setattr(runner_mod, "run_config_from_settings", _fake_deployment_config)

    row = SessionRow(prompt="q", research_depth="fast")
    row.demo = False
    cfg = await runner_mod._run_config_for(_Db(), row, str(uuid.uuid4()))

    assert cfg.llm_mode == "fake", "the deployment is fake; the run was scripted"
    assert cfg.demo is True, "the config must agree with itself"
    assert row.demo is True, "a scripted run was recorded as though a provider had answered"


async def test_server_v1_a_real_deployment_leaves_an_ordinary_run_alone(monkeypatch):
    """The control. Without it, unconditionally stamping every run would pass the test above.

    A real run must stay unmarked, or the demo stamp becomes noise and stops meaning
    anything on the runs that need it.
    """
    import app.workers.pipeline_runner as runner_mod

    monkeypatch.setattr(runner_mod, "run_config_from_settings", _real_deployment_config)

    row = SessionRow(prompt="q", research_depth="fast")
    row.demo = False
    cfg = await runner_mod._run_config_for(_Db(), row, str(uuid.uuid4()))

    assert cfg.llm_mode == "real"
    assert cfg.demo is False
    assert row.demo is False


async def test_server_v1_an_explicit_demo_request_still_works_on_a_real_deployment(monkeypatch):
    """The path that already worked keeps working: a demo run beside real ones."""
    import app.workers.pipeline_runner as runner_mod

    monkeypatch.setattr(runner_mod, "run_config_from_settings", _real_deployment_config)

    row = SessionRow(prompt="q", research_depth="fast")
    row.demo = True
    cfg = await runner_mod._run_config_for(_Db(), row, str(uuid.uuid4()))

    assert (cfg.llm_mode, cfg.demo, row.demo) == ("fake", True, True)


# ── V2 ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
async def v2_run(tmp_path):
    async with open_db(tmp_path / "demo.sqlite") as maker, maker() as db:
        now = datetime(2026, 8, 24, tzinfo=UTC)
        uid, pid = uuid.uuid4(), uuid.uuid4()
        await db.execute(
            insert(User).values(
                id=uid, email=f"{uid}@x.invalid", hashed_pw="x", is_active=True, created_at=now
            )
        )
        await db.execute(
            insert(Project).values(id=pid, user_id=uid, name="P", created_at=now, updated_at=now)
        )
        await db.commit()
        run = await v2_runtime.create_run(
            db, owner_id=uid, project_id=pid, question="q", depth="fast"
        )
        await db.commit()
        yield db, run


async def test_v2_a_fake_deployment_records_the_run_as_a_demo(monkeypatch, v2_run):
    """Same rule on the V2 path, which is the one this release leads with."""
    db, run = v2_run
    monkeypatch.setattr(v2_execution, "run_config_from_settings", _fake_deployment_config)

    cfg = await v2_execution.run_config_for_run(db, run)
    await db.commit()

    assert (cfg.llm_mode, cfg.demo) == ("fake", True)
    from app.models.research import ResearchRun

    fresh = (await db.execute(select(ResearchRun).where(ResearchRun.id == run.id))).scalars().one()
    assert fresh.demo is True, "a scripted V2 run was recorded as real research"


async def test_v2_a_real_deployment_leaves_an_ordinary_run_alone(monkeypatch, v2_run):
    db, run = v2_run
    monkeypatch.setattr(v2_execution, "run_config_from_settings", _real_deployment_config)

    cfg = await v2_execution.run_config_for_run(db, run)
    await db.commit()

    assert (cfg.llm_mode, cfg.demo) == ("real", False)
    assert run.demo is False


# ── V1 desktop ─────────────────────────────────────────────────────────────────────


async def test_desktop_a_fake_app_records_its_runs_as_demos(tmp_path):
    """End to end over the sidecar's real routes, on a `--fake` app.

    The desktop's `--fake` is process-wide, so *every* run on it is scripted. Before this,
    each one persisted `demo = false` and its `.md` export came out without the stamp.
    """
    app = create_sidecar_app(data_dir=tmp_path, token=TOKEN, fake=True)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:9") as client:
            auth = {"Authorization": f"Bearer {TOKEN}"}
            start = await client.post(
                "/api/v1/research",
                headers=auth,
                json={"query": "What is retrieval-augmented generation?", "depth": "fast"},
            )
            assert start.status_code == 202
            sid = start.json()["session_id"]

            import asyncio

            deadline = asyncio.get_event_loop().time() + 30
            detail: dict = {}
            while asyncio.get_event_loop().time() < deadline:
                detail = (await client.get(f"/api/v1/research/{sid}", headers=auth)).json()
                if detail["status"] == "AWAITING_APPROVAL":
                    break
                await asyncio.sleep(0.05)

            assert detail["status"] == "AWAITING_APPROVAL"
            assert detail["demo"] is True, "a scripted desktop run recorded itself as real research"
