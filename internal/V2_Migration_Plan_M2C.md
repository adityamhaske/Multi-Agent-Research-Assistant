# M2C — V1 → V2 Migration Plan

**Status:** Plan for review. **PLAN ONLY — nothing executed.**
**Derives from:** `V2_Domain_Model_RFC.md` (M2A + Amendment 1) and
`V2_Schema_Proposal_M2B.md` (M2B + Amendment 2), both approved.

> No Alembic revision has been authored. No table has been created. No data has been
> migrated. No production code has changed. This document specifies *what will be done*, in
> what order, and how each step is validated and reversed.

**Explicitly outside this plan:** Phase 9 (V1 column removal / retirement). It is named so the
sequence is complete, and it has no operations here.

---

## 0. What this migration must not break

Five properties, each traceable to a decision already approved. Every phase below states how it
preserves them; §8 is the consolidated check.

| Must preserve | Because |
|---|---|
| **V1 evidence stays `UNCHECKED`** | V1 never recorded per-item attestation. Marking it `ATTESTED` writes a verification claim nobody made (M2A §8, M2B §6.2). |
| **Unrecoverable history stays unrecoverable** | Superseded drafts were overwritten; pruned checkpoints are gone. The migration must record their absence, never synthesise a replacement. |
| **Artifact integrity** | `format_version` stays 1 and `verify_bundle.py` is untouched. Every bundle exported before, during and after must verify with the same unmodified verifier. |
| **Approval provenance** | The `Review → Artifact → Memory` chain must survive intact. An artifact whose approving review is lost cannot be verified. |
| **Tenant isolation** | `owner_id` must be carried correctly onto every V2 row. A backfill that mis-assigns one is a cross-tenant leak that no later check would notice. |
| **SQLite compatibility** | The desktop host migrates too, via `create_all`, with no Alembic. A plan that only works on Postgres ships a broken desktop app. |

---

## 1. Phase sequence

| # | Phase | Changes schema? | Changes behaviour? | Reversible? |
|---|---|---|---|---|
| **P0** | Prerequisites and freeze points | no | no | n/a |
| **P1** | Compatibility layer (read seam) | no | no | yes |
| **P2** | V2 schema creation | **yes, additive** | no | yes — drop |
| **P3** | Dual-write | no | writes only | yes — stop |
| **P4** | Backfill | no | no | yes — truncate |
| **P5** | Validation | no | no | n/a |
| **P6** | Golden artifact comparison (**the gate**) | no | no | n/a |
| **P7** | Read switch | no | **yes** | yes — flag flip |
| **P8** | Write switch (stop dual-write) | no | writes only | degraded |
| **P9** | V1 retirement | yes, destructive | yes | **no** — *out of scope* |

Behaviour changes only at P7. Everything before it is invisible to users.

---

## 2. P0 — Prerequisites and freeze points

**Prerequisites**

- M2A and M2B approved (done).
- Issue [#54](https://github.com/adityamhaske/Multi-Agent-Research-Assistant/issues/54) resolved *or* explicitly deferred with `CANCELLED` handling agreed. The migration writes a `status` value that does not exist in V1 (`CANCELLED`, `AWAITING_REVIEW`), so the mapping must be settled first.
- `tests/test_host_parity.py` green with `KNOWN_DESKTOP_GAPS == {}`.
- A backup and a verified restore of the production database. Not ceremonial: P8 is the first phase whose rollback is degraded.

**Freeze points — held from P0 to P8**

| Frozen | Why |
|---|---|
| `bundle_version` / `format_version` = **1** | P6 compares bundles byte-for-byte across the boundary; a format change makes the gate meaningless. |
| `METRICS_VERSION` = **4** | Eval results either side of the migration must stay comparable. |
| `research_engine/bundle.py` assembly logic | It is the instrument P6 measures with. Changing it mid-migration invalidates the comparison. |
| `verify_bundle.py` | Same, and it is what proves artifact integrity survived. |
| The public API contract | Parity tests must pass unchanged throughout. |

**Operations.** No schema or code change. Record the freeze list in `AGENTS.md`, tag the
commit the migration starts from, and rehearse a restore from backup against a scratch
instance. The tag is what P8's degraded rollback would return to.

**Validation.** CI green on both hosts; the restore rehearsal completed and the restored copy
passes the full suite; the freeze recorded in `AGENTS.md`.
**Rollback.** n/a — nothing has changed.
**Failure handling.** Do not begin P1 until every prerequisite holds. In particular, if #54 is
neither resolved nor explicitly deferred, stop: §13.2's status mapping has no agreed answer.

---

## 3. P1 — Compatibility layer

**The step that makes every later phase reversible by a flag rather than a deploy.**

**Prerequisites.** P0.

**Operations.** Introduce a read seam — a thin accessor module through which the API obtains
research data, initially delegating 1:1 to today's V1 queries. No behaviour change, no schema
change, no new dependency.

The seam is needed because P7 switches reads *per surface* (history list, session detail,
bundle export, memory ingestion). Without it, P7 is one large deploy with one large rollback;
with it, P7 is a sequence of independently reversible flips.

Read paths to route through the seam:

| Surface | V1 source today |
|---|---|
| Session list / history | `sessions` |
| Session detail | `sessions` |
| Plan gate | `sessions.plan_json`, `outline_json` |
| Report view | `sessions.draft_report` / `final_report`, `sources` |
| Bundle export | `sessions` + checkpoint + `audit_log` + `agent_logs` |
| Memory ingestion | `sessions.final_report` |

**Both hosts.** The sidecar reads the same ORM models, so the seam must serve it too, or M1's
parity contract regresses.

**Validation.** Full backend suite green; parity suite green; a golden diff of bundle bytes
before and after the refactor (the M0A technique) proving the seam changed nothing.
**Rollback.** Revert the refactor; it is behaviour-preserving by construction.
**Failure handling.** If the golden diff differs at all, the seam is wrong — stop and fix
before P2.

---

## 4. P2 — V2 schema creation

**Prerequisites.** P1 merged and stable for at least one release.

**Operations**

1. **One Alembic revision**, additive only, following `0015_citation_resolution_rate`. It
   creates the 13 new tables of M2B §4 plus `migration_ledger` (§5), and **alters nothing**.
   No V1 table or column is touched.
2. **Ordering within the revision** follows the dependency graph:
   `research_runs → research_plans → sources → evidence → revisions → claims →
   claim_evidence_links → contradictions → reviews → claim_annotations →
   research_artifacts → audit_events → project_memory_items → project_memory_provenance`.
   Composite foreign keys require their target's `UNIQUE (id, run_id)` to exist first, which
   this ordering satisfies.
3. **SQLite parity.** The desktop creates the same tables through `create_all` on next launch,
   with two documented exclusions:
   - `project_memory_items` — `pgvector`, Postgres-only, exactly as `memory_chunks` is excluded today.
   - `project_memory_provenance` — excluded with it; provenance to a table that does not exist is meaningless.
   Every other table must render under the `with_variant` types (`JSONB→JSON`,
   `UUID→CHAR(32)`, `BIGSERIAL→INTEGER PRIMARY KEY`).
4. **Nothing reads or writes the new tables.**

**Validation**

- `alembic upgrade head` then `alembic downgrade -1` on a copy of production, twice.
- A test asserting `create_all` on SQLite produces the same table and constraint set minus the two exclusions. This is new and belongs beside `test_desktop_sidecar.py::test_existing_database_gains_columns_added_after_release`.
- A test asserting every composite FK and partial unique index exists on **both** dialects — partial indexes in particular are the feature most likely to render differently.
- The parity suite still green.

**Rollback.** `alembic downgrade -1` drops the tables. Nothing references them.
**Failure handling.** A partial `create_all` on desktop leaves an inconsistent SQLite file; the
sidecar must verify the expected table set at startup and refuse to serve with a clear message
rather than half-working — the same fail-closed posture as the corpus airgap guard.

---

## 5. The migration ledger

A temporary table, created in P2 and dropped only at P9.

```sql
-- PROPOSED. Not executed.
CREATE TABLE migration_ledger (
    run_id            UUID PRIMARY KEY,
    backfilled_at     TIMESTAMPTZ NOT NULL,
    evidence_outcome  VARCHAR(24) NOT NULL,   -- COPIED | CHECKPOINT_MISSING | CHECKPOINT_UNREADABLE | NONE_PRESENT
    evidence_count    INTEGER NOT NULL DEFAULT 0,
    revision_outcome  VARCHAR(24) NOT NULL,   -- COPIED | NO_REPORT
    artifact_outcome  VARCHAR(24) NOT NULL,   -- CREATED | NOT_APPROVED | BLOCKED
    golden_result     VARCHAR(16),            -- MATCH | MISMATCH | NOT_APPLICABLE
    notes             TEXT
);
```

**Why this exists.** The backfill must distinguish *"this run had no evidence"* from *"we could
not read this run's evidence"*. Without a ledger those produce the same empty result set, and a
run whose checkpoint was pruned would look identical to one that genuinely gathered nothing.
That is the unmeasured-vs-zero failure applied to the migration itself, and it is the exact
error this project treats as P0.

The ledger is also what makes P5 and P6 reportable: "N runs migrated" is worthless without
"and M were skipped, for these reasons".

---

## 6. P3 — Dual-write

**Prerequisites.** P2 shipped; both hosts on the new schema.

**Operations.** New and resumed runs write V1 *and* V2. **V1 remains authoritative for every
read.** Both writes occur in one transaction, following the existing pattern where the audit
row and the status change share a `commit` — so a partial write is not representable.

Write points and their V2 counterparts:

| Event | V1 write | Added V2 write |
|---|---|---|
| Run started | `sessions` insert | `research_runs` insert |
| Plan proposed | `sessions.plan_json` | `research_plans` v1, `origin=MODEL_PROPOSED` |
| Plan approved | `plan_json` overwrite, `plan_approved_at`, `audit_log` | `research_plans` v2 `origin=HUMAN_EDITED` if edited, `approved_at`; `reviews` gate=PLAN; `audit_events` |
| Evidence gathered | checkpoint only | `sources` + `evidence` rows, with real `provenance_state` |
| Draft synthesized | `sessions.draft_report` overwrite | `revisions` insert (new version), `claims`, `claim_evidence_links` |
| Contradictions detected | checkpoint only | `contradictions` rows with `detection_state` |
| Review decision | `audit_log`, `rework_count` | `reviews` gate=REPORT; `audit_events` |
| Run completed | `sessions.final_report`, status | `research_artifacts` insert |
| Memory ingested | `memory_chunks` | `project_memory_items` + `project_memory_provenance` |

**This is the phase where new runs get provenance V1 never had.** Evidence written here carries
a genuine `provenance_state` from the in-graph attestation check — `ATTESTED`, `UNATTESTED`, or
`UNCHECKED` in fake mode. Only *backfilled* rows are uniformly `UNCHECKED`. §8 keeps the two
populations distinguishable.

**Validation**

- Continuous, not one-off: a scheduled job runs the P6 comparison over runs completed in the last 24h. A dual-write bug corrupts V2 silently while V1 stays correct and every user-facing surface looks fine — this job is the only thing that would notice.
- The ledger records dual-written runs distinctly from backfilled ones.
- Parity suite green; both hosts dual-writing.

**Rollback.** Stop writing V2. V1 is untouched and complete. V2 rows become stale, which P4 can
re-derive.
**Failure handling.** A V2 write failure must **fail the transaction**, not be swallowed —
otherwise V1 and V2 diverge silently, which is worse than an error. If dual-write proves too
failure-prone, stop it and reconsider; V1 is unaffected.

---

## 7. P4 — Backfill

**Prerequisites.** P3 stable; dual-write comparison clean for at least one week.

**Operations.** Batch over historical runs, oldest first, idempotent by `migration_ledger.run_id`,
throttled to avoid competing with live traffic. Per run:

1. Insert `research_runs` from `sessions`, carrying `owner_id` from `sessions.user_id`.
2. Insert one `research_plans` row from `plan_json` + `outline_json`, `origin='UNKNOWN'`.
3. Insert `sources` rows from the `sessions.sources` JSON array.
4. Read the LangGraph checkpoint. Insert `evidence` rows, **all `UNCHECKED`**. Record the outcome in the ledger.
5. Insert **one** `revisions` row from `final_report or draft_report`.
6. Derive `claims` and `claim_evidence_links` from that report.
7. Insert `contradictions` from checkpoint state, or a `NOT_RUN` marker.
8. Insert `reviews` and `audit_events` from `audit_log`.
9. For approved runs, assemble and insert `research_artifacts`.
10. Re-point `memory_chunks` → `project_memory_items` + provenance, once the artifact exists.
11. Write the ledger row.

**Ordering within a run matters:** artifacts require reviews (composite FK), memory requires
artifacts. A run whose artifact could not be created leaves its memory un-migrated, recorded as
`BLOCKED`.

**Desktop.** The sidecar runs the same backfill once, at startup, over its SQLite database and
`checkpoints.sqlite`. It must be resumable — a desktop app can be killed mid-backfill — and must
not block first paint. Progress belongs in the app, not in a log the user never reads.

**Validation.** Per-run ledger entry; row counts reconcile against V1; no run silently skipped.
**Rollback.** Truncate V2 tables and the ledger; re-run. V1 untouched.
**Failure handling.** A failing run records its reason and the batch continues. A batch that
fails on *many* runs stops for investigation — a systematic failure must not be logged 4,000
times and called a migration.

---

## 8. P5 — Validation

**Prerequisites.** P4 complete for all runs; every `sessions.id` has a ledger row.

**Operations.** Run the structural checks below as one batch job, read-only, over the whole
dataset. No sampling — several of these are cross-tenant correctness checks, where a sample
proves nothing about the rows it did not read.

**Validation.** The job's own output: every check below returns zero violations, and the
summary report is produced and read by a person. A check that cannot run (for example, hash
verification on a run whose evidence could not be backfilled) is reported as *not run*, never
counted as passed.

**Structural checks**

| Check | Fails if |
|---|---|
| Row-count reconciliation | `count(research_runs) <> count(sessions)` |
| Tenant isolation | any `research_runs.owner_id <> sessions.user_id`, or any artifact whose `owner_id` differs from its run's — **run against every row, not a sample** |
| Approval chain | any approved V1 session without a `reviews` row, or any artifact without an approving review |
| Provenance honesty | any backfilled `evidence` row with `provenance_state <> 'UNCHECKED'` |
| Hash integrity | every `revisions.report_hash` = `sha256(report_markdown)`; every `evidence.content_hash` = `sha256(snippet)` |
| Constraint acceptance | the DB accepted every row — a violated CHECK would have failed the insert, so this is really a check that inserts were not silently skipped |
| Ledger completeness | any `sessions.id` with no ledger row |
| No manufactured history | `count(revisions) = count(sessions with a report)` — **not** `sum(rework_count + 1)`; more revisions than reports means drafts were invented |

**The last one is the important one.** It is the structural guard against the migration
"helpfully" reconstructing superseded drafts that V1 overwrote.

**Reporting.** A summary naming: runs migrated, runs with unreadable checkpoints, runs with no
artifact and why, memory items blocked. A validation report that says only "success" hides
exactly what §0 requires the migration to disclose.

**Rollback.** Truncate and re-run P4.
**Failure handling.** Any check failing blocks P6. No exceptions and no "known-acceptable"
list — a tolerated failure here is a data defect that reaches P7.

---

## 9. P6 — Golden artifact comparison (the gate)

**The gate on P7.** Nothing switches until this passes.

**Prerequisites.** P5 clean, with its report reviewed.

**Operations.** For every eligible run, assemble a bundle twice and compare. Read-only;
touches no production data. Runs on both hosts.

**Validation.** Zero `MISMATCH`, and the coverage accounting below published with its counts —
a green gate whose population is mostly `NOT_APPLICABLE` has not demonstrated much, and must
say so.

**Method.** For every historical run that reached `COMPLETED` with an approving review:

1. Assemble a bundle through the **V1 path** — `sessions` row, checkpoint, `audit_log`, `agent_logs` — using `bundle.assemble`.
2. Assemble a bundle through the **V2 path** — runs, revisions, sources, evidence, claims, links, reviews — using the **same** `bundle.assemble`.
3. Inject an identical `created_at` into both. This is the only normalisation permitted, and it is required: V1 stamps assembly time, so two assemblies of one session legitimately differ (M2A §13.4).
4. Compare `bundle.serialize(...)` **byte for byte**.
5. Run `verify_bundle.verify()` on the V2-derived manifest and require `passed = True`.

This works because `bundle.assemble` is pure — no DB, no ORM, no host — and takes plain data
from either source. It is the same instrument that proved M0A behaviour-preserving, applied to
a larger corpus.

**Coverage accounting — mandatory.** Every run must land in exactly one bucket, and the counts
are published:

| Bucket | Meaning |
|---|---|
| `MATCH` | Byte-identical. The only passing outcome. |
| `MISMATCH` | **Blocks the gate.** |
| `NOT_APPLICABLE — never approved` | No artifact to compare. |
| `NOT_APPLICABLE — checkpoint pruned` | No V1 evidence to compare against. |
| `NOT_APPLICABLE — demo run` | Compared, but proves less; counted separately. |

**A gate that silently skips is the failure this project exists to prevent.** `NOT_APPLICABLE`
is a real outcome, not a pass, and the report must show its size. If most runs are
`NOT_APPLICABLE`, the gate has not demonstrated much and that fact must be visible rather than
buried under a green tick.

**What the gate proves.** The V2 tables contain everything needed to reconstruct exactly what
V1 produced.
**What it cannot prove.** That V2 captured anything V1 never had — attestation states, plan
authorship, superseded drafts. Those are permanently `UNCHECKED` / `UNKNOWN` / absent, by
design.

**Both hosts.** The desktop runs the same comparison over its own data. A migration verified
only on the server is verified on one of two hosts, which is the recurring defect this project
keeps rediscovering.

**Rollback.** n/a — a measurement.
**Failure handling.** Any `MISMATCH` stops the migration. Diagnose by diffing the two
serialisations; the difference names the field, which names the backfill step that is wrong.

---

## 10. P7 — Read switch

**Prerequisites.** P6 passed on both hosts, with published coverage.

**Operations.** Flip reads surface by surface, through the P1 seam, each behind its own flag,
in ascending order of blast radius:

| Order | Surface | Why this position |
|---|---|---|
| 1 | Bundle export | Already proven byte-identical by P6. Lowest risk, highest confidence. |
| 2 | Session detail (report, sources) | Read-only; a defect is visible immediately. |
| 3 | Plan gate | Read-only, low traffic. |
| 4 | History list | Highest traffic; switch once the rest is stable. |
| 5 | Memory ingestion | Writes downstream data; switch last. |

Dual-write continues throughout, so V1 stays current and every flip is reversible.

**Validation.** Per surface: parity suite green, golden E2E green, and a comparison of V1 and
V2 responses for a sample of live requests before the flag is removed.
**Rollback.** Flip the flag back. V1 columns are still being written, so nothing is lost. This
is a config change, not a deploy.
**Failure handling.** Any surface showing a discrepancy is flipped back immediately and
diagnosed against the ledger; the others stay on V2.

---

## 11. P8 — Write switch

**Prerequisites.** P7 complete for all surfaces, stable for at least one full release.

**Operations.** Stop writing V1. V2 becomes authoritative for reads and writes. V1 tables remain
in place, unchanged, no longer updated.

**Validation.** Full suite, parity suite, golden E2E on both hosts. A final P6 run over runs
created during P7 — the last population written to both.
**Rollback.** **Degraded, and this is the phase to be careful about.** Flipping reads back to
V1 recovers everything up to the moment dual-write stopped; anything created after is V2-only
and would have to be replayed forward. Rolling back P8 therefore means accepting a gap or
running a reverse backfill.
**Failure handling.** Because rollback is degraded, P8 ships behind a long soak and a verified
backup. If a defect appears, prefer fixing forward over reverting.

---

## 12. P9 — V1 retirement (out of scope)

Named for completeness. **No operations in M2C.**

**Prerequisites / Operations / Validation / Rollback / Failure handling:** deliberately
undefined here. Defining them would invite starting them. P9 is irreversible and needs its own
milestone, gate and backup rehearsal.

Dropping `sessions.draft_report`, `final_report`, `sources`, `plan_json`, `outline_json`,
`rework_count`, and the `audit_log` table is irreversible and needs its own milestone, its own
gate, and its own backup rehearsal. It should not begin until V2 has been authoritative for
several releases and no rollback path to V1 is still wanted.

`migration_ledger` is dropped here, not before — it is the record of what the migration could
and could not recover, and that record outlives the migration.

---

## 13. Detailed V1 → V2 mapping

Extends M2B §6 with the transformation each field undergoes and its confidence.

### 13.1 Tables

| V1 table | V2 destination | Note |
|---|---|---|
| `projects` | `projects` | rename `user_id` → `owner_id` |
| `sessions` | `research_runs` + `revisions` + `sources` + `research_plans` | one row becomes four kinds |
| `audit_log` | `reviews` **and** `audit_events` | the §3.1 split writes both |
| `agent_logs` | unchanged | referenced by artifacts as trace |
| `memory_chunks` | `project_memory_items` + `project_memory_provenance` | re-pointed to artifacts |
| `chat_messages`, `chat_threads` | unchanged | out of scope |
| LangGraph checkpoints | `evidence` + `contradictions` | execution state discarded |
| Redis `session:{id}:cancelled` | — | **discarded**; write-only, never read (#54) |

### 13.2 `sessions` field-by-field

| V1 field | V2 | Transformation | Confidence |
|---|---|---|---|
| `id` | `research_runs.id` | direct | certain |
| `user_id` | `research_runs.owner_id` | direct | certain |
| `project_id` | `research_runs.project_id` | direct | certain |
| `prompt` | `research_runs.question` | direct | certain |
| `status` | `research_runs.status` | `AWAITING_APPROVAL`→`AWAITING_REVIEW`; `FAILED` + "stopped by user" → **stays `FAILED`** (see below) | certain |
| `research_depth` | `.depth` | direct | certain |
| `corpus_mode`, `demo`, `skip_plan_gate` | `.` same | direct | certain |
| `topic_seeds`, `outline_template` | `.` same | direct | certain |
| `model_routing` | `.model_routing` | direct | certain |
| `total_cost_usd`, `total_tokens_input`, `total_tokens_output`, `elapsed_seconds` | `.` same | direct | certain |
| `citation_resolution_rate` | `.` same | direct; **NULL stays NULL** | certain |
| `error_message` | `.error_message` | direct | certain |
| `archived_at`, `created_at`, `updated_at` | `.` same | direct | certain |
| `rework_count` | — | **discarded**; becomes `count(revisions) - 1` | derived |
| `draft_report` / `final_report` | `revisions` v1 | `final_report` preferred; `report_hash = sha256(text)`; `evidence_watermark` = max evidence sequence else 0 | certain for the surviving text; **earlier drafts discarded** |
| `sources` (JSON) | `sources` rows | one row per entry; `citation_index` from `index`; `kind` from `corpus://` prefix; `retrieval_status='UNKNOWN'` | url/title/index certain; **status unknown** |
| `plan_json`, `outline_json` | `research_plans` v1 | `origin='UNKNOWN'` | plan certain; **authorship unknown** |
| `plan_approved_at` | `research_plans.approved_at` | direct | certain |

**On cancelled runs.** V1 represents user cancellation as `FAILED` with
`error_message = "Research stopped by user."`. Inferring `CANCELLED` from that string is string-
matching a message that is not a contract, so **it is not done**: migrated rows keep `FAILED`,
and `cancelled_at` stays NULL, satisfying the coherence CHECK. `CANCELLED` is written only by
new code after #54. Recorded because the alternative is tempting and would be a fabricated
lifecycle fact.

### 13.3 `audit_log` field-by-field

| V1 field | `reviews` | `audit_events` | Confidence |
|---|---|---|---|
| `id` | — | ordering only | certain |
| `session_id` | via `revision_id` (the single migrated revision) | `subject_id` | certain |
| `user_id` | `reviewer_id` | `actor_id` | certain |
| `action='approved'` | `decision='APPROVED'`, `gate='REPORT'` | `action='review.approved'` | certain |
| `action='rework_requested'` | `decision='REWORK_REQUESTED'`, `gate='REPORT'` | `action='review.rework_requested'` | certain |
| `action='plan_approved'` | `decision='APPROVED'`, `gate='PLAN'`, `plan_version_id` = migrated plan | `action='plan.approved'` | certain |
| `feedback` | `feedback` | — | certain |
| `draft_hash` | `reviewed_hash` | — | certain for REPORT; **opaque for PLAN** — nothing has ever verified it (M2A §8) |
| `created_at` | `created_at` | `occurred_at` | certain |

### 13.4 Checkpoint state

| Checkpoint key | V2 | Transformation | Confidence |
|---|---|---|---|
| `evidence[]` | `evidence` rows | `sequence` assigned in list order; `provenance_state='UNCHECKED'`; `attested_against=NULL`; `attestation_run_at=NULL`; `content_hash=sha256(snippet)` | **UNCHECKED — never ATTESTED** |
| `evidence[].source_url` | resolved to `sources.id` | matched on `normalized_url` within the run | certain where the source list contains it |
| `evidence[].snippet` | `evidence.snippet` | verbatim, **including empty** | empty is ambiguous and stays ambiguous |
| `evidence[].key_fact` | `evidence.key_fact` | direct | certain |
| `contradictions[]` | `contradictions` rows | `detection_state='DETECTED'` where a pair resolves, else `NOT_RUN` | pairs certain; absence ambiguous |
| everything else | — | **discarded** — execution state (M2A §3.4) | n/a |

### 13.5 Derived at migration

| V2 | Derived from | Recorded as |
|---|---|---|
| `claims` | `claims.claim_lines(report)` | `extraction_method='DERIVED_FROM_REPORT'`, `verification_state='UNCHECKED'`, `verification_method='NOT_RUN'` |
| `claim_evidence_links` | `[n]` markers + source list | `origin='CITATION_MARKER'`, `stance='SUPPORTS'` |
| `research_artifacts` | `bundle.assemble` over migrated data | `format_version=1` |
| `project_memory_provenance` | `memory_chunks.source_session_id` → run → artifact | one row per item |

**Claims derived at migration are derived by today's extractor.** Re-deriving later with a
changed extractor would produce different claims for the same report — which is why V2 persists
them (M2A §3.5). The migration freezes one derivation, and that is a fact about the migration,
not about the original run.

---

## 14. Consolidated preservation check

How each §0 property is held, and where it is verified.

| Property | Held by | Verified at |
|---|---|---|
| V1 evidence stays `UNCHECKED` | Backfill writes the literal; the `evidence` CHECK makes an inconsistent claim unrepresentable | P5 provenance-honesty check |
| Unrecoverable history stays unrecoverable | One revision per run; ledger records what could not be read | P5 "no manufactured history" check; P6 coverage accounting |
| Artifact integrity | `format_version` frozen at 1; `verify_bundle.py` untouched | P6 byte comparison + `verify()` |
| Approval provenance | `ON DELETE RESTRICT` chain; artifact composite FK to an approving review | P5 approval-chain check |
| Tenant isolation | `owner_id` carried onto runs and artifacts | P5 isolation check, **every row** |
| SQLite compatibility | `create_all` parity test; desktop backfill; desktop P6 run | P2 dialect test; P6 on both hosts |

---

## 15. Open questions

Carried from M2B, still open, each blocking a specific step rather than the plan.

1. **Artifact payload storage** (M2B §8 Q2). JSONB vs blob vs object storage. Decidable before P2; the schema is agnostic.
2. **`provenance_digest` sufficiency** (M2B §8 Q4). Adequate for one-artifact-per-item, which is all M2A commits to.
3. **Desktop `owner_id`** (M2B §8 Q5). Redundant on a single-user host; kept for one schema. A named cost, not a defect.
4. **Orphaned-artifact retention** (M2B §8 Q7). Needed before P9, not before P7.
5. **Backfill duration on a large deployment.** Reading a checkpoint per run is the expensive step. Unmeasured — needs a timing run on a production-sized copy before P4 is scheduled.
6. **Whether P7's per-surface flags are removed at P8 or kept.** Keeping them costs complexity; removing them costs the cheap rollback.

---

## 16. Out of scope for M2C

No migration executed. No Alembic revision authored. No table created. No production code
changed. No data backfilled. No `bundle_version` or `METRICS_VERSION` change. P9 is named but
has no operations here.

M2D, if this is approved, is the **first executable step: the P2 Alembic revision**, reviewed
on its own, with the `create_all` dialect-parity test written before it.
