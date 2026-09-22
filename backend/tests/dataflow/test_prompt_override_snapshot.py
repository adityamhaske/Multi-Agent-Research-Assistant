"""
A run executes under the overrides it started with, and nothing else (PR-6, scope freeze §17).

Two invariants, and the second is the one that bites:

**Snapshot immutability.** `effective_prompt_overrides` is written exactly once, in the same
transaction that writes RUNNING, and a start is decided by the caller's arguments — not by
finding the column NULL. NULL is also what every run created before this column holds, so
"first start" and "resumed pre-upgrade run" are indistinguishable from the row alone.

**Execution-source immutability.** Once execution begins, prompt resolution reads the row
and only the row. A run pauses at a human gate for as long as its reader takes; if resume
re-read live preferences, an edit made in that window would rewrite the instructions the
first half of the report was already written under, and the finished report would be
attributable to no configuration that ever existed.

These drive the **host builders** rather than constructing a `RunConfig` by hand. AGENTS.md
records why: `corpus_mode` lost the row → `RunConfig` hop on both hosts in turn while a test
that built the config itself stayed green throughout, because it had stubbed the exact hop
that was broken.
"""

from __future__ import annotations

import ast
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import insert

from app import run_execution, run_lifecycle
from app.models.project import Project
from app.models.user import User
from app.services.run_config import (
    OVERRIDES_APPLIED,
    OVERRIDES_NONE,
    OVERRIDES_UNUSABLE,
    PREFERENCE_FIELDS,
)
from tests.sqlite_support import open_db

BACKEND = Path(__file__).resolve().parents[2]

BODY = "Plan in exactly three tasks."
LATER = "Plan in exactly nine tasks."


async def _run_with(db, preferences):
    """A real user and a real `research_runs` row, created the way `POST /runs` creates one."""
    now = datetime(2026, 9, 21, tzinfo=UTC)
    uid, pid = uuid.uuid4(), uuid.uuid4()
    await db.execute(
        insert(User).values(
            id=uid,
            email=f"{uid}@x.invalid",
            hashed_pw="x",
            is_active=True,
            created_at=now,
            preferences=preferences,
        )
    )
    await db.execute(
        insert(Project).values(id=pid, user_id=uid, name="P", created_at=now, updated_at=now)
    )
    await db.commit()
    run = await run_lifecycle.create_run(
        db, owner_id=uid, project_id=pid, question="q", depth="fast"
    )
    await db.commit()
    return run, uid


@pytest.fixture
async def started(tmp_path, request):
    """A run frozen the way a start freezes it, with whatever preferences the test asks for."""
    prefs = getattr(request, "param", {"prompt_overrides": {"planner": BODY}})
    async with open_db(tmp_path / "snap.sqlite") as maker, maker() as db:
        run, uid = await _run_with(db, prefs)
        await run_execution.freeze_prompt_overrides(db, run)
        await db.commit()
        yield db, run, uid


# ── What a start writes ───────────────────────────────────────────────────────────


async def test_a_start_freezes_the_users_overrides_onto_the_row(started):
    db, run, _ = started
    assert run.effective_prompt_overrides == {"planner": BODY}
    assert run.prompt_overrides_status == OVERRIDES_APPLIED


@pytest.mark.parametrize("started", [{}], indirect=True)
async def test_a_user_with_no_overrides_is_recorded_as_such(started):
    """`NONE` is a measurement — the resolver looked and found nothing. Distinct from the
    NULL a pre-upgrade run carries, where nothing ever looked."""
    _, run, _ = started
    assert run.effective_prompt_overrides is None
    assert run.prompt_overrides_status == OVERRIDES_NONE


@pytest.mark.parametrize(
    "started",
    [{"prompt_overrides": {"planner": BODY, "notarole": "x"}}],
    indirect=True,
)
async def test_a_malformed_stored_preference_freezes_as_unusable_not_partial(started):
    """One bad entry discards the lot. Honouring the good half would run the pipeline under
    a configuration nobody chose and nothing records; shipped prompts throughout is at least
    a state the run can name."""
    _, run, _ = started
    assert run.prompt_overrides_status == OVERRIDES_UNUSABLE
    assert run.effective_prompt_overrides is None


# ── What execution reads ──────────────────────────────────────────────────────────


async def test_the_frozen_snapshot_reaches_the_engine_config(started):
    """The hop the whole change exists for, through the server's own builder."""
    db, run, _ = started
    cfg = await run_execution.run_config_for_run(db, run)
    assert cfg.prompt_overrides == {"planner": BODY}


async def test_resume_does_not_re_read_live_preferences(started):
    """The gate window. A run sits paused for as long as its reader takes; an override
    edited in that window must not reach the second half of a report whose first half was
    written under the old one."""
    db, run, uid = started
    user = await db.get(User, uid)
    user.preferences = {"prompt_overrides": {"planner": LATER}}
    await db.commit()

    cfg = await run_execution.run_config_for_run(db, run)

    assert cfg.prompt_overrides == {"planner": BODY}, "resume re-resolved from live preferences"
    assert run.effective_prompt_overrides == {"planner": BODY}, "resume rewrote the snapshot"


async def test_a_pre_upgrade_run_stays_null_and_runs_on_shipped_prompts(tmp_path):
    """A run created before this column holds NULL, and resume must leave it that way.

    This is why "first start" cannot be inferred from the column: re-resolving on a NULL
    would hand a resumed pre-upgrade run instructions its first half never saw — the exact
    failure the argument-based gate exists to prevent.
    """
    async with open_db(tmp_path / "legacy.sqlite") as maker, maker() as db:
        run, _ = await _run_with(db, {"prompt_overrides": {"planner": LATER}})
        assert run.effective_prompt_overrides is None, "fixture precondition: never frozen"

        cfg = await run_execution.run_config_for_run(db, run)
        await db.commit()

        assert cfg.prompt_overrides == {}
        assert run.effective_prompt_overrides is None
        assert run.prompt_overrides_status is None, (
            "a status was invented for a run nothing ever resolved"
        )


async def test_a_snapshot_that_cannot_be_used_yields_shipped_prompts_and_says_so(tmp_path):
    """A hand-edited row, or one written by a future migration. The API refuses these
    shapes, but the runtime is the boundary that matters and re-checks rather than trusting.
    """
    async with open_db(tmp_path / "corrupt.sqlite") as maker, maker() as db:
        run, _ = await _run_with(db, {})
        run.effective_prompt_overrides = {"planner": BODY, "notarole": "x"}
        run.prompt_overrides_status = OVERRIDES_APPLIED
        await db.commit()

        cfg = await run_execution.run_config_for_run(db, run)
        await db.commit()

        assert cfg.prompt_overrides == {}, "a partially usable snapshot was partially applied"
        assert run.prompt_overrides_status == OVERRIDES_UNUSABLE
        assert run.effective_prompt_overrides == {"planner": BODY, "notarole": "x"}, (
            "the snapshot was rewritten; only the status is a measurement this run may correct"
        )


async def test_run_config_never_reads_the_owners_prompt_overrides(started):
    """The execution-source rule, asserted by making the live read impossible.

    `run_config_for_run` legitimately loads the owner — `model_routing` and the five dialled
    preferences both resolve through it — so "it does not load the user" is the wrong claim.
    This is the right one: whatever it reads off that user, it is not this.
    """
    db, run, uid = started
    user = await db.get(User, uid)

    class _Trap(dict):
        def get(self, key, *a):
            assert key != "prompt_overrides", "live preferences were consulted during a run"
            return super().get(key, *a)

    user.preferences = _Trap(user.preferences or {})
    cfg = await run_execution.run_config_for_run(db, run)
    assert cfg.prompt_overrides == {"planner": BODY}


def test_prompt_overrides_is_not_a_live_dialled_preference():
    """The five in `PREFERENCE_FIELDS` are re-read on every resume, which is existing
    behaviour and correct for them. Adding this one there would silently undo the snapshot."""
    assert "prompt_overrides" not in PREFERENCE_FIELDS


# ── The gate itself, on both hosts ────────────────────────────────────────────────


def _freeze_guard(path: Path, arg_names: tuple[str, ...]) -> ast.If:
    """The `if` that guards this host's freeze call, or a failure naming what was found."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        calls = {
            getattr(c.func, "attr", getattr(c.func, "id", ""))
            for c in ast.walk(node)
            if isinstance(c, ast.Call)
        }
        if "freeze_prompt_overrides" in calls:
            names = {n.id for n in ast.walk(node.test) if isinstance(n, ast.Name)}
            assert names == set(arg_names), (
                f"{path.name}: the freeze is gated on {sorted(names)}, not on {sorted(arg_names)}"
            )
            return node
    raise AssertionError(f"{path.name} never freezes the snapshot")


@pytest.mark.parametrize(
    ("relpath", "args"),
    [("app/run_execution.py", ("resume", "plan")), ("desktop/sidecar.py", ("resume", "plan"))],
)
def test_both_hosts_gate_the_freeze_on_the_call_arguments(relpath, args):
    """Structural because the behavioural version needs a broker on one host and a packaged
    app on the other. The claim is narrow and worth pinning anyway: the guard reads the
    arguments that distinguish a start from a resume, and never the column — which is what
    "do not infer first start from NULL" means in code.
    """
    guard = _freeze_guard(BACKEND / relpath, args)
    assert "effective_prompt_overrides" not in ast.unparse(guard.test)


def test_the_server_freezes_inside_the_transaction_that_starts_the_run():
    """Ordering, not just presence: a freeze after the commit would leave a window in which
    a run is observably RUNNING with no record of what it is running under — and a crash in
    that window resumes a started run that never froze."""
    src = (BACKEND / "app" / "run_execution.py").read_text(encoding="utf-8").splitlines()
    start = next(i for i, ln in enumerate(src) if 'set_status(db, run, "RUNNING")' in ln)
    freeze = next(i for i, ln in enumerate(src[start:], start) if "freeze_prompt_overrides" in ln)
    commit = next(i for i, ln in enumerate(src[start:], start) if "await db.commit()" in ln)
    assert start < freeze < commit
