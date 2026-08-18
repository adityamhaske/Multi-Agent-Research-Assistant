# V2 release gate — migration validated against restored production data

**Date:** 2026-08-18 · **Verdict:** the last known engineering release blocker is cleared.
**Production was never written to.** Every command ran against a disposable restore.

Until now the migration had only ever been measured against a corpus it generated itself.
This is the first run against the actual historical data, and it is the authoritative
validation for real V1 records.

---

## A. Source and restore

| | Source | Restored copy |
|---|---|---|
| database | `research_db` (**read-only**, `pg_dump` only) | `v2_release_check` (disposable) |
| alembic | `0015_citation_resolution_rate` | `0015…` → upgraded to `0018_agent_logs_polymorphic` |
| users / projects | 16 / 14 | 16 / 14 |
| sessions | 11 | 11 |
| audit_log | 20 | 20 |
| agent_logs | 214 | 214 |
| LangGraph checkpoints | 4 tables | **106 checkpoint rows** |
| V2 tables | 0 | 0 before the upgrade, 13 after |

Every compared count matches. The restore carries **real checkpoints**, which is what makes
this meaningful: the evidence the migration read is the evidence those runs actually
gathered, not a fixture.

**Safety gate — all five passed before anything was written:** target is not `research_db`;
target name marks it disposable; no application is connected to it; it carries the expected
V1 revision; it contains no V2 tables.

## B. Migration results

Dry run first (rolled back), then applied to the disposable copy.

```
considered 11 · MIGRATED 11 · refused 0 · failed 0 · retries 0
evidence_outcome: COPIED × 11      revision_outcome: COPIED × 11
```

234 V2 rows: 11 runs · 11 plans · 22 sources · 40 evidence · 11 revisions · 44 claims ·
55 claim→evidence links · 20 reviews · 20 audit events · 0 contradictions.

**Zero refusals on real data.** Neither `EVIDENCE_SOURCE_UNRESOLVED` nor
`PLAN_REVIEW_WITHOUT_PLAN` occurred.

## C. Fidelity gate

| Verdict | Runs |
|---|---:|
| `BUNDLE_EQUIVALENT` | **7** |
| `BUNDLE_MISMATCH` | **0** |
| `NOT_COMPARABLE` | 4 — all `v1=V1_STATUS_NOT_COMPLETED \| v2=V2_PRESENT` |

No generic bucket, and **no mismatch at all**: neither known lossy class
(`V1_SOURCE_SNAPSHOT_DIVERGED_FROM_EVIDENCE`, contradiction pairs) was triggered by real
data. The four not-comparable runs are `AWAITING_APPROVAL` drafts — V1's own export route
refuses a non-COMPLETED session, so there is no V1 bundle to be equivalent to. V2 migrated
all four in full; the reason set states both sides.

## D. Validity gate

| Pairing | Runs |
|---|---:|
| `v1=valid, v2=valid` | 7 |
| `v1=invalid, v2=invalid` | 4 — `approval_chain` on both sides |
| **`v1=valid → v2=invalid`** | **0** ✅ |
| **`v1=invalid → v2=valid`** | **0** ✅ |
| **`v1=unassembled → v2=assembled`** | **0** ✅ |

The four invalid-on-both are **inherited, not caused**. Each carries exactly one V1 audit
row — `plan_approved` — and no report approval, so `approval_chain` correctly fails: a draft
nobody approved has no approval to verify. The migration recorded each as a PLAN review at
sequence 1 with `revision_id` NULL.

**This is the M2F/F2 work validated by real data.** Under the pre-M2F schema, where
`reviews.revision_id` was NOT NULL, all four of these production runs would have been refused
as `REVIEW_WITHOUT_REVISION` — 36% of the estate. They migrate cleanly now, and the plan
approval still authorizes no artifact.

## E. Grounding gate

```
undeclared_columns   []
stale_declarations   []
constant_violations  []
```

Every column written to real data is declared `FROM` / `DERIVED` / `CONST` / `NULL`, and
every declared constant holds in the rows actually produced.

## F. Ledger accounting

11 sessions considered, 11 ledger rows, **one terminal outcome each**, no remainder. All
states remain distinct in the schema; on this estate only `MIGRATED` occurred, with
`EMPTY`, `CHECKPOINT_MISSING`, `READ_FAILURE`, `INCONSISTENT_V1`, `NO_REPORT` and
`MIGRATED_WITH_MISMATCH` at zero. Retries: 0.

## G. Bundle verification

Assembled from the **actual migration output** and checked by the shipped standalone
verifier, not by comparing bytes:

- **7 of 7** runs expected to produce a verifiable artifact — the COMPLETED ones — **PASS**
  all six checks.
- 4 fail `approval_chain` only, classified above: never approved in V1.

No V2 artifacts were created. The migration deliberately does not create them (an artifact
is a frozen snapshot, not a migrated fact); it records whether one *could* be authorized.

## H. Performance — measured, not extrapolated

Fresh restore, timed end to end: **11 sessions, 234 rows, 0.416 s wall clock, 563 rows/sec,
per-run p50 14 ms / p95 174 ms / max 174 ms.** The max is the first run, which pays the
checkpointer's connection setup.

The synthetic baseline (220 runs, 3,836 rows, ~7.7 s) is *not* the production number and is
not quoted as one. Nothing here is close to needing optimisation.

## I. Production safety

Re-checked read-only after every step:

```
alembic_version = 0015_citation_resolution_rate
sessions 11 · audit_log 20 · agent_logs 214 · users 16 · projects 14
v2_tables = 0
last_session_update unchanged
```

Identical to the pre-run snapshot. `pg_dump` was the only command that touched it.

## J. Defects discovered

**None.** No behaviour differed from the synthetic validation, and no code was changed as a
result of this run.

## K. Known limitations (unchanged, none introduced here)

- **The estate is small and homogeneous.** 11 sessions, all COMPLETED or AWAITING_APPROVAL,
  none cancelled, none with a missing or unreadable checkpoint, none with contradictions.
  Six of the migration's terminal states and both refusal categories were therefore **never
  exercised by real data** — they remain covered only by the synthetic corpus and the
  planted-failure suite. That is a property of this deployment's history, not a gap in the
  tooling, but it is the honest limit of what this run proves.
- Corpus-mode V2 has no end-to-end test (requires a local embedder).
- Cancellation is advisory; claims carry no verification; no claim lineage; project memory
  does not ingest V2 runs.

## Artifacts and cleanup

`migration-report.json`, `gates.json` and `perf.json` were captured under the session
scratch directory and their findings are reproduced above. **The database dump and the
restored databases were deleted after capture and are not in the repository** — the dump
contains real user data (16 users, 14 projects) and must never be committed. No credentials,
DSNs or machine paths appear in this report or in git.

To reproduce: `pg_dump` the production database, restore into a database whose name you pass
to `--confirm-database`, `alembic upgrade head`, then run `python -m migration.cli` against
that DSN. The CLI refuses to write without a matching `--confirm-database`, and the dry-run
tool refuses any target whose `sessions` table is not empty.
