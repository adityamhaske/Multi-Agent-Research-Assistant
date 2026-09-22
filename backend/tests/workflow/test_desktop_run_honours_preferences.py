"""
A desktop research **run** must honour the user's saved preferences (RFC AP-1/AP-2).

`desktop/sidecar.py::_drive_run` — the desktop's driver for the pipeline the product
actually ships — never read `users.preferences`. It built a `RunConfig`, applied the demo
rule, and then `replace()`d in only the four row-derived fields
(`skip_plan_gate`, `topic_seeds`, `outline_template`, `corpus_mode`). The other three
per-run builders all applied preferences:

    app/workers/pipeline_runner.py::_run_config_for     server, sessions
    app/run_execution.py::run_config_for_run            server, runs
    desktop/sidecar.py::_drive_session                  desktop, sessions

So a desktop user who set `retrieval_k`, `min_sources_per_task`, `snippet_max_chars` or a
search-provider key in Settings had it honoured on the legacy session path and **silently
discarded on runs**. Nothing failed, nothing logged, and the setting persisted correctly —
the value simply never reached the engine.

**Why nothing caught it.** `tests/workflow/test_host_parity.py` compares route
*registration*, and no route is missing; `AGENTS.md` records this exact shape — "a route
that exists on both hosts can still be desktop-only broken, and parity won't see it".

**Why these tests drive the real path.** `AGENTS.md`: "A test that builds `RunConfig(...)`
by hand cannot catch this" — `test_corpus_egress.py` stayed green through a live airgap
breach because it stubbed the exact hop that was broken. So nothing here constructs a
`RunConfig`, and nothing stubs `_drive_run`, `sidecar_run_config` or the preference
extractor. The tests POST to the sidecar's real routes and capture the config at the
**engine boundary** — `desktop.sidecar.run_pipeline`, one layer past the code under test —
which is the first point where "what the run actually dialled" is observable.
"""

from __future__ import annotations

import asyncio
import uuid

import httpx
import pytest

from desktop.sidecar import create_sidecar_app

TOKEN = "test-prefs-token"

#: Every preference the canonical server implementation honours, with a value distinct
#: from the `RunConfig` default so an assertion cannot pass on the default by accident.
#: Deliberately the whole supported surface and not one sample: the defect was that *no*
#: preference arrived, and a single-field test would have passed once any one of them was
#: wired. Keys and semantics are unchanged by this work — see `PREFERENCE_FIELDS`.
PREFERENCES = {
    "retrieval_k": 9,
    "min_sources_per_task": 3,
    "snippet_max_chars": 250,
    "tavily_api_key": "tvly-desktop-preference",
    "brave_api_key": "brave-desktop-preference",
}

#: What `RunConfig` gives a user who has set nothing (`research_engine/runconfig.py`).
#: Pinned here so "unset stays unset" is asserted against stated values rather than
#: against whatever the class happens to return.
DEFAULTS = {
    "retrieval_k": 5,
    "min_sources_per_task": 0,
    "snippet_max_chars": 500,
    "tavily_api_key": "",
    "brave_api_key": "",
}


class _CapturedConfig(Exception):
    """Raised from the patched engine entry point to stop the run once observed.

    The run must not proceed past the capture: driving a whole scripted pipeline would
    make these tests slow and would couple them to graph behaviour they are not about.
    `_drive_run` catches `Exception` and records the run FAILED, which is the intended
    and harmless outcome here — the assertion has already been made.
    """

    def __init__(self, config):
        super().__init__("captured")
        self.config = config


async def _run_config_from_a_real_desktop_run(monkeypatch, tmp_path, preferences: dict | None):
    """Drive the sidecar's real routes and return the `RunConfig` the engine received.

    request → bearer auth → local user row → `users.preferences` → `_drive_run` →
    `RunConfig` → engine. Every hop is the shipped one; only the engine itself is replaced,
    and the engine is not what is under test.
    """
    captured: dict = {}

    async def _capture(**kwargs):
        captured["config"] = kwargs["run_config"]
        raise _CapturedConfig(kwargs["run_config"])

    # The sidecar binds `run_pipeline` at module scope (`desktop/sidecar.py`), so this
    # intercepts the handoff without touching the builder that produces its argument.
    monkeypatch.setattr("desktop.sidecar.run_pipeline", _capture)

    app = create_sidecar_app(data_dir=tmp_path, token=TOKEN, fake=True)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:9") as client:
            auth = {"Authorization": f"Bearer {TOKEN}"}

            if preferences is not None:
                saved = await client.patch(
                    "/api/v1/auth/me", headers=auth, json={"preferences": preferences}
                )
                assert saved.status_code == 200, saved.text

            project = await client.post(
                "/api/v1/projects",
                headers=auth,
                json={"name": f"prefs-{uuid.uuid4().hex[:8]}"},
            )
            assert project.status_code == 201, project.text

            created = await client.post(
                "/api/v1/runs",
                headers=auth,
                json={
                    "project_id": project.json()["id"],
                    "question": "Does the desktop run honour my settings?",
                    "depth": "fast",
                },
            )
            assert created.status_code == 201, created.text

            # `_SidecarDispatcher.start` fires `_drive_run` as an un-awaited asyncio task,
            # so the POST returns before the config exists. Poll rather than sleep.
            deadline = asyncio.get_event_loop().time() + 20
            while "config" not in captured and asyncio.get_event_loop().time() < deadline:
                await asyncio.sleep(0.01)

    assert "config" in captured, "the engine was never reached — the run never started"
    return captured["config"]


# ── AP-1: the regression ──────────────────────────────────────────────────────────


@pytest.mark.parametrize(("field", "expected"), sorted(PREFERENCES.items()))
async def test_a_desktop_run_receives_each_saved_preference(monkeypatch, tmp_path, field, expected):
    """The defect, one field per case so a failure names which preference was dropped.

    Fails on the pre-fix `_drive_run`: every one of these arrived as the `RunConfig`
    default because the builder never read the user row.
    """
    config = await _run_config_from_a_real_desktop_run(monkeypatch, tmp_path, PREFERENCES)
    assert getattr(config, field) == expected, (
        f"a desktop run ignored the saved preference {field!r}: "
        f"expected {expected!r}, engine received {getattr(config, field)!r}"
    )


async def test_a_desktop_run_with_no_preferences_set_keeps_every_default(monkeypatch, tmp_path):
    """The other direction, and the one that stops the fix from being unconditional.

    A builder that always wrote values would satisfy the test above while changing what an
    account that never opened Settings gets — the negative control `AGENTS.md` asks for.
    """
    config = await _run_config_from_a_real_desktop_run(monkeypatch, tmp_path, None)
    for field, default in sorted(DEFAULTS.items()):
        assert getattr(config, field) == default, (
            f"{field!r} drifted from its default for a user with no preferences set"
        )


async def test_a_partially_configured_user_keeps_the_defaults_they_did_not_set(
    monkeypatch, tmp_path
):
    """An unset preference is absent, not `None` — `None` would overwrite the default.

    This is what `_preference_overrides`' `is not None` filter buys, and it has to hold on
    the desktop run path too or a user who sets one field silently resets the other four.
    """
    config = await _run_config_from_a_real_desktop_run(
        monkeypatch, tmp_path, {"retrieval_k": PREFERENCES["retrieval_k"]}
    )
    assert config.retrieval_k == PREFERENCES["retrieval_k"]
    for field in ("min_sources_per_task", "snippet_max_chars", "tavily_api_key", "brave_api_key"):
        assert getattr(config, field) == DEFAULTS[field], f"setting retrieval_k disturbed {field!r}"


async def test_the_row_derived_fields_still_arrive_alongside_preferences(monkeypatch, tmp_path):
    """Preferences must be added to the existing overrides, not substituted for them.

    `corpus_mode` is the one with teeth: `AGENTS.md` records that a run recorded as
    airgapped researched the open web on both hosts in turn, because the field reached the
    row and never the `RunConfig`. A fix that replaced the overrides dict would reopen it.
    """
    config = await _run_config_from_a_real_desktop_run(monkeypatch, tmp_path, PREFERENCES)
    assert config.retrieval_k == PREFERENCES["retrieval_k"]
    assert config.corpus_mode is False
    assert config.skip_plan_gate is True
    assert config.topic_seeds == ()
    assert config.outline_template is None


# ── AP-2: the two hosts agree, measured rather than asserted ──────────────────────


async def test_server_and_desktop_runs_apply_the_same_preferences(monkeypatch, tmp_path):
    """Same saved preferences, same five values in the config the engine receives.

    Both sides drive the real builder — `run_execution.run_config_for_run` for the server,
    the sidecar's routes for the desktop. `AGENTS.md` records why the comparison has to be
    against the *server's* result rather than between two desktop paths: the corpus parity
    test asserted equality between the two desktop response shapes, "which only proves the
    bug was consistent, not correct".
    """
    import uuid as _uuid
    from datetime import UTC, datetime

    from sqlalchemy import insert

    from app import run_execution, run_lifecycle
    from app.models.project import Project
    from app.models.user import User
    from tests.sqlite_support import open_db

    async with open_db(tmp_path / "server.sqlite") as maker, maker() as db:
        now = datetime(2026, 9, 21, tzinfo=UTC)
        uid, pid = _uuid.uuid4(), _uuid.uuid4()
        await db.execute(
            insert(User).values(
                id=uid,
                email=f"{uid}@x.invalid",
                hashed_pw="x",
                is_active=True,
                created_at=now,
                preferences=dict(PREFERENCES),
            )
        )
        await db.execute(
            insert(Project).values(id=pid, user_id=uid, name="P", created_at=now, updated_at=now)
        )
        await db.commit()
        row = await run_lifecycle.create_run(
            db, owner_id=uid, project_id=pid, question="q", depth="fast"
        )
        await db.commit()
        server_config = await run_execution.run_config_for_run(db, row)

    desktop_config = await _run_config_from_a_real_desktop_run(monkeypatch, tmp_path, PREFERENCES)

    for field in sorted(PREFERENCES):
        assert getattr(desktop_config, field) == getattr(server_config, field), (
            f"hosts disagree on {field!r}: server {getattr(server_config, field)!r}, "
            f"desktop {getattr(desktop_config, field)!r}"
        )
