"""
Gate C — historical non-fabrication, made mechanical (M2F Amendment §10, §11, M7).

> Migration may transform, normalize, or recover information demonstrably present in V1,
> but must never manufacture historical facts to satisfy V2 constraints.

A principle nothing checks becomes a slogan. This module turns it into a declaration that
the build enforces: **every column `migration/engine.py` writes must be declared here**, as
exactly one of four kinds.

| Kind | Means |
|---|---|
| `FROM(expr)` | read from a named V1 location |
| `DERIVED(expr)` | a pure function of V1 data |
| `CONST(value, why)` | a fixed value, with the reason V1 could not supply one |
| `NULL(why)` | deliberately absent |

Two checks run against it, and both are needed:

* **Structural** (`undeclared_columns` / `stale_declarations`) — the set of columns the engine
  supplies is read out of its own AST, so adding a column to an `insert()` without declaring
  its provenance fails, and a declaration that no longer describes reality fails too. Neither
  list can quietly become a description of the past.
* **Runtime** (`constant_violations`) — every `CONST` is verified against the rows actually
  written. A declaration that says `provenance_state='UNCHECKED'` while the engine writes
  `ATTESTED` is a lie the structural check cannot see.

The AST is read rather than the runtime call recorded, because a column added inside a branch
that the dry-run corpus never exercises is exactly the one that would slip through.
"""

from __future__ import annotations

import ast
import enum
import pathlib
from dataclasses import dataclass

ENGINE_PATH = pathlib.Path(__file__).with_name("engine.py")


class Kind(enum.StrEnum):
    FROM = "FROM"
    DERIVED = "DERIVED"
    CONST = "CONST"
    NULL = "NULL"


@dataclass(frozen=True)
class Provenance:
    kind: Kind
    #: For FROM/DERIVED: the V1 expression. For CONST: a human-readable rendering.
    expr: str
    #: Why this kind was the honest choice. Required for CONST and NULL.
    reason: str = ""
    #: For CONST only: the value every migrated row must actually carry.
    value: object = None


def FROM(expr: str) -> Provenance:
    return Provenance(Kind.FROM, expr)


def DERIVED(expr: str) -> Provenance:
    return Provenance(Kind.DERIVED, expr)


def CONST(value: object, reason: str) -> Provenance:
    return Provenance(Kind.CONST, repr(value), reason, value)


def NULL(reason: str) -> Provenance:
    return Provenance(Kind.NULL, "NULL", reason)


#: Model class name → table name, for reading the engine's `insert(Model)` calls.
MODEL_TABLES = {
    "ResearchRun": "research_runs",
    "ResearchPlan": "research_plans",
    "Source": "sources",
    "Evidence": "evidence",
    "Contradiction": "contradictions",
    "Revision": "revisions",
    "Claim": "claims",
    "ClaimEvidenceLink": "claim_evidence_links",
    "Review": "reviews",
    "AuditEvent": "audit_events",
}


# ── The declaration ───────────────────────────────────────────────────────────────
#
# Read this as the answer to "where did this value come from?" for every field the
# migration writes. Anything that cannot be answered in one of the four kinds is a fact the
# migration would be inventing, and must become a refusal instead.

PROVENANCE: dict[str, dict[str, Provenance]] = {
    "research_runs": {
        "id": FROM("sessions.id"),
        "project_id": FROM("sessions.project_id"),
        "owner_id": FROM("sessions.user_id"),
        "question": FROM("sessions.prompt"),
        "status": DERIVED("STATUS_MAP[sessions.status] — AWAITING_APPROVAL→AWAITING_REVIEW"),
        "depth": FROM("sessions.research_depth"),
        "corpus_mode": FROM("sessions.corpus_mode"),
        "demo": FROM("sessions.demo"),
        "skip_plan_gate": FROM("sessions.skip_plan_gate"),
        "topic_seeds": FROM("sessions.topic_seeds"),
        "outline_template": FROM("sessions.outline_template"),
        "model_routing": FROM("sessions.model_routing"),
        "cost_usd": FROM("sessions.total_cost_usd"),
        "tokens_input": FROM("sessions.total_tokens_input"),
        "tokens_output": FROM("sessions.total_tokens_output"),
        "elapsed_seconds": FROM("sessions.elapsed_seconds"),
        "citation_resolution_rate": FROM("sessions.citation_resolution_rate — NULL stays NULL"),
        "error_message": FROM("sessions.error_message"),
        "cancelled_at": NULL(
            "V1 records a user cancellation as FAILED with a message. A message is not a "
            "contract, so cancellation is never inferred (M2E §0.2)"
        ),
        "cancel_requested_by": NULL("same as cancelled_at"),
        "archived_at": FROM("sessions.archived_at"),
        "created_at": FROM("sessions.created_at"),
        "updated_at": FROM("sessions.updated_at"),
    },
    "research_plans": {
        "id": DERIVED("uuid5(NS, 'plan|run_id|1')"),
        "run_id": FROM("sessions.id"),
        "version": CONST(1, "V1 overwrote plan_json in place; only one version survives"),
        "tasks": FROM("sessions.plan_json['tasks']"),
        "outline_sections": FROM("sessions.outline_json['sections']"),
        "origin": CONST(
            "UNKNOWN",
            "V1 overwrote the model's proposal with the approved plan, so which one this "
            "is cannot be known (M2E §2)",
        ),
        "approved_at": FROM("sessions.plan_approved_at"),
        "created_at": FROM("sessions.created_at"),
    },
    "sources": {
        "id": DERIVED("uuid5(NS, 'source|run_id|normalized_url')"),
        "run_id": FROM("sessions.id"),
        "url": FROM("sessions.sources[i].url"),
        "normalized_url": DERIVED("_norm_url(sessions.sources[i].url)"),
        "title": FROM("sessions.sources[i].title"),
        "kind": DERIVED("'CORPUS' if url startswith corpus:// else 'WEB'"),
        "retrieval_status": CONST(
            "UNKNOWN",
            "V1 never recorded whether a page was fetched or only seen in a search result",
        ),
        "citation_index": FROM("sessions.sources[i].index"),
        "corpus_document_id": DERIVED("url after the corpus:// prefix, else NULL"),
        "retrieved_at": FROM("sessions.created_at — V1 kept no per-source retrieval time"),
    },
    "evidence": {
        "id": DERIVED("uuid5(NS, 'evidence|run_id|position')"),
        "run_id": FROM("sessions.id"),
        "source_id": DERIVED("the sources row whose normalized_url matches this item's"),
        "sequence": DERIVED("1-based position in checkpoint state['evidence']"),
        "task_id": FROM("checkpoint evidence[i].task_id"),
        "snippet": FROM("checkpoint evidence[i].snippet — verbatim, empty included"),
        "content_hash": DERIVED("sha256(snippet)"),
        "key_fact": FROM("checkpoint evidence[i].key_fact"),
        "provenance_state": CONST(
            "UNCHECKED",
            "V1's snippet check is skipped in fake mode, records nothing per item, and "
            "blanks the snippet on failure rather than flagging it. 'Verification usually "
            "ran' is not 'verification ran for this item' (M2E §4)",
        ),
        "attested_against": NULL("no attestation was recorded, so no grade can be claimed"),
        "attestation_run_at": NULL("required NULL by ck_ev_unchecked when UNCHECKED"),
        "created_at": FROM("sessions.created_at"),
    },
    "contradictions": {
        "id": DERIVED("uuid5(NS, 'contradiction|run_id|position')"),
        "run_id": FROM("sessions.id"),
        "evidence_a_id": NULL(
            "V1 keys the pair by source URL, not by evidence id. Resolving it is M2F/F4; "
            "until then the reference is absent rather than guessed"
        ),
        "evidence_b_id": NULL("same as evidence_a_id"),
        "summary_a": FROM("checkpoint contradictions[j].claim_a"),
        "summary_b": FROM("checkpoint contradictions[j].claim_b"),
        "dimension": CONST("UNCLASSIFIED", "V1's detector records no dimension"),
        "detection_state": CONST(
            "NOT_RUN",
            "ck_contra_pair forbids DETECTED without both evidence references, and V1 "
            "recorded none. Revised by M2F/S4; NOT_RUN is what is storable today",
        ),
        "review_state": CONST("UNREVIEWED", "V1 has no contradiction review workflow"),
        "created_at": FROM("sessions.created_at"),
    },
    "revisions": {
        "id": DERIVED("uuid5(NS, 'revision|run_id|1')"),
        "run_id": FROM("sessions.id"),
        "version": CONST(
            1, "superseded drafts were overwritten in place by V1 and are gone (M2E §3)"
        ),
        "report_markdown": FROM("sessions.final_report or sessions.draft_report"),
        "report_hash": DERIVED("sha256(report_markdown)"),
        "evidence_watermark": DERIVED("max(evidence.sequence) for the run, else 0"),
        "created_at": FROM("sessions.updated_at, falling back to created_at"),
    },
    "claims": {
        "id": DERIVED("uuid5(NS, 'claim|run_id|1|position')"),
        "revision_id": DERIVED("the run's single migrated revision"),
        "run_id": FROM("sessions.id"),
        "position": DERIVED("index in research_engine.claims.claim_lines(report)"),
        "text": DERIVED("research_engine.claims.claim_lines(report)[position]"),
        "extraction_method": CONST(
            "DERIVED_FROM_REPORT",
            "the claims are produced by today's extractor from V1 prose, and the field "
            "says so rather than implying the model emitted them",
        ),
        "verification_state": CONST("UNCHECKED", "V1 ran no per-claim verification"),
        "verification_method": CONST("NOT_RUN", "required by ck_claim_unchecked"),
        "lineage_id": NULL(
            "nothing in V1 observed that a sentence in one revision IS the assertion from "
            "another. Matching by text would manufacture a relationship (M2A §13.3)"
        ),
        "created_at": FROM("sessions.created_at"),
    },
    "claim_evidence_links": {
        "id": DERIVED("uuid5(NS, 'link|run_id|1|position|marker)"),
        "run_id": FROM("sessions.id"),
        "claim_id": DERIVED("the claim this citation marker was found in"),
        "evidence_id": DERIVED("first evidence row for the source at that citation index"),
        "stance": CONST(
            "SUPPORTS",
            "a V1 [n] marker asserts support and nothing else; V1 had no way to express "
            "a contradicting or contextual citation",
        ),
        "origin": CONST(
            "CITATION_MARKER",
            "the link came from a typographic marker rather than a considered judgement, "
            "and says so",
        ),
        "created_at": FROM("sessions.created_at"),
    },
    "reviews": {
        "id": DERIVED("uuid5(NS, 'review|run_id|audit_log.id')"),
        "revision_id": DERIVED("the run's single migrated revision"),
        "reviewer_id": FROM("audit_log.user_id"),
        "plan_version_id": DERIVED("the migrated plan, for PLAN-gate rows only"),
        "gate": DERIVED("AUDIT_MAP[audit_log.action][0]"),
        "decision": DERIVED("AUDIT_MAP[audit_log.action][1]"),
        "feedback": FROM("audit_log.feedback"),
        "reviewed_hash": FROM("audit_log.draft_hash — opaque at the PLAN gate"),
        "created_at": FROM("audit_log.created_at"),
    },
    "audit_events": {
        "actor_id": FROM("audit_log.user_id"),
        "action": DERIVED("AUDIT_MAP[audit_log.action][2]"),
        "subject_type": CONST("research_run", "every migrated event is about a run"),
        "subject_id": FROM("sessions.id"),
        "metadata_json": DERIVED("{'v1_audit_log_id': audit_log.id}"),
        "occurred_at": FROM("audit_log.created_at"),
    },
}


# ── Structural check: what the engine actually writes ─────────────────────────────


def written_columns(path: pathlib.Path | None = None) -> dict[str, set[str]]:
    """Read `engine.py`'s AST and return `{table: {column, ...}}` it supplies.

    Static rather than instrumented on purpose: a column added inside a branch the dry-run
    corpus never exercises is precisely the one a runtime recorder would miss.
    """
    tree = ast.parse((path or ENGINE_PATH).read_text(encoding="utf-8"))
    found: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        # Matches `insert(Model).values(col=..., ...)`.
        if not isinstance(node, ast.Call):
            continue
        if not (isinstance(node.func, ast.Attribute) and node.func.attr == "values"):
            continue
        inner = node.func.value
        if not (isinstance(inner, ast.Call) and isinstance(inner.func, ast.Name)):
            continue
        if inner.func.id != "insert" or not inner.args:
            continue
        target = inner.args[0]
        if not isinstance(target, ast.Name):
            continue
        table = MODEL_TABLES.get(target.id)
        if table is None:
            continue
        found.setdefault(table, set()).update(kw.arg for kw in node.keywords if kw.arg is not None)
    return found


def undeclared_columns(path: pathlib.Path | None = None) -> list[str]:
    """Columns the engine writes with no provenance declaration. Must be empty."""
    out = []
    for table, columns in sorted(written_columns(path).items()):
        declared = PROVENANCE.get(table, {})
        for column in sorted(columns - set(declared)):
            out.append(f"{table}.{column}")
    return out


def stale_declarations(path: pathlib.Path | None = None) -> list[str]:
    """Declarations for columns the engine no longer writes. Must be empty.

    Without this the map becomes a description of a past version of the engine, which is
    the failure mode the host-parity tables were written to avoid.
    """
    written = written_columns(path)
    out = []
    for table, declared in sorted(PROVENANCE.items()):
        actual = written.get(table, set())
        for column in sorted(set(declared) - actual):
            out.append(f"{table}.{column}")
    return out


# ── Runtime check: the constants are really constant ──────────────────────────────

#: Table → the SQLAlchemy model whose rows carry it. Imported lazily by the checker so this
#: module stays importable without the ORM (it is also read by a lint-style test).
_MODEL_IMPORTS = {
    "research_runs": ("app.models.research", "ResearchRun"),
    "research_plans": ("app.models.research", "ResearchPlan"),
    "sources": ("app.models.research", "Source"),
    "evidence": ("app.models.research", "Evidence"),
    "contradictions": ("app.models.research", "Contradiction"),
    "revisions": ("app.models.revision", "Revision"),
    "claims": ("app.models.revision", "Claim"),
    "claim_evidence_links": ("app.models.revision", "ClaimEvidenceLink"),
    "reviews": ("app.models.review", "Review"),
    "audit_events": ("app.models.review", "AuditEvent"),
}


async def constant_violations(db) -> list[str]:
    """Every `CONST` declaration, checked against the rows actually written.

    A structural declaration is a claim about the code; this is the claim about the data.
    Both are needed: the map could say `UNCHECKED` while the engine writes `ATTESTED`, and
    only this would notice.
    """
    import importlib

    from sqlalchemy import func, select

    out: list[str] = []
    for table, columns in sorted(PROVENANCE.items()):
        consts = {c: p for c, p in columns.items() if p.kind is Kind.CONST}
        if not consts:
            continue
        module_name, class_name = _MODEL_IMPORTS[table]
        model = getattr(importlib.import_module(module_name), class_name)
        total = (await db.execute(select(func.count()).select_from(model))).scalar_one()
        if not total:
            continue
        for column, prov in consts.items():
            col = getattr(model, column)
            bad = (
                await db.execute(
                    select(func.count()).select_from(model).where(col.is_distinct_from(prov.value))
                )
            ).scalar_one()
            if bad:
                out.append(f"{table}.{column}: {bad}/{total} rows differ from {prov.expr}")
    return out
