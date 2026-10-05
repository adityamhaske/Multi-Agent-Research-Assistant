"""Approving a report succeeds when filing it into project memory cannot, and says so honestly.

The defect this pins: approving a run also files its report into project memory, a best-effort
step that needs an embeddings provider. On a deployment without one — no Ollama running, no
`EMBEDDINGS_PROVIDER` — the step failed as designed, rolled the session back, and then logged
`run.id`. After the rollback that attribute reloads lazily, outside the greenlet, so the log
line raised `MissingGreenlet` and the route answered **500**. The approval had already been
committed: the run was COMPLETED with its artifact, while the page told the reviewer
"Couldn't record that decision". Found driving the real UI in real mode.

Test runs never saw it, because fake mode always has an embedder; only a real deployment
without a provider reaches the failing branch. So this one installs the repo's own
`NoEmbeddings` — what such a deployment gets — and drives the real route on Postgres.
"""

from __future__ import annotations

from tests.conftest import requires_db

pytestmark = requires_db


async def test_an_ingest_without_an_embeddings_provider_never_fails_the_approval(db, monkeypatch):
    """The helper the approval route calls after committing the decision, on Postgres, where
    project memory exists. (The parity server driver runs on SQLite, which has no project
    memory, so the failing branch is unreachable there.) Before the fix this raised
    `MissingGreenlet` out of the log line, which the route turned into a 500."""
    from structlog.testing import CapturingLogger

    from app import adapters
    from app.api.v1 import runs
    from research_engine.embeddings import NoEmbeddings
    from tests.dataflow.test_project_memory import SOLAR_REPORT, make_project, make_run, make_user

    user = await make_user(db)
    project = await make_project(db, user, "Energy")
    run = await make_run(db, project, user, question="solar capacity growth")
    await db.commit()  # the route commits the decision before this best-effort step
    run_id = str(run.id)

    async def no_provider(_keys=None):
        return NoEmbeddings()

    monkeypatch.setattr(adapters, "embeddings_for", no_provider)
    captured = CapturingLogger()
    monkeypatch.setattr(runs, "logger", captured)

    await runs._ingest_report_into_memory(db, run, SOLAR_REPORT)

    failures = [c.kwargs for c in captured.calls if c.args and c.args[0] == "memory_ingest_failed"]
    assert failures and failures[0]["run_id"] == run_id, (
        "the memory gap must still be reported, against the right run"
    )
    assert "embeddings" in failures[0]["error"].lower()
