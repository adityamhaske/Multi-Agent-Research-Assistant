# M2E — V1 → V2 Field Mapping (reconnaissance output)

**Status:** Reconnaissance complete. **No migration code written.**
**Gate:** M2E §1 — "Do not start coding until the mapping is understood."
**Derives from:** M2A RFC + Amendment 1, M2B + Amendment 2, M2C plan §13, M2C.5 benchmark,
M2D schema (`eafdf189af24`).

This extends M2C §13 with what inspecting the code actually revealed. Where it contradicts
M2C, the code wins and the difference is called out.

---

## 0. Findings that change the plan

Five things the audit surfaced that M2C §13 did not anticipate.

### 0.1 `checkpoints.get_thread_state` collapses the distinction M2E exists to preserve

```python
snapshot = await graph.aget_state({"configurable": {"thread_id": thread_id}})
return snapshot.values if snapshot else {}
```

A missing checkpoint and a checkpoint whose state is empty **both return `{}`**. That is
precisely the collapse the objective forbids (`CHECKPOINT_MISSING` vs `NONE_PRESENT`).

**Consequence:** the migration must NOT use this helper. It must call `aget_state` itself
and branch on `snapshot is None` before looking at `.values`. The existing helper stays
untouched — it is a production read path and M2E may not alter V1 semantics.

### 0.2 V1 has six statuses; V2 has seven

| V1 | V2 | Note |
|---|---|---|
| `PENDING` → `PENDING` | | direct |
| `RUNNING` → `RUNNING` | | direct |
| `AWAITING_PLAN` → `AWAITING_PLAN` | | direct |
| `AWAITING_APPROVAL` → **`AWAITING_REVIEW`** | | rename only |
| `COMPLETED` → `COMPLETED` | | direct |
| `FAILED` → `FAILED` | | direct, **including user cancellations** |
| — | `CANCELLED` | **never written by migration** |

V1 records a user cancellation as `FAILED` with
`error_message = "Research stopped by user."`. Inferring `CANCELLED` means string-matching
a message that is not a contract. **Not done** (M2E hard boundary; M2C §13.2). `cancelled_at`
stays NULL, satisfying `ck_run_cancelled`.

### 0.3 Only three audit actions exist

Confirmed by grep across `app/` and `desktop/`: `approved`, `rework_requested`,
`plan_approved`. No others are written by any code path. The `Review.gate`/`decision` split
therefore has no unmapped input.

### 0.4 V1 numeric widths are narrower than V2's

| V1 | V2 |
|---|---|
| `total_cost_usd NUMERIC(10,6)` | `cost_usd NUMERIC(12,6)` |
| `total_tokens_input/output INTEGER` | `tokens_input/output BIGINT` |
| `elapsed_seconds NUMERIC(10,2)` | `elapsed_seconds NUMERIC(12,3)` |

All widening. No truncation risk, no transformation needed.

### 0.5 `projects.user_id` is not renamed

M2B §2.1 proposed `owner_id`. M2E may not alter V1 tables, so `projects.user_id` stays as
it is; `research_runs.owner_id` is populated **from** it. The rename is a later milestone's
problem, if ever.

---

## 1. Table-level mapping

| V1 source | V2 destination | Cardinality |
|---|---|---|
| `sessions` | `research_runs` | 1:1 |
| `sessions.draft_report`/`final_report` | `revisions` | 1:**1** — never `rework_count + 1` |
| `sessions.sources` (JSON) | `sources` | 1:N |
| `sessions.plan_json` + `outline_json` | `research_plans` | 1:**1**, `origin='UNKNOWN'` |
| `audit_log` | `reviews` **and** `audit_events` | 1:1 into each |
| checkpoint `state["evidence"]` | `evidence` | 1:N |
| checkpoint `state["contradictions"]` | `contradictions` | 1:N |
| *derived from report* | `claims`, `claim_evidence_links` | 1:N |
| *assembled* | `research_artifacts` | 0..1 per run |
| `memory_chunks` | `project_memory_items` + `_provenance` | 1:1 + link |
| `agent_logs` | unchanged (artifact trace only) | — |
| `sessions.rework_count` | **discarded** — derived | — |
| Redis `session:{id}:cancelled` | **discarded** — write-only, never read | — |
| checkpoint (everything else) | **discarded** — execution state | — |

---

## 2. `sessions` → `research_runs`, field by field

| V1 | V2 | Transformation | Confidence |
|---|---|---|---|
| `id` | `id` | direct | certain |
| `user_id` | `owner_id` | direct | certain |
| `project_id` | `project_id` | direct | certain |
| `prompt` | `question` | direct | certain |
| `status` | `status` | `AWAITING_APPROVAL`→`AWAITING_REVIEW`; else direct | certain |
| `research_depth` | `depth` | direct | certain |
| `corpus_mode`, `demo`, `skip_plan_gate` | same | direct | certain |
| `topic_seeds`, `outline_template` | same | direct | certain |
| `model_routing` | same | direct | certain |
| `total_cost_usd` | `cost_usd` | widen | certain |
| `total_tokens_input`/`output` | `tokens_input`/`output` | widen | certain |
| `elapsed_seconds` | same | widen | certain |
| `citation_resolution_rate` | same | direct, **NULL stays NULL** | certain |
| `error_message` | same | direct | certain |
| `archived_at`, `created_at`, `updated_at` | same | direct | certain |
| — | `cancelled_at`, `cancel_requested_by` | **always NULL** (§0.2) | n/a |
| `rework_count` | — | discarded; `count(revisions)-1` | derived |

---

## 3. Report → `revisions`

| Field | Value |
|---|---|
| `version` | **always 1.** Superseded drafts were overwritten by V1 and are gone. |
| `report_markdown` | `final_report or draft_report` |
| `report_hash` | `sha256(report_markdown)` |
| `evidence_watermark` | `max(evidence.sequence)` for the run, else **0** |

**No revision row when both report columns are NULL** → ledger `revision_outcome = NO_REPORT`.

---

## 4. Checkpoint → `evidence`

| V2 field | Value | Confidence |
|---|---|---|
| `sequence` | list index + 1 (gaps permitted, M2B §9.2) | positional |
| `source_id` | resolved via `normalized_url` within the run | certain where the source list contains it |
| `snippet` | verbatim, **including empty string** | empty stays ambiguous |
| `content_hash` | `sha256(snippet)` | computed |
| `key_fact` | direct | certain |
| `provenance_state` | **`UNCHECKED`** — never `ATTESTED` | see below |
| `attested_against` | **NULL** | required by `ck_ev_grade` |
| `attestation_run_at` | **NULL** | required by `ck_ev_unchecked` |

**Why `UNCHECKED` and never `ATTESTED`.** V1's in-graph check is skipped entirely in fake
mode, records nothing per item, and *blanks* the snippet on failure rather than flagging it.
"Verification usually ran" is not "verification ran for this item". The `ck_ev_unchecked`
CHECK makes the alternative unstorable: an `ATTESTED` row needs `attestation_run_at`, and the
migration has no honest value to put there.

**Evidence whose `source_url` is not in `sessions.sources`** cannot satisfy the composite FK
`(source_id, run_id) → sources(id, run_id)`. Options for §4+ of the spec to settle:
insert a synthetic `sources` row with `retrieval_status='UNKNOWN'`, or record the run as a
partial migration. **Not decided here** — it manufactures a source either way and needs a
ruling.

---

## 5. Report → `claims` / `claim_evidence_links`

| Field | Value |
|---|---|
| `claims.text` | `research_engine.claims.claim_lines(report)` — the M0A canonical extractor |
| `claims.position` | index in that list |
| `extraction_method` | `DERIVED_FROM_REPORT` |
| `verification_state` | `UNCHECKED` |
| `verification_method` | `NOT_RUN` (required by `ck_claim_unchecked`) |
| `lineage_id` | **NULL** — never assigned by matching |
| link `stance` | `SUPPORTS` |
| link `origin` | `CITATION_MARKER` |
| link target | `extract_citations(claim)` → `sources.citation_index` → its evidence |

**Caveat to record in the ledger:** claims are derived by *today's* extractor. Re-deriving
later with a changed extractor yields different claims for the same report. That is a fact
about the migration, not the run — which is why V2 persists them (M2A §3.5).

A citation marker pointing at no source (V1 resolution rate < 1) yields **no link**. It must
not invent one.

---

## 6. `audit_log` → `reviews` + `audit_events`

| V1 `action` | `reviews.gate` | `reviews.decision` | `audit_events.action` |
|---|---|---|---|
| `approved` | `REPORT` | `APPROVED` | `review.approved` |
| `rework_requested` | `REPORT` | `REWORK_REQUESTED` | `review.rework_requested` |
| `plan_approved` | `PLAN` | `APPROVED` | `plan.approved` |

- `draft_hash` → `reviewed_hash`. **Opaque for `PLAN`** — nothing has ever verified it.
- `revision_id` → the single migrated revision. **A run with reviews but no report cannot
  satisfy the NOT NULL FK** → ledger `INCONSISTENT_V1`, not a silent repair.
- `ck_review_hash` requires `length = 64`. A V1 row with a malformed hash is
  `INCONSISTENT_V1`, never padded or regenerated.
- **`uq_review_approval`** allows one approving REPORT review per revision. Two V1
  `approved` rows for one session → `INCONSISTENT_V1`.

---

## 7. Ledger taxonomy (M2C §5, extended)

M2C's four `evidence_outcome` values are insufficient for the states M2E §2 requires. The
additions are marked.

| Column | Values |
|---|---|
| `status` | `NOT_PROCESSED` (implicit — **absence from the ledger**), `IN_PROGRESS` ✚, `MIGRATED`, `MIGRATED_WITH_MISMATCH` ✚, `NOT_APPLICABLE`, `FAILED` ✚ |
| `evidence_outcome` | `COPIED`, `NONE_PRESENT`, `CHECKPOINT_MISSING`, `CHECKPOINT_UNREADABLE`, `READ_FAILURE` ✚ |
| `revision_outcome` | `COPIED`, `NO_REPORT` |
| `artifact_outcome` | `CREATED`, `NOT_APPROVED`, `BLOCKED` |
| `golden_result` | `MATCH`, `MISMATCH`, `NOT_APPLICABLE` |

**Absence from the ledger means `NOT_PROCESSED`. It never means empty.**
`CHECKPOINT_MISSING` (no snapshot) and `NONE_PRESENT` (snapshot with zero evidence) are
distinct rows, and §0.1 is why the existing helper cannot produce that distinction.

`INCONSISTENT_V1` is proposed as a `NOT_APPLICABLE` reason rather than a status, since the
run is not migrated and not retryable without a human decision.

---

## 8. Open decisions requiring the missing spec sections

1. **Orphan evidence** (§4) — synthetic source row vs partial-migration record.
2. **Runs with reviews but no report** (§6) — `INCONSISTENT_V1`, or synthesise nothing and
   drop the review? Dropping loses an approval record, which C3 forbids.
3. **Golden comparison scope** — every approved run, or a sample? M2C §9 says every.
4. **Where the migration runs** — CLI under `backend/`, Alembic data migration, or a
   `bench/`-style script. Affects testability and the desktop story.
5. **Desktop backfill** — M2C §7 requires it at sidecar startup; is that in M2E or deferred?

---

## 9. Status

Reconnaissance complete; mapping understood. **No code written.** Awaiting M2E §4+ (the
message was truncated mid-§3) before implementing.
