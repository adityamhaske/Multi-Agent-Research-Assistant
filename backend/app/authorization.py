"""
Artifact authorization — the application layer of a four-layer rule.

> Only an **APPROVED REPORT** review may authorize a `ResearchArtifact`.
> A PLAN approval never can.

The rule is enforced four times, deliberately, because each layer catches what the others
cannot reach:

| Layer | Mechanism | Catches |
|---|---|---|
| database | `fk_artifact_review → reviews(id, decision, gate)` + `ck_artifact_gate` | any writer, including a psql session |
| application | **this module** | a service that queries approvals itself |
| serialization | `run_bundle.REVIEW_TO_BUNDLE_ACTION` | a bundle that renames a plan approval |
| verifier | `verify_bundle._check_approval_chain` | a bundle produced by something else entirely |

The serialization layer is the one that looks redundant and is not. `verify_bundle` treats
`action == "approved"` as report authorization and rejects `plan_approved` — but only
because the session path happens to use a distinct string. An assembler that mapped every APPROVED
review to `"approved"` would satisfy the verifier's load-bearing check in a file no
database constraint reaches.

**Top-level in `app/`, not under `app/services/`**, so the desktop sidecar can import it on
the same terms as the server. A rule with two homes is the failure this repository keeps
rediscovering (AGENTS.md); this is the one home.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.review import Review

#: The gate/decision pair that authorizes an artifact. Not two literals at a call site.
AUTHORIZING_GATE = "REPORT"
AUTHORIZING_DECISION = "APPROVED"


class NotAuthorizing(Exception):
    """A review was offered as an artifact's authorization and is not one."""


def may_authorize_artifact(review: Review) -> bool:
    """True only for an approving review at the report gate."""
    return review.gate == AUTHORIZING_GATE and review.decision == AUTHORIZING_DECISION


async def approving_report_review(db: AsyncSession, run_id: uuid.UUID) -> Review | None:
    """The one review that may authorize this run's artifact, or None.

    `uq_review_approval` allows at most one approving REPORT review per revision, so this
    returns at most one row per revision; ordering by `sequence` makes the choice
    deterministic for a run whose rework loop produced several revisions.
    """
    return (
        (
            await db.execute(
                select(Review)
                .where(
                    Review.run_id == run_id,
                    Review.gate == AUTHORIZING_GATE,
                    Review.decision == AUTHORIZING_DECISION,
                )
                .order_by(Review.sequence.desc())
            )
        )
        .scalars()
        .first()
    )


def artifact_authorization_values(review: Review) -> dict:
    """The three denormalised columns an artifact must carry to prove its authorization.

    Raises rather than returning something the database will reject: a caller that has to
    read the CHECK constraint's error message to learn it passed a plan approval has been
    told too late.
    """
    if not may_authorize_artifact(review):
        raise NotAuthorizing(
            f"review {review.id} is {review.gate}/{review.decision}; an artifact requires "
            f"{AUTHORIZING_GATE}/{AUTHORIZING_DECISION}"
        )
    return {
        "review_id": review.id,
        "review_decision": review.decision,
        "review_gate": review.gate,
    }


async def approval_chain(db: AsyncSession, run_id: uuid.UUID) -> list[Review]:
    """A run's reviews in decision order — both gates, ordered by `sequence`.

    Before `reviews.run_id` existed this query was impossible: PLAN reviews hang off
    `research_plans` and REPORT reviews off `revisions`, so a single-parent read silently
    omitted every plan approval.
    """
    return list(
        (
            await db.execute(
                select(Review).where(Review.run_id == run_id).order_by(Review.sequence.asc())
            )
        )
        .scalars()
        .all()
    )
