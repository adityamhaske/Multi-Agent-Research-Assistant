"""
Bundle equivalence: does the V2 representation say the same thing V1 said? (M2E §"Bundle
equivalence").

The V1 bundle is assembled from `sessions` + `audit_log` + the LangGraph checkpoint, exactly
as `app/api/v1/research.py::export_bundle_json` does. The V2 bundle is assembled from the
migrated domain tables. Both go through the same `research_engine.bundle.assemble`, so any
difference is a difference in the *data*, not in the format.

**Three independent gates, never combined into one verdict** (M2F Amendment §10). A bundle
can be *equivalent but invalid* — the entire M2E-2 corpus was, because its approval hashes were
placeholders — *valid but intentionally lossy*, or *not comparable* and still required to be
non-fabricated. No two of the three imply the third.

| | Gate | Question | Lives in |
|---|---|---|---|
| **A** | fidelity | does V2 say what V1 said? | `compare_run` |
| **B** | validity | does each bundle pass `verify_bundle` on its own terms? | `check_validity` |
| **C** | non-fabrication | is every migrated fact traceable to V1? | `migration/provenance.py` |

**What a match does and does not mean.** `BUNDLE_EQUIVALENT` means one thing only:

    the V1 representation and the V2 representation are the same

It does **not** mean the historical V1 evidence was truthful, that its citations resolved,
that its claims were correct, or that any attestation was valid. Those are properties of the
run; this is a property of the migration. Conflating them is precisely the "false
measurement" failure this repository treats as P0 (AGENTS.md), so the vocabulary is kept
apart: `BUNDLE_EQUIVALENT` is about *representation fidelity*.

**Only two fields are normalised, and both are properties of the act of assembling rather
than of the run:**

* `created_at` — the wall-clock at which `assemble()` was called. Different by construction.
* `bundle_hash` — a digest over every other field including `created_at`, so it cannot
  agree while `created_at` disagrees. Recomputed over the normalised dict on both sides, so
  it still detects any difference in the fields that *are* compared.

Nothing else is normalised. A mismatch anywhere else is reported as a mismatch, named field
by field, and never smoothed away.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import v2_bundle
from app.models.agent_log import AgentLog
from app.models.audit_log import AuditLog
from app.models.research import ResearchRun
from app.models.revision import Revision
from app.models.session import Session, SessionStatus
from migration.checkpoint import CheckpointOutcome, read_checkpoint
from migration.ledger import MigrationLedger
from research_engine import bundle as bundle_mod
from research_engine import verify_bundle

#: The only fields normalised before comparison. See the module docstring.
NORMALISED_FIELDS = ("created_at", "bundle_hash")


#: Field sets that differ for a **known, named** reason — a V2 column that does not exist,
#: not a migration defect. Keyed by the differing fields with `bundle_hash` removed, since
#: the digest moves with any field and never identifies one.
#:
#: A mismatch whose field set is not in here is `UNCLASSIFIED`, and the dry run fails on it.
#: That is the point: "never silently ignore mismatches" means an unrecognised difference
#: must be louder than a recognised one, not quieter.
KNOWN_LOSSY: dict[frozenset[str], str] = {
    # NOT a V2 gap. `sources[].snippet(s)` is derived data: `_number_sources` computes it
    # from evidence, `verify_bundle` never reads it, and the frontend treats it as a
    # rendering helper. The V2 bundle rebuilds it by replaying that derivation, so a
    # difference means the V1 snapshot no longer agrees with the evidence it was computed
    # from — a V1 inconsistency, which its own `claim_evidence_linkage` check also fails
    # (M2F §9.1). Named for what it detects, not for what M2E-3 first assumed.
    frozenset({"sources"}): "V1_SOURCE_SNAPSHOT_DIVERGED_FROM_EVIDENCE",
}


#: Re-exported from the shared assembler, which is now its one definition. An assignment
#: rather than an import so it survives an unused-import sweep: the comparison's
#: invertibility test reads it from here, and the value must be the same object the bundle
#: is actually built with.
REVIEW_TO_V1_ACTION = v2_bundle.REVIEW_TO_V1_ACTION


class BundleVerdict(enum.StrEnum):
    BUNDLE_EQUIVALENT = "BUNDLE_EQUIVALENT"
    BUNDLE_MISMATCH = "BUNDLE_MISMATCH"
    #: One side could not be assembled at all. Never silently folded into either of the
    #: other two, and never reported without saying which side and why.
    NOT_COMPARABLE = "NOT_COMPARABLE"


class V1Reason(enum.StrEnum):
    """Could V1 itself have exported a bundle for this run?"""

    EXPORTABLE = "V1_EXPORTABLE"
    #: `export_bundle_json` refuses anything but COMPLETED.
    STATUS_NOT_COMPLETED = "V1_STATUS_NOT_COMPLETED"
    NO_REPORT = "V1_NO_REPORT"
    CHECKPOINT_MISSING = "V1_CHECKPOINT_MISSING"
    CHECKPOINT_UNREADABLE = "V1_CHECKPOINT_UNREADABLE"


class V2Reason(enum.StrEnum):
    """Does V2 hold a comparable representation?"""

    PRESENT = "V2_PRESENT"
    #: The migration refused or failed the run — INCONSISTENT_V1 or FAILED in the ledger.
    RUN_ABSENT = "V2_RUN_ABSENT"
    NO_REVISION = "V2_NO_REVISION"
    #: The ledger says the checkpoint could not be read, so zero evidence rows is unknown
    #: rather than measured (M2F Amendment §9.2).
    EVIDENCE_UNAVAILABLE = "V2_EVIDENCE_UNAVAILABLE"


@dataclass
class BundleComparison:
    """Gate A. Two reason **sets**, evaluated independently and reported in full.

    Not one enum. A run can be both non-COMPLETED and report-less, and can *also* be absent
    from V2 — and the previous single-reason form returned at the first match, so 12 of 48
    not-comparable runs reported a V1 property while the material fact was that the
    migration had refused them (M2F §9.2).
    """

    session_id: str
    verdict: BundleVerdict
    #: Every applicable reason on each axis, sorted. Never empty: the "nothing is wrong"
    #: case is an explicit `V1_EXPORTABLE` / `V2_PRESENT`, so there is no generic bucket.
    v1_reasons: list[str] = field(default_factory=list)
    v2_reasons: list[str] = field(default_factory=list)
    #: Field names that differ, in bundle-manifest order. Empty iff EQUIVALENT.
    differing_fields: list[str] = field(default_factory=list)
    #: `field -> (v1, v2)`, truncated. Diagnosis, never a place to stash a whole report.
    detail: dict[str, tuple[str, str]] = field(default_factory=dict)
    #: For a mismatch: the named limitation that explains it, or `UNCLASSIFIED`.
    limitation: str | None = None

    @property
    def comparable(self) -> bool:
        return self.verdict is not BundleVerdict.NOT_COMPARABLE


@dataclass
class Validity:
    """Gate B, for one side. `passed is None` means *not measured*, never *failed*."""

    assembled: bool
    passed: bool | None = None
    failed_checks: list[str] = field(default_factory=list)


@dataclass
class RunValidation:
    """Gates A and B for one run, kept apart. Gate C is corpus-wide by construction."""

    session_id: str
    fidelity: BundleComparison
    validity_v1: Validity
    validity_v2: Validity


def _clip(value: Any, n: int = 240) -> str:
    text = repr(value)
    return text if len(text) <= n else text[:n] + f"…(+{len(text) - n})"


def _normalise(manifest: bundle_mod.BundleManifest) -> dict:
    """Blank the two assembly-time fields, then recompute the hash over what is left."""
    d = manifest.model_dump()
    d["created_at"] = ""
    d["bundle_hash"] = ""
    d["bundle_hash"] = bundle_mod.compute_bundle_hash(bundle_mod.BundleManifest.model_validate(d))
    return d


# ── V1 side ───────────────────────────────────────────────────────────────────────


async def assemble_v1(
    db: AsyncSession, saver, session: Session
) -> tuple[bundle_mod.BundleManifest | None, str | None]:
    """Rebuild the bundle the V1 server would have exported for this session.

    Mirrors `export_bundle_json` field for field, with one deliberate difference: the
    checkpoint is read through the tri-state reader, so a missing or unreadable snapshot
    yields NOT_COMPARABLE rather than an empty evidence list (M2E §0.1).
    """
    report = session.final_report or session.draft_report
    if not report:
        return None, "V1_NO_REPORT"

    read = await read_checkpoint(saver, str(session.id))
    if read.outcome is CheckpointOutcome.MISSING:
        return None, "V1_CHECKPOINT_MISSING"
    if read.outcome is CheckpointOutcome.UNREADABLE:
        return None, "V1_CHECKPOINT_UNREADABLE"

    audit_logs = (
        (
            await db.execute(
                select(AuditLog)
                .where(AuditLog.session_id == session.id)
                .order_by(AuditLog.id.asc())
            )
        )
        .scalars()
        .all()
    )
    approval_chain = [
        {
            "action": row.action,
            "feedback": row.feedback,
            "draft_hash": row.draft_hash,
            "timestamp": row.created_at.isoformat(),
        }
        for row in audit_logs
    ]

    return (
        bundle_mod.assemble(
            session_id=str(session.id),
            query=session.prompt,
            report=report,
            evidence=read.evidence,
            sources=session.sources or [],
            contradictions=read.contradictions,
            models=session.model_routing or {},
            cost_usd=float(session.total_cost_usd),
            tokens_input=session.total_tokens_input,
            tokens_output=session.total_tokens_output,
            elapsed_seconds=float(session.elapsed_seconds) if session.elapsed_seconds else None,
            research_depth=session.research_depth,
            approval_chain=approval_chain,
            trace=await _trace(db, session.id),
            trace_available=True,
            demo=session.demo,
        ),
        None,
    )


async def _trace(db: AsyncSession, run_id) -> list[dict]:
    """`agent_logs` is not migrated — it is the same table for both sides (M2E §1)."""
    rows = (
        (
            await db.execute(
                select(AgentLog).where(AgentLog.session_id == run_id).order_by(AgentLog.id.asc())
            )
        )
        .scalars()
        .all()
    )
    return [row.payload for row in rows]


# ── V2 side ───────────────────────────────────────────────────────────────────────


async def assemble_v2(
    db: AsyncSession, run_id
) -> tuple[bundle_mod.BundleManifest | None, str | None]:
    """The V2 side of the comparison — the same assembler the native runtime freezes.

    Delegates to `app.v2_bundle` rather than holding a second copy: if the two ever
    disagreed, "the migration produces the same bundle the product does" would stop being a
    measurement and become a coincidence.
    """
    return await v2_bundle.assemble_with_reason(db, run_id)


# ── Comparison ────────────────────────────────────────────────────────────────────


async def _v1_axis(db: AsyncSession, saver, session: Session) -> set[str]:
    """Every reason V1 itself could not have exported a bundle. All of them, not the first."""
    reasons: set[str] = set()
    if session.status != SessionStatus.COMPLETED:
        reasons.add(V1Reason.STATUS_NOT_COMPLETED)
    if not (session.final_report or session.draft_report):
        reasons.add(V1Reason.NO_REPORT)

    read = await read_checkpoint(saver, str(session.id))
    if read.outcome is CheckpointOutcome.MISSING:
        reasons.add(V1Reason.CHECKPOINT_MISSING)
    elif read.outcome is CheckpointOutcome.UNREADABLE:
        reasons.add(V1Reason.CHECKPOINT_UNREADABLE)

    return reasons or {V1Reason.EXPORTABLE}


async def _v2_axis(db: AsyncSession, run_id) -> set[str]:
    """Every reason V2 holds no comparable representation.

    Reads `migration_ledger` for the evidence-availability contract (M2F Amendment §9.2):
    **absence of a ledger row means the run is V2-native**, so its evidence rows are the
    complete record and zero of them is a measured zero. Only a ledger row saying the
    checkpoint could not be read makes the count unknown.
    """
    reasons: set[str] = set()
    run = (
        await db.execute(select(ResearchRun).where(ResearchRun.id == run_id))
    ).scalar_one_or_none()
    if run is None:
        reasons.add(V2Reason.RUN_ABSENT)
        return reasons

    revision = (
        (
            await db.execute(
                select(Revision).where(Revision.run_id == run_id).order_by(Revision.version.desc())
            )
        )
        .scalars()
        .first()
    )
    if revision is None:
        reasons.add(V2Reason.NO_REVISION)

    ledger = (
        await db.execute(select(MigrationLedger).where(MigrationLedger.session_id == run_id))
    ).scalar_one_or_none()
    if ledger is not None and ledger.evidence_outcome in {
        "CHECKPOINT_MISSING",
        "CHECKPOINT_UNREADABLE",
    }:
        reasons.add(V2Reason.EVIDENCE_UNAVAILABLE)

    return reasons or {V2Reason.PRESENT}


# ── Gate A: representational fidelity ─────────────────────────────────────────────


async def compare_run(db: AsyncSession, saver, session: Session) -> BundleComparison:
    """Assemble both sides and compare. Never returns a verdict it did not measure."""
    sid = str(session.id)
    v1_reasons = await _v1_axis(db, saver, session)
    v2_reasons = await _v2_axis(db, session.id)
    axes = {
        "v1_reasons": sorted(str(r) for r in v1_reasons),
        "v2_reasons": sorted(str(r) for r in v2_reasons),
    }

    # Comparable only when *nothing* is wrong on either axis. Both sets are explicit, so a
    # run never lands in an unexplained bucket.
    if v1_reasons != {V1Reason.EXPORTABLE} or v2_reasons != {V2Reason.PRESENT}:
        return BundleComparison(sid, BundleVerdict.NOT_COMPARABLE, **axes)

    v1, _ = await assemble_v1(db, saver, session)
    v2, _ = await assemble_v2(db, session.id)
    if v1 is None or v2 is None:  # pragma: no cover — the axes already excluded this
        return BundleComparison(sid, BundleVerdict.NOT_COMPARABLE, **axes)

    left, right = _normalise(v1), _normalise(v2)
    differing = [k for k in left if left[k] != right[k]]
    if not differing:
        return BundleComparison(sid, BundleVerdict.BUNDLE_EQUIVALENT, **axes)

    substantive = frozenset(differing) - {"bundle_hash"}
    return BundleComparison(
        sid,
        BundleVerdict.BUNDLE_MISMATCH,
        **axes,
        differing_fields=differing,
        detail={k: (_clip(left[k]), _clip(right[k])) for k in differing if k != "bundle_hash"},
        limitation=KNOWN_LOSSY.get(substantive, "UNCLASSIFIED"),
    )


# ── Gate B: internal bundle validity ──────────────────────────────────────────────


def _validity(manifest) -> Validity:
    """Run the shipped standalone verifier over one bundle.

    Deliberately the same `verify_bundle` a third party runs, imported rather than
    reimplemented: a private copy of the checks would verify the migration against the
    migration's own idea of validity.
    """
    if manifest is None:
        # Not measured. `passed` stays None — a bundle that could not be assembled has not
        # failed verification, and recording False would be the unmeasured-became-zero
        # error one layer up.
        return Validity(assembled=False)
    result = verify_bundle.verify(manifest)
    return Validity(
        assembled=True,
        passed=result.passed,
        failed_checks=sorted(c.name for c in result.checks if not c.passed),
    )


async def check_validity(db: AsyncSession, saver, session: Session) -> tuple[Validity, Validity]:
    """Gate B for both sides.

    The V1 side is **diagnostic, not a pass/fail for the migration**: a V1 bundle that never
    verified is a V1 fact, and blocking on it would make the migration hostage to historical
    defects it did not cause. What matters is the pairing — V1 valid and V2 invalid is a
    migration defect; both invalid is inherited; V2 valid where V1 was not is suspicious.
    """
    v1, _ = await assemble_v1(db, saver, session)
    v2, _ = await assemble_v2(db, session.id)
    return _validity(v1), _validity(v2)


async def validate_run(db: AsyncSession, saver, session: Session) -> RunValidation:
    """Gates A and B for one run, reported as separate fields and never combined."""
    fidelity = await compare_run(db, saver, session)
    validity_v1, validity_v2 = await check_validity(db, saver, session)
    return RunValidation(
        session_id=str(session.id),
        fidelity=fidelity,
        validity_v1=validity_v1,
        validity_v2=validity_v2,
    )
