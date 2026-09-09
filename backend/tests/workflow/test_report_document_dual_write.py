"""A revision carries a typed view of its report, and the Markdown stays authoritative.

The point of A7 is a boundary, not a behaviour change. So the assertions that matter are
the ones proving nothing moved: `report_markdown` is still the model's own bytes,
`report_hash` is still `sha256` of those bytes, the approval hash still pins the same value,
and the bundle still verifies. The typed view rides alongside and nothing authoritative
reads it.

`test_bundle.py`, `test_bundle_export_routes.py`, `test_artifact_authorization.py` and
`test_claim_extraction_parity.py` are the real regression here and run unchanged.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import insert

from app import run_lifecycle
from app.models.project import Project
from app.models.revision import Revision
from app.models.user import User
from research_engine.document import ReportDocument
from tests.sqlite_support import open_db

NOW = datetime(2026, 9, 9, tzinfo=UTC)

REPORT = (
    "# Fixture Report\n\n## Executive Summary\nDeterministic summary [1].\n\n"
    "## Key Findings\n- A citable fact [1]\n- A corroborating fact [2]\n\n"
    "## Limitations\nFixture data only.\n\n"
    "## Sources\n[1] https://example.com/fixture/1\n"
)


@pytest.fixture
async def run(tmp_path):
    async with open_db(tmp_path / "a7.sqlite") as maker, maker() as db:
        uid, pid = uuid.uuid4(), uuid.uuid4()
        await db.execute(
            insert(User).values(
                id=uid, email=f"{uid}@x.invalid", hashed_pw="x", is_active=True, created_at=NOW
            )
        )
        await db.execute(
            insert(Project).values(id=pid, user_id=uid, name="P", created_at=NOW, updated_at=NOW)
        )
        await db.commit()
        row = await run_lifecycle.create_run(
            db, owner_id=uid, project_id=pid, question="What is RAG?", depth="fast"
        )
        await db.commit()
        yield db, row


# ── The authoritative bytes are untouched ─────────────────────────────────────────


async def test_the_stored_markdown_is_the_exact_bytes_that_were_passed_in(run):
    db, row = run
    await run_lifecycle.record_revision(db, row, report_markdown=REPORT)
    await db.commit()

    revision = (await db.execute(Revision.__table__.select())).mappings().one()
    assert revision["report_markdown"] == REPORT, "the report was reshaped on the way in"


async def test_the_report_hash_is_still_sha256_of_the_markdown(run):
    """The load-bearing one. `reviews.reviewed_hash`, `research_artifacts.artifact_hash`
    and the bundle verifier's approval-chain check all pin this value, so a hash taken over
    anything else would invalidate artifacts approved before this change."""
    db, row = run
    await run_lifecycle.record_revision(db, row, report_markdown=REPORT)
    await db.commit()

    revision = (await db.execute(Revision.__table__.select())).mappings().one()
    assert revision["report_hash"] == hashlib.sha256(REPORT.encode()).hexdigest()


async def test_the_hash_does_not_depend_on_the_derived_document(run):
    """Two reports whose typed views differ but whose bytes are identical must hash the
    same — which is only guaranteed while the document is downstream of the hash."""
    db, row = run
    first = await run_lifecycle.record_revision(db, row, report_markdown=REPORT)
    second = await run_lifecycle.record_revision(db, row, report_markdown=REPORT)
    await db.commit()

    rows = (await db.execute(Revision.__table__.select())).mappings().all()
    assert len({r["report_hash"] for r in rows}) == 1
    assert first.revision.version != second.revision.version


# ── The typed view rides alongside ────────────────────────────────────────────────


async def test_a_new_revision_stores_a_document_that_parses_back(run):
    db, row = run
    await run_lifecycle.record_revision(db, row, report_markdown=REPORT)
    await db.commit()

    revision = (await db.execute(Revision.__table__.select())).mappings().one()
    doc = ReportDocument(**revision["report_document"])
    assert doc.blocks, "no typed view was stored"
    assert doc.metadata.run_id == str(row.id)
    assert doc.metadata.revision_version == revision["version"]
    assert doc.metadata.question == "What is RAG?"


async def test_the_stored_document_records_its_fidelity_to_the_stored_markdown(run):
    """`EXACT` is not a success condition — what matters is that the relationship is
    recorded rather than assumed, so no reader mistakes the view for its source."""
    db, row = run
    await run_lifecycle.record_revision(db, row, report_markdown=REPORT)
    await db.commit()

    revision = (await db.execute(Revision.__table__.select())).mappings().one()
    doc = ReportDocument(**revision["report_document"])
    assert doc.render_fidelity in {"EXACT", "LOSSY"}

    from research_engine.document import render_markdown

    matches = render_markdown(doc) == revision["report_markdown"]
    assert (doc.render_fidelity == "EXACT") is matches, "recorded fidelity is not the truth"


async def test_claims_are_still_extracted_from_the_markdown_not_the_document(run):
    """Claim extraction is untouched by A7: the `claims` table is the one home for claims,
    and the document carries markers only. Duplicating claims into blocks would create two
    representations that will eventually disagree."""
    db, row = run
    result = await run_lifecycle.record_revision(db, row, report_markdown=REPORT)
    await db.commit()

    from research_engine import claims as claim_rules

    assert result.claim_count == len(claim_rules.claim_lines(REPORT))


async def test_a_revision_predating_the_typed_view_still_works(run):
    """NULL is the honest record for a revision written before the column existed, and
    nothing may require the document to be present."""
    db, row = run
    await run_lifecycle.record_revision(db, row, report_markdown=REPORT)
    await db.commit()

    await db.execute(Revision.__table__.update().values(report_document=None))
    await db.commit()

    revision = (await db.execute(Revision.__table__.select())).mappings().one()
    assert revision["report_document"] is None
    assert revision["report_markdown"] == REPORT
    assert revision["report_hash"] == hashlib.sha256(REPORT.encode()).hexdigest()
