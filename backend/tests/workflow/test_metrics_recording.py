"""
The metrics are recorded at the boundaries where a run actually terminates, on both hosts.

A metric that is declared but never moves is the failure this repository has already
shipped once — a citation rate that was NULL on every run, memory keyed to the wrong table.
So nothing here asserts that a counter *exists*: every test drives the same path production
drives and asserts the number moved.

**A run does not finish in the engine.** `submit_report_review` sets `run.status =
"COMPLETED"` itself and freezes the artifact in the same transaction; the engine is never
resumed with `approved=True`, because `RunDispatcher.rework` hard-codes `False` on both
hosts (`app/workers/dispatch.py`, `desktop/sidecar.py`). The committed parity golden is the
evidence: a full journey reaches `COMPLETED` at *approve the report*, and
`elapsed_seconds` is `None` at every step including the finished run and its bundle. So
completion is observed at the approval route and `FAILED`/`CANCELLED` in the persistence
adapter — the two boundaries that exist, rather than one that would have been convenient.

Both boundaries are functions the two hosts share by identity: the sidecar's run routes
import `app.api.v1.runs` handlers, and both drivers call `run_execution.persist_outcome` by
name. Instrumenting them once is what makes the hosts record identically instead of by
discipline.

`/metrics` is server-only by design (a laptop is not scraped), which is a difference in
*exposition* and not in *recording* — `test_the_desktop_records_a_completed_run` is the
assertion that keeps it that way.
"""

from __future__ import annotations

import contextlib
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import insert

from app import metrics as m
from app import run_execution, run_lifecycle
from app.models.project import Project
from app.models.user import User
from research_engine import runner
from research_engine.runconfig import RunConfig
from tests.parity.drivers import desktop_driver, server_driver
from tests.parity.journeys import _await_run_status
from tests.sqlite_support import open_db

QUESTION = "What did recent work find about retrieval-augmented generation?"

HOSTS = {"server": server_driver, "desktop": desktop_driver}


@pytest.fixture()
def registry(monkeypatch):
    fresh = m.Metrics()
    monkeypatch.setattr(m, "_default", fresh)
    return fresh


def _value(registry, name: str, labels: dict | None = None) -> float:
    return registry.registry.get_sample_value(name, labels) or 0.0


def _outcomes(registry) -> dict[str, float]:
    return {
        v: _value(registry, "research_run_outcomes_total", {"outcome": v})
        for v in m.DECLARED["research_run_outcomes"]["outcome"]
    }


def _confidence(registry) -> dict[str, float]:
    return {
        v: _value(registry, "research_run_cost_confidence_total", {"confidence": v})
        for v in m.DECLARED["research_run_cost_confidence"]["confidence"]
    }


# ── A genuinely successful run, driven the way a person drives one ────────────────


async def _run_to_approval(driver, *, routing=None) -> dict:
    """start → plan gate → approve plan → report gate → rework → report gate → approve.

    The rework loop is deliberate: it is the shape that would double-count if terminal
    observation were placed anywhere the run passes through more than once.
    """
    project = await driver.request("POST", "/projects", json={"name": f"m-{uuid.uuid4().hex}"})
    assert project.status_code in (200, 201), project.text

    body = {
        "project_id": project.json()["id"],
        "question": QUESTION,
        "depth": "fast",
        "skip_plan_gate": False,
    }
    if routing is not None:
        body["model_routing"] = routing
    created = await driver.request("POST", "/runs", json=body)
    assert created.status_code == 201, created.text
    run_id = created.json()["run_id"]

    at_plan = await _await_run_status(driver, run_id, {"AWAITING_PLAN", "FAILED"})
    assert at_plan.json()["run"]["status"] == "AWAITING_PLAN", at_plan.text

    await driver.request("POST", f"/runs/{run_id}/plan-review", json={"decision": "APPROVED"})
    at_report = await _await_run_status(driver, run_id, {"AWAITING_REVIEW", "FAILED"})
    assert at_report.json()["run"]["status"] == "AWAITING_REVIEW", at_report.text

    await driver.request(
        "POST",
        f"/runs/{run_id}/report-review",
        json={"decision": "REWORK_REQUESTED", "feedback": "Add a second source."},
    )
    reworked = await _await_run_status(driver, run_id, {"AWAITING_REVIEW", "FAILED"})
    assert reworked.json()["run"]["status"] == "AWAITING_REVIEW", reworked.text

    return {"run_id": run_id, "at_plan": at_plan, "at_report": at_report, "reworked": reworked}


@pytest.mark.parametrize("host", list(HOSTS), ids=list(HOSTS))
async def test_a_successful_run_is_recorded_exactly_once(registry, tmp_path, host):
    """The whole point of the phase, on both hosts: one run, one terminal observation."""
    async with HOSTS[host](tmp_path / host) as driver:
        state = await _run_to_approval(driver)
        run_id = state["run_id"]

        # Everything up to here is a pause. Nothing may have been counted yet.
        assert _outcomes(registry) == {"completed": 0.0, "failed": 0.0, "cancelled": 0.0}
        assert _value(registry, "research_run_cost_usd_total") == 0.0, (
            "a run waiting at a gate has not finished, and its spend is not final"
        )

        approved = await driver.request(
            "POST", f"/runs/{run_id}/report-review", json={"decision": "APPROVED"}
        )
        assert approved.status_code == 201, approved.text

        finished = (await driver.request("GET", f"/runs/{run_id}")).json()["run"]

    assert finished["status"] == "COMPLETED"
    assert _outcomes(registry) == {"completed": 1.0, "failed": 0.0, "cancelled": 0.0}

    # The counter agrees with the row rather than with a number the test made up.
    assert _value(registry, "research_run_cost_usd_total") == pytest.approx(finished["cost_usd"])
    assert (
        _value(registry, "research_run_tokens_total", {"direction": "input"})
        == (finished["tokens_input"])
    )
    assert (
        _value(registry, "research_run_tokens_total", {"direction": "output"})
        == (finished["tokens_output"])
    )
    assert sum(_confidence(registry).values()) == 1.0

    assert finished["cost_usd"] > 0 and finished["tokens_input"] > 0, (
        "the fixture must produce real spend, or this test proves nothing"
    )


@pytest.mark.parametrize("host", list(HOSTS), ids=list(HOSTS))
async def test_approving_an_already_completed_run_does_not_count_twice(registry, tmp_path, host):
    """A second approval is not a second terminal transition, on either host.

    Two independent things make that true, and A8 added neither. `reviews.revision_id` is
    UNIQUE, so the second `APPROVED` on the same revision is refused by the database before
    it reaches any observation — which is why this drives it and tolerates whatever the
    endpoint does with that refusal rather than asserting a status A8 is not entitled to
    change. And `submit_report_review` reads `run.status` before it writes `COMPLETED`, so
    a repeat approval that ever did get through would still not be a second transition."""
    async with HOSTS[host](tmp_path / f"{host}-twice") as driver:
        run_id = (await _run_to_approval(driver))["run_id"]
        first = await driver.request(
            "POST", f"/runs/{run_id}/report-review", json={"decision": "APPROVED"}
        )
        assert first.status_code == 201, first.text
        with contextlib.suppress(Exception):
            await driver.request(
                "POST", f"/runs/{run_id}/report-review", json={"decision": "APPROVED"}
            )

    assert _outcomes(registry)["completed"] == 1.0


async def test_a_dispatched_run_is_classified_from_its_stamped_routing(registry, tmp_path):
    """`run_config_for_run` writes the resolved routing onto the row, so a run that was
    actually driven always carries a snapshot — and this fixture's roles are catalog-priced,
    so its recorded cost is one an operator can trust."""
    async with server_driver(tmp_path / "priced") as driver:
        run_id = (await _run_to_approval(driver))["run_id"]
        approved = await driver.request(
            "POST", f"/runs/{run_id}/report-review", json={"decision": "APPROVED"}
        )
        assert approved.status_code == 201, approved.text
        finished = (await driver.request("GET", f"/runs/{run_id}")).json()["run"]

    assert finished["model_routing"], "a driven run must carry the routing it ran on"
    assert _confidence(registry)["priced"] == 1.0
    assert _confidence(registry)["unstamped"] == 0.0
    assert _value(registry, "research_run_cost_usd_total") > 0


async def test_the_exposition_carries_no_research_content(registry, tmp_path):
    """A real, approved run — then the bytes an operator would scrape."""
    async with server_driver(tmp_path / "exposition") as driver:
        run_id = (await _run_to_approval(driver))["run_id"]
        await driver.request("POST", f"/runs/{run_id}/report-review", json={"decision": "APPROVED"})

    text = registry.render()[0].decode()

    assert "research_run_outcomes_total" in text, "nothing was recorded; this proves nothing"
    for secret in (QUESTION, run_id, "retrieval-augmented"):
        assert secret not in text, f"{secret!r} reached the metrics endpoint"
    assert "@" not in text


# ── The states the persistence adapter owns ───────────────────────────────────────


@pytest.fixture
async def db(tmp_path):
    async with open_db(tmp_path / "metrics.sqlite") as maker, maker() as session:
        yield session


@pytest.fixture
async def owner(db):
    now = datetime(2026, 9, 9, tzinfo=UTC)
    uid, pid = uuid.uuid4(), uuid.uuid4()
    await db.execute(
        insert(User).values(
            id=uid, email=f"{uid}@x.invalid", hashed_pw="x", is_active=True, created_at=now
        )
    )
    await db.execute(
        insert(Project).values(id=pid, user_id=uid, name="RAG", created_at=now, updated_at=now)
    )
    await db.commit()
    return {"user_id": uid, "project_id": pid}


@pytest.fixture
async def saver(tmp_path):
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    async with AsyncSqliteSaver.from_conn_string(str(tmp_path / "graph.sqlite")) as s:
        yield s


async def _drive_once(db, owner, saver, **run_kw):
    """The real graph, then the real adapter — the two calls both drivers make."""
    run = await run_lifecycle.create_run(
        db,
        owner_id=owner["user_id"],
        project_id=owner["project_id"],
        question=QUESTION,
        depth="fast",
        demo=True,
        skip_plan_gate=True,
        **run_kw,
    )
    await db.commit()
    outcome = await runner.run(
        checkpointer=saver,
        session_id=str(run.id),
        user_id=str(owner["user_id"]),
        query=QUESTION,
        depth="fast",
        run_config=RunConfig(llm_mode="fake", demo=True, skip_plan_gate=True),
    )
    result = await run_execution.persist_outcome(db, run, outcome, saver=saver)
    await db.commit()
    return run, outcome, result


async def test_a_run_paused_at_the_report_gate_records_nothing(registry, db, owner, saver):
    _, _, result = await _drive_once(db, owner, saver)

    assert result.status == "AWAITING_REVIEW", result.status
    assert _outcomes(registry) == {"completed": 0.0, "failed": 0.0, "cancelled": 0.0}
    assert _value(registry, "research_run_cost_usd_total") == 0.0


async def test_a_cancelled_run_is_counted_and_keeps_its_spend(registry, db, owner, saver):
    """Cancellation is advisory — the outcome still arrives, and the tokens burned before
    the pipeline noticed are real. `persist_outcome` commits that spend deliberately; the
    counter must agree with the row rather than quietly drop it."""
    run = await run_lifecycle.create_run(
        db,
        owner_id=owner["user_id"],
        project_id=owner["project_id"],
        question=QUESTION,
        depth="fast",
        demo=True,
        skip_plan_gate=True,
    )
    await db.commit()
    await run_lifecycle.request_cancel(db, run, by=owner["user_id"])
    await db.commit()

    outcome = await runner.run(
        checkpointer=saver,
        session_id=str(run.id),
        user_id=str(owner["user_id"]),
        query=QUESTION,
        depth="fast",
        run_config=RunConfig(llm_mode="fake", demo=True, skip_plan_gate=True),
    )
    result = await run_execution.persist_outcome(db, run, outcome, saver=saver)
    await db.commit()
    run_execution.observe_persisted(run, outcome, result)

    assert result.status == "CANCELLED"
    assert _outcomes(registry)["cancelled"] == 1.0
    assert _value(registry, "research_run_cost_usd_total") == pytest.approx(outcome.cost_usd)
    # A run created directly and stopped before `run_config_for_run` could stamp a routing
    # carries none — which is `unstamped`, not `priced`. This is the only way to reach that
    # state, and reaching it is the point: the deployment default that applied instead is
    # invisible from a module that may not read `app.config`, so it is recorded as unknown
    # rather than vouched for.
    assert run.model_routing is None
    assert _confidence(registry) == {"priced": 0.0, "unpriced": 0.0, "unstamped": 1.0}


async def test_a_failed_run_is_counted(registry, db, owner, saver):
    """The engine's `failed` outcome is the adapter's to observe, and the only route to it
    that does not require a broken provider is the adapter itself."""
    run = await run_lifecycle.create_run(
        db,
        owner_id=owner["user_id"],
        project_id=owner["project_id"],
        question=QUESTION,
        depth="fast",
        demo=True,
        skip_plan_gate=True,
    )
    await db.commit()

    failed = runner.RunOutcome(status="failed", error="provider quota exhausted", cost_usd=0.02)
    result = await run_execution.persist_outcome(db, run, failed)
    await db.commit()
    run_execution.observe_persisted(run, failed, result)

    assert result.status == "FAILED"
    assert _outcomes(registry) == {"completed": 0.0, "failed": 1.0, "cancelled": 0.0}
    assert _value(registry, "research_run_cost_usd_total") == pytest.approx(0.02)


# ── Ingest, through the one shared contract ───────────────────────────────────────


def _corpus_store(tmp_path):
    from research_engine.corpus import CorpusStore
    from tests.dataflow.test_corpus_store import FakeEmbeddings

    return CorpusStore(tmp_path / "corpus.sqlite", FakeEmbeddings())


async def test_ingesting_a_document_counts_it_and_its_bytes(registry, tmp_path):
    from app.services import corpus_ingest

    body = ("Retrieval-augmented generation grounds a model in retrieved text. " * 40).encode()
    await corpus_ingest.ingest_document(_corpus_store(tmp_path), "paper.txt", body)

    assert _value(registry, "corpus_ingest_documents_total", {"outcome": "ingested"}) == 1.0
    assert _value(registry, "corpus_ingest_bytes_total") == float(len(body))


async def test_re_ingesting_the_same_document_is_a_skip_not_throughput(registry, tmp_path):
    """`skipped` is a success, not a failure — but it indexed nothing, so it must not
    inflate the throughput numerator or the byte total."""
    from app.services import corpus_ingest

    store = _corpus_store(tmp_path)
    body = ("The same document, twice. " * 60).encode()
    await corpus_ingest.ingest_document(store, "paper.txt", body)
    await corpus_ingest.ingest_document(store, "paper.txt", body)

    assert _value(registry, "corpus_ingest_documents_total", {"outcome": "ingested"}) == 1.0
    assert _value(registry, "corpus_ingest_documents_total", {"outcome": "skipped"}) == 1.0
    assert _value(registry, "corpus_ingest_bytes_total") == float(len(body))


async def test_a_refused_upload_is_counted_without_its_reason(registry, tmp_path):
    """The refusal message names the file. The metric must not."""
    from app.errors import Invalid
    from app.services import corpus_ingest

    with pytest.raises(Invalid):
        await corpus_ingest.ingest_document(
            _corpus_store(tmp_path), "secret-acquisition-memo.xyz", b"unsupported format"
        )

    assert _value(registry, "corpus_ingest_documents_total", {"outcome": "rejected"}) == 1.0
    assert b"secret-acquisition-memo" not in registry.render()[0]


async def test_an_unavailable_embedder_is_its_own_outcome(registry, tmp_path):
    """ "Fix your file" and "try again later" are different operational signals, and the
    module already tells them apart for the client — the metric keeps that distinction."""
    from app.errors import DependencyUnavailable
    from app.services import corpus_ingest
    from research_engine.embeddings import EmbeddingsUnavailable

    class _Down:
        async def ingest(self, *_a, **_kw):
            raise EmbeddingsUnavailable("no embedding server")

    with pytest.raises(DependencyUnavailable):
        await corpus_ingest.ingest_document(_Down(), "paper.txt", b"some text to index")

    assert _value(registry, "corpus_ingest_documents_total", {"outcome": "unavailable"}) == 1.0


async def test_an_upload_is_counted_the_same_on_the_desktop(registry, tmp_path):
    """The upload route differs per host; the contract it calls does not."""
    from app.services import corpus_ingest

    async with desktop_driver(tmp_path / "desktop-ingest") as driver:
        project = await driver.request("POST", "/projects", json={"name": "ingest"})
        body = ("Corpus text for the desktop host. " * 60).encode()
        resp = await driver.client.post(
            f"/api/v1/projects/{project.json()['id']}/corpus/documents",
            files={"file": ("desktop.txt", body, "text/plain")},
        )
        assert resp.status_code == 201, resp.text

    assert _value(registry, "corpus_ingest_documents_total", {"outcome": "ingested"}) == 1.0
    assert corpus_ingest.ingest_document is not None  # the shared contract, not a copy


# ── Exposition is server-only; recording is not ───────────────────────────────────


async def test_the_server_exposes_metrics(tmp_path):
    async with server_driver(tmp_path / "expose") as driver:
        resp = await driver.client.get("/metrics")

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/plain")
    assert "# TYPE research_run_outcomes_total counter" in resp.text


async def test_the_desktop_does_not_expose_metrics(tmp_path):
    """Declared, not accidental: a laptop is not scraped, and an unauthenticated counter
    endpoint on a loopback socket would add surface with no consumer."""
    async with desktop_driver(tmp_path / "no-expose") as driver:
        resp = await driver.client.get("/metrics")

    assert resp.status_code == 404


async def test_the_desktop_records_a_completed_run(registry, tmp_path):
    """The half that keeps this a difference in exposition rather than in behaviour: the
    desktop cannot be scraped, and still counts every run it finishes."""
    async with desktop_driver(tmp_path / "desktop-records") as driver:
        run_id = (await _run_to_approval(driver))["run_id"]
        await driver.request("POST", f"/runs/{run_id}/report-review", json={"decision": "APPROVED"})

    assert _outcomes(registry)["completed"] == 1.0


# ── Ordering: a counter cannot be incremented for a write that rolls back ─────────
#
# Prometheus counters are not transactional and cannot be decremented, so "increment, then
# fail to commit" is unrecoverable: the totals would permanently disagree with the rows.
# Both boundaries therefore observe strictly *after* their commit, and these two tests are
# what hold them there.


async def test_a_rolled_back_approval_counts_nothing(registry, tmp_path, monkeypatch):
    """The approval transaction fails at `create_artifact`, which is inside it.

    `submit_report_review` rolls back and answers 409; the observation sits after the
    commit, so it is never reached. Driven through the real route with a real failure the
    lifecycle already raises, rather than by breaking the session object."""
    from app import run_lifecycle

    def _refuse(*_a, **_kw):
        raise run_lifecycle.LifecycleError("the run has no assemblable bundle")

    async with server_driver(tmp_path / "rollback") as driver:
        run_id = (await _run_to_approval(driver))["run_id"]
        monkeypatch.setattr(run_lifecycle, "create_artifact", _refuse)
        refused = await driver.request(
            "POST", f"/runs/{run_id}/report-review", json={"decision": "APPROVED"}
        )
        monkeypatch.undo()
        after = (await driver.request("GET", f"/runs/{run_id}")).json()["run"]

    assert refused.status_code == 409, refused.text
    assert after["status"] == "AWAITING_REVIEW", "the rollback left the run un-approved"
    assert _outcomes(registry) == {"completed": 0.0, "failed": 0.0, "cancelled": 0.0}
    assert _value(registry, "research_run_cost_usd_total") == 0.0
    assert sum(_confidence(registry).values()) == 0.0


async def test_persisting_an_outcome_counts_nothing_until_the_caller_commits(
    registry, db, owner, saver
):
    """`persist_outcome` writes; it does not count.

    Its own docstring says the caller owns the transaction, so the caller owns the counter
    too — `observe_persisted` is a separate call both drivers make on the line after their
    `db.commit()`. This drives the two halves apart deliberately: persist, check nothing
    moved, then commit and observe."""
    run = await run_lifecycle.create_run(
        db,
        owner_id=owner["user_id"],
        project_id=owner["project_id"],
        question=QUESTION,
        depth="fast",
        demo=True,
        skip_plan_gate=True,
    )
    await db.commit()

    failed = runner.RunOutcome(status="failed", error="provider quota exhausted", cost_usd=0.02)
    result = await run_execution.persist_outcome(db, run, failed)

    assert result.status == "FAILED"
    assert _outcomes(registry)["failed"] == 0.0, (
        "persist_outcome incremented a counter for a write nobody has committed"
    )

    await db.rollback()
    assert _outcomes(registry)["failed"] == 0.0, "a rolled-back outcome must count nothing"

    # The committed path, for contrast: same call, and now the counter moves.
    run = await run_lifecycle.create_run(
        db,
        owner_id=owner["user_id"],
        project_id=owner["project_id"],
        question=QUESTION,
        depth="fast",
        demo=True,
        skip_plan_gate=True,
    )
    await db.commit()
    result = await run_execution.persist_outcome(db, run, failed)
    await db.commit()
    run_execution.observe_persisted(run, failed, result)

    assert _outcomes(registry)["failed"] == 1.0


def test_both_drivers_observe_after_their_commit():
    """The ordering itself, read off the source of both drivers.

    A behavioural test can show that a rollback counts nothing; only this can show that
    neither host has quietly moved the call back above its commit — which is the edit a
    future change would make by accident."""
    import ast
    import inspect
    from pathlib import Path

    backend = Path(__file__).resolve().parents[2]
    for path, driver in (
        (backend / "app" / "run_execution.py", "execute_run"),
        (backend / "desktop" / "sidecar.py", "_drive_run"),
    ):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        fn = next(
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.AsyncFunctionDef | ast.FunctionDef) and n.name == driver
        )
        commits, observes = [], []
        for node in ast.walk(fn):
            if not isinstance(node, ast.Call):
                continue
            name = ast.unparse(node.func)
            if name.endswith("db.commit"):
                commits.append(node.lineno)
            if name.endswith("observe_persisted"):
                observes.append(node.lineno)
        assert observes, f"{driver} never records the outcome it persisted"
        assert commits, f"{driver} does not commit — the harness is reading the wrong function"
        for line in observes:
            assert any(c < line for c in commits), (
                f"{driver} calls observe_persisted at line {line}, before any db.commit() — "
                "a counter incremented for a write that may still roll back cannot be undone"
            )
    assert inspect.isfunction(run_execution.observe_persisted), "one home for the observation"
