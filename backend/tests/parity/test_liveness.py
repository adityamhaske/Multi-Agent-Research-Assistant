"""
The guard against a parity suite that passes because nothing happened.

Two implementations that both return `[]` agree perfectly. Comparing them to a golden
recorded from a run that also returned `[]` agrees perfectly too. Every assertion is
green, the journey is meaningless, and nothing in the harness objects — this is the
subtlest form of the failure `AGENTS.md` records as "a test that stubs the thing it is
testing proves nothing", and the reason it survives is that an empty result is a *valid*
response shape.

So a journey does not merely produce observations; it declares what must be true of them.
The checks are product facts written in the journey's own terms — "the run reached
AWAITING_APPROVAL", "the report carries at least one citation marker", "the document list
was not empty" — and they run against **both** hosts. A journey with no checks is refused
at collection time, so the guard cannot be skipped by omitting it.
"""

from __future__ import annotations

import pytest

from tests.parity.liveness import (
    at_least_one_nonempty_body,
    body_at,
    failing_checks,
    status_at,
)

# One recorded journey, as `drive()` returns it.
OBSERVED = [
    {"step": "create project", "status": 201, "body": {"id": "<uuid>", "name": "Parity"}},
    {"step": "list projects", "status": 200, "body": {"projects": [{"id": "<uuid>"}]}},
    {"step": "list documents", "status": 200, "body": []},
]

EMPTY_BUT_AGREEING = [
    {"step": "list projects", "status": 200, "body": {"projects": []}},
    {"step": "list documents", "status": 200, "body": []},
]


class _J:
    """The two attributes `failing_checks` reads off a journey."""

    def __init__(self, name, checks):
        self.name = name
        self.checks = checks


# ── Accessors journeys write their checks in terms of ─────────────────────────────


def test_body_at_returns_the_body_recorded_for_a_named_step():
    assert body_at(OBSERVED, "create project") == {"id": "<uuid>", "name": "Parity"}


def test_body_at_raises_for_a_step_the_journey_never_reached():
    """A check that silently reads `None` for a missing step is a check that passes when
    the journey broke — the exact failure this module exists to prevent."""
    with pytest.raises(KeyError):
        body_at(OBSERVED, "approve report")


def test_status_at_returns_the_recorded_status():
    assert status_at(OBSERVED, "list projects") == 200


# ── The floor: something, somewhere, was non-empty ────────────────────────────────


def test_a_journey_with_one_populated_body_clears_the_floor():
    assert at_least_one_nonempty_body(OBSERVED) is True


def test_a_journey_whose_successful_bodies_are_all_empty_does_not():
    """Both hosts returning nothing, in agreement, is the case that must fail."""
    assert at_least_one_nonempty_body(EMPTY_BUT_AGREEING) is False


def test_an_empty_nested_collection_does_not_count_as_content():
    assert at_least_one_nonempty_body([{"step": "s", "status": 200, "body": {"runs": []}}]) is False


def test_a_populated_error_body_does_not_count_as_life():
    """A journey that only ever produced 4xx bodies has exercised its error contract, not
    the product. Error-contract journeys declare their own checks instead."""
    observed = [{"step": "s", "status": 409, "body": {"detail": "not AWAITING_APPROVAL"}}]
    assert at_least_one_nonempty_body(observed) is False


# ── Declared product facts ────────────────────────────────────────────────────────


def test_a_journey_whose_declared_checks_hold_reports_no_failures():
    journey = _J(
        "projects",
        (("the project list is not empty", lambda o: body_at(o, "list projects")["projects"]),),
    )
    assert failing_checks(journey, OBSERVED) == []


def test_a_failed_check_is_reported_by_its_label():
    journey = _J(
        "projects", (("the document list is not empty", lambda o: body_at(o, "list documents")),)
    )
    assert failing_checks(journey, OBSERVED) == ["the document list is not empty"]


def test_a_check_that_raises_is_a_failure_not_an_error():
    """A check reading a step the journey never reached has found a real defect. It must
    read as a failed product fact, not as a crash in the harness."""
    journey = _J("projects", (("the report was approved", lambda o: body_at(o, "approve report")),))
    assert failing_checks(journey, OBSERVED) == [
        "the report was approved (raised KeyError: 'approve report')"
    ]


def test_a_journey_that_declares_no_checks_is_itself_a_failure():
    """The guard cannot be opted out of by writing a journey without it."""
    assert failing_checks(_J("silent", ()), OBSERVED) == [
        "journey 'silent' declares no checks — a journey that asserts nothing cannot fail"
    ]
