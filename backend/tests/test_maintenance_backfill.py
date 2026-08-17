"""
Backfilling `citation_resolution_rate` on sessions finished before it existed
(docs/07 §2, Phase 7).

Migration 0015 added the column with no default and no backfill, deliberately: it is
recorded at finalize from a live outcome, and inventing a number in a migration is the
thing the column exists to avoid. But every session that completed before it landed
therefore reads "Not measured", which is honest and also means History's new filter is
empty until new runs accumulate. This recomputes it from what was already stored.

The rule it must not break: **a report with no citable claims stays NULL.** Backfilling
is allowed to fill in a measurement that was never taken; it is not allowed to invent one
that cannot be taken.
"""

from __future__ import annotations

from app.maintenance import BackfillPlan, plan_backfill
from app.models.session import Session, SessionStatus

SOURCES = [{"index": 1, "url": "https://a"}, {"index": 2, "url": "https://b"}]


def _session(**kw) -> Session:
    row = Session(prompt="q", research_depth="fast")
    row.status = kw.pop("status", SessionStatus.COMPLETED)
    row.final_report = kw.pop("final_report", "A claim [1].")
    row.sources = kw.pop("sources", SOURCES)
    row.citation_resolution_rate = kw.pop("citation_resolution_rate", None)
    return row


def test_a_completed_report_with_citations_gets_its_rate():
    plan = plan_backfill([_session(final_report="A [1]. B [3].")])
    assert plan == [BackfillPlan(index=0, rate=0.5)]


def test_a_report_that_cited_nothing_is_left_unmeasured():
    """The rule. `None` here means "there was nothing to measure", and writing 0.0 would
    turn that into "every marker failed" — the opposite finding, invented by a script."""
    plan = plan_backfill([_session(final_report="Prose with no markers.")])
    assert plan == [], "an uncited report must not be given a number"


def test_an_existing_measurement_is_never_overwritten():
    """Idempotent, and more importantly non-destructive: a rate recorded at finalize was
    computed against the outcome, and recomputing from a stored report is second-hand."""
    plan = plan_backfill([_session(citation_resolution_rate=1.0, final_report="A [1]. B [3].")])
    assert plan == []


def test_only_completed_sessions_are_touched():
    """A draft is not a report. Measuring one would publish a number for text no human
    has approved, and the rate would then change under the reader on approval."""
    for status in (SessionStatus.RUNNING, SessionStatus.AWAITING_PLAN, SessionStatus.FAILED):
        assert plan_backfill([_session(status=status)]) == [], status


def test_a_completed_session_with_no_report_is_skipped():
    assert plan_backfill([_session(final_report=None)]) == []
    assert plan_backfill([_session(final_report="")]) == []


def test_a_report_whose_markers_all_dangle_records_zero_not_null():
    """The other side of the rule: 0.0 is a real measurement and must be written. A
    report citing [1] with no sources at all is exactly the failure the product surfaces
    with ⚠ chips, and it has to be findable in History rather than hidden as unmeasured.
    """
    plan = plan_backfill([_session(final_report="A claim [1].", sources=[])])
    assert plan == [BackfillPlan(index=0, rate=0.0)]


def test_the_plan_reports_indices_so_a_dry_run_can_be_read_before_writing():
    rows = [
        _session(final_report="no markers"),
        _session(final_report="A [1]."),
        _session(citation_resolution_rate=0.25),
    ]
    assert plan_backfill(rows) == [BackfillPlan(index=1, rate=1.0)]
