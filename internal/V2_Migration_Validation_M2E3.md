# M2E-3 — V1 → V2 migration validation report

**Status:** dry run complete on PostgreSQL and SQLite. **Production was not touched.**
**Scope:** M2E-2 (disposable dry run) and M2E-3 (this report). M2F was not started.
**Derives from:** M2A RFC, M2B schema proposal, M2C migration plan, M2C.5 read benchmark,
M2D schema (`eafdf189af24`), M2E field mapping, M2E-1 engine.

Artifacts this report is computed from, committed beside it:

| File | What |
|---|---|
| `m2e_dryrun/dryrun-postgres-200.json` | 200-run migration on a disposable Postgres |
| `m2e_dryrun/dryrun-sqlite-200.json` | the same corpus on SQLite |
| `m2e_dryrun/dryrun-postgres-200-resume.json` | the same corpus, interrupted after 80 runs and resumed |

---

## 1. Executive summary

The migration works, is idempotent, resumes correctly, and refuses rather than invents. Two
hundred synthetic-but-representative V1 sessions across twelve shapes migrated on both
dialects with **identical row counts, identical ledger outcomes and identical bundle
verdicts** — 3,836 V2 rows, zero failures, zero retries, 14 invariant checks green on each.

Three defects were found *by* the dry run, in code M2E-1 had already shipped, and fixed:

1. **A corrupt checkpoint was reported as an empty one.** Against a real LangGraph saver, a
   damaged blob still *deserialises* — to the integer `0` — so `read_checkpoint` returned
   `READ` with no evidence. The tri-state the whole milestone exists to preserve had been
   reintroduced one level below where it was fixed. `migration/checkpoint.py` now validates
   the decoded shape, not merely the absence of an exception.
2. **One refused run aborted the whole migration.** `migrate_all` loaded every `Session` up
   front; the first rollback expired all of them, and the next iteration died with
   `MissingGreenlet`. The M2E-1 test never saw it because its only refusal was the last run
   in the corpus. The runner now reads ids and re-reads each row inside its own attempt.
3. **`--limit` was not deterministic.** Ordering was `created_at` alone, which ties; resume
   could therefore cut the corpus at a different place on each pass. Now `(created_at, id)`.

Seventeen planted violations were run; **all seventeen fired** and all restored green. The
one M2E-1 plant that had stayed silent — deterministic child identity — now fires against a
test that does not depend on the `research_runs` primary key at all.

Two genuine V1→V2 limitations are reported rather than repaired, and are the reason this
migration is not yet ready to run against production unattended: `EVIDENCE_SOURCE_UNRESOLVED`
and `REVIEW_WITHOUT_REVISION` (§15). Two further limitations were discovered in the V2 schema
during bundle comparison (§16).

**Production readiness: not yet — see §17.** Nothing here should be run against
`research_db` until the two mapping limitations have a ruling.

---

## 2. Migration architecture

```
V1                          migration/                       V2
────────────────────────    ──────────────────────────────   ──────────────────────
sessions                ─┐
audit_log               ─┤   engine.migrate_session()    ──►  research_runs
sessions.plan_json      ─┤     · derives, never infers        research_plans
sessions.sources        ─┤     · deterministic uuid5 ids      sources
                         │                                    evidence
LangGraph checkpoint    ─┘   checkpoint.read_checkpoint()      contradictions
  (tri-state read)             READ | MISSING | UNREADABLE     revisions / claims / links
                                                               reviews / audit_events
                             runner.migrate_all()          ──►  migration_ledger
                               · one transaction per run
                               · resume is the default
                               · ledger written in the same tx

                             cli.py         explicit target, fail-closed
                             dryrun.py      disposable corpus + measurement
                             bundle_equivalence.py   V1 bundle ≟ V2 bundle
```

Five properties hold the design together.

**One transaction per run.** Read V1, derive V2, insert V2, write the ledger, commit. A
failure anywhere rolls the whole run back, so V2 can never hold a half-migrated run, and can
never hold rows with no ledger row to explain them.

**The migration never writes to V1.** No `UPDATE`, no `DELETE`, no schema change on any V1
table. Verified by the dry run leaving `sessions`, `audit_log` and `agent_logs` byte-identical.

**Sequential and single-connection, by measurement.** M2C.5 found concurrent checkpoint reads
flat on throughput and 14× worse at p99, because the saver serialises anyway. §12 measured
the write path and found no reason to revisit that: peak heap is 2.6 MB for 200 runs and the
per-run p99 is 95 ms, so there is nothing for concurrency to buy.

**Deterministic identity.** Every V2 child id is `uuid5(NS, key)` over the V1 identity, so a
second pass produces the *same* ids. The accurate statement of what that buys:

> `research_runs.id = session.id` is the **top-level idempotency boundary**.
> uuid5 child ids are **deterministic defence in depth**.

**Absence from the ledger means `NOT_PROCESSED`.** It never means empty. That is the reason
the ledger table exists and the reason it outlives the migration (M2C §12).

---

## 3. Ledger state machine

One row per V1 session **considered**, keyed by the V1 session id. `attempt` counts retries
in place, so a retried run does not create a competing terminal outcome.

```
                        (no row)
                    = NOT_PROCESSED
                           │
                           ▼
                   migrate_session()
                           │
      ┌────────────┬───────┴────────┬───────────────┬──────────────┐
      ▼            ▼                ▼               ▼              ▼
  MIGRATED      EMPTY        CHECKPOINT_MISSING  READ_FAILURE   NO_REPORT
   (rows)   (READ, 0 items)   (no snapshot)     (undecodable)  (no report)
      │
      ├──────────────► INCONSISTENT_V1   V2 cannot hold it without inventing a fact.
      │                                  NOT retryable — needs a human ruling.
      └──────────────► FAILED            The one retryable terminal state.
                                         `--retry-failed` re-attempts it.
```

`MIGRATED_WITH_MISMATCH` is declared in `MigrationStatus` and is **not yet written by any
code path**: bundle comparison runs after the transaction, in the dry run, rather than inside
it. Recorded here rather than removed, because M2F's dual-write is where it acquires a
writer.

`IN_PROGRESS` is likewise **unreachable by construction**: with one transaction per run,
a row written before the work would roll back with it. It is retained for a future chunked
mode and is asserted absent by `every_outcome_is_terminal`.

**Status is one slot and a run can carry two findings.** A run with an empty checkpoint *and*
no report is both. The precedence is fixed and documented in `runner.py`: **the checkpoint
outcome outranks the revision outcome**, because an unread checkpoint means the migration
could not see the run, while a missing report is something it could see. Neither fact is
lost — `evidence_outcome` and `revision_outcome` are separate columns and both are always
written. Pinned by `test_every_considered_session_has_exactly_one_terminal_outcome`.

---

## 4. V1 → V2 mapping (as built)

Extends `V2_Migration_Mapping_M2E.md` §2–§6; only differences and confirmations are listed.

| V1 | V2 | Rule |
|---|---|---|
| `sessions` | `research_runs` | 1:1, `id` preserved. `AWAITING_APPROVAL` → `AWAITING_REVIEW`; nothing else renamed |
| `sessions.status = FAILED` | `FAILED` | **including user cancellations.** `cancelled_at` and `cancel_requested_by` stay NULL |
| `plan_json` + `outline_json` | `research_plans` v1, `origin='UNKNOWN'` | V1 overwrote the proposal with the approved plan; which one this is cannot be known |
| `sessions.sources` | `sources` | verbatim; `retrieval_status='UNKNOWN'`, `kind` from the `corpus://` prefix |
| checkpoint `evidence[i]` | `evidence`, `sequence = i+1` | `provenance_state='UNCHECKED'` **always**; snippet kept verbatim, empty included |
| checkpoint `contradictions` | `contradictions`, `detection_state='NOT_RUN'` | the pair is keyed by source URL in V1 and cannot be reconstructed — see §16 |
| `final_report or draft_report` | `revisions` v1 | **exactly one.** Never `rework_count + 1` |
| report prose | `claims` + `claim_evidence_links` | via `research_engine.claims`, `extraction_method='DERIVED_FROM_REPORT'`, `lineage_id` NULL |
| `audit_log` | `reviews` **and** `audit_events` | 1:1 into each, via `AUDIT_MAP` |
| `rework_count` | — | discarded; derivable as `count(revisions) - 1` |
| `agent_logs` | unchanged | same table serves both bundle assemblers |

`AUDIT_MAP` is injective and its inverse is pinned by `test_the_audit_action_map_is_invertible`,
so the V2 approval chain can be rebuilt without a second hand-maintained table.

**Five refusals, each traceable to a rule rather than to taste.** Every one is a planted
failure in §13.

| Refusal | Category | Why |
|---|---|---|
| evidence whose source is not in `sessions.sources` | `EVIDENCE_SOURCE_UNRESOLVED` | `evidence.source_id` is NOT NULL and V2 has no honest placeholder |
| a review with no revision to attach to | `REVIEW_WITHOUT_REVISION` | `reviews.revision_id` is NOT NULL; the approval must not be dropped and no revision may be fabricated |
| two approving REPORT reviews for one revision | `DUPLICATE_APPROVAL` | `uq_review_approval` forbids it; refusing here makes it `INCONSISTENT_V1` rather than a *retryable* `FAILED` that would fail identically forever |
| a `draft_hash` that is not 64 characters | `MALFORMED_DRAFT_HASH` | `ck_review_hash`; never padded, never regenerated |
| an audit action outside the three that exist | `UNKNOWN_AUDIT_ACTION` | a fourth action must stop the run, not migrate as an approval-shaped hole |

---

## 5. Checkpoint tri-state handling

`app.services.checkpoints.get_thread_state` returns `snapshot.values if snapshot else {}`,
collapsing "no checkpoint" and "empty checkpoint" into `{}`. It is a live production read
path and M2E does not touch it. `migration/checkpoint.py` owns the distinction instead:

| Outcome | Means | Ledger |
|---|---|---|
| `READ` + evidence | a snapshot decoded and held items | `COPIED` → `MIGRATED` |
| `READ` + no evidence | a snapshot decoded and held nothing | `NONE_PRESENT` → `EMPTY` |
| `MISSING` | `aget_tuple` returned `None` | `CHECKPOINT_MISSING` |
| `UNREADABLE` | a snapshot exists and could not be decoded **into a checkpoint** | `CHECKPOINT_UNREADABLE` → `READ_FAILURE` |

**The defect the dry run found.** M2E-1 read the values as
`dict((tup.checkpoint or {}).get("channel_values") or {})` and treated *any* non-raising
decode as success. Corrupting a real `AsyncSqliteSaver`'s stored blob produces a value that
deserialises to the integer `0`; `0 or {}` is `{}`, so a corrupt checkpoint was recorded as a
run that had genuinely gathered nothing. The tests did not catch it because they only
exercised `FakeSaver`, which *raises* on corruption — a fake that behaves better than the
thing it stands in for.

The reader now requires the decoded checkpoint to be a mapping carrying a `channel_values`
mapping, and reports `UNREADABLE` otherwise, including when `channel_values` is absent
entirely ("a format this code does not understand" is not "a run with no evidence").
`test_the_tri_state_holds_against_a_real_langgraph_saver` exercises all four states against
a real saver, and the dry run's `unreadable_checkpoint` shape corrupts a real stored blob
rather than simulating one.

---

## 6. Transaction semantics

* One transaction per run, opened by the caller, committed once the ledger row is written.
* `Unmigratable` → rollback, then `INCONSISTENT_V1` recorded with its category and detail.
* Any other exception → rollback, then `FAILED` recorded with the exception type and message.
* `--dry-run` (the CLI default) executes everything and rolls back every transaction,
  including the ledger write.
* `KeyboardInterrupt` is a `BaseException` and is deliberately **not** caught: an operator
  pressing Ctrl-C kills the process with the transaction open, so the run leaves no rows and
  no ledger entry — which is exactly `NOT_PROCESSED`.

Measured, not asserted: `no_partial_rows_for_a_refused_run` passed on both dialects, and
`test_a_failure_mid_transaction_leaves_no_v2_rows` injects a fault *after* the run, sources,
evidence and revision rows are already in the transaction — a failure early enough to be
trivially safe would prove nothing.

---

## 7. Idempotency

Three independent mechanisms, in order of what actually stops a duplicate:

1. **The ledger.** A session with a terminal status is skipped. This is what makes re-running
   cheap; it is not what makes it safe.
2. **`research_runs.id = session.id`.** The top-level boundary. Even with the ledger wiped,
   the second pass collides on the primary key and rolls back.
3. **`uuid5` child ids.** Defence in depth: same V1 source + same mapping → same child id.

**The P3 gap M2E-1 left open, and how it is closed.** M2E-1 planted a `uuid4` substitution
and it did not fire, because mechanism 2 collided first and hid the change — so the plant
proved only that the run id is stable. The claim under test is about *children*, so the new
test removes the shield: it migrates a byte-identical V1 fixture into **two disjoint
databases** that share no primary key at all, and compares the ids of every child table —
`research_plans`, `sources`, `evidence`, `contradictions`, `revisions`, `claims`,
`claim_evidence_links`, `reviews` — with a vacuity guard requiring each to be non-empty.
A second test deletes every V2 row *and* the ledger and re-migrates, so nothing remains to
collide with. Both fail under `uuid4` (verified: planted, failed, restored, passed).

On Postgres, running the CLI a second time over a fully migrated database reported
`considered: 0` and left all row counts identical (188 runs / 612 evidence / 672 claims /
200 ledger rows before and after).

---

## 8. Resume behaviour

Resume needs no flag: the migration always skips terminal sessions. `--resume` exists to
document that; `--retry-failed` is the opt-in that additionally re-attempts `FAILED`.

**Clean stop, Postgres, 200 runs, interrupted after 80:**

| | |
|---|---|
| first pass considered | 80 |
| ledger rows after first pass | 80 |
| second pass considered | 120 |
| first + second | 200 = the corpus |
| rows written across both passes | 1,520 + 2,316 = 3,836 |
| rows in the database afterwards | **3,836** |

Every check passed, including `resume_processed_only_the_remainder` and
`resume_duplicated_nothing`, and the bundle verdicts were identical to the uninterrupted run.

**Hard interruption** is covered by `test_resume_after_a_hard_interruption_loses_nothing_and_duplicates_nothing`:
a `KeyboardInterrupt` during run 3 of 4 leaves two ledger rows and two V2 runs; the restart
processes exactly the interrupted run and the untouched one, and the evidence count proves
nothing was migrated twice.

**Retry:** a fault-injected `FAILED` run retried with `--retry-failed` becomes `MIGRATED`
with `attempt = 2` — the retry is counted, not hidden — and a third pass changes nothing.
Without the flag, a `FAILED` run is left alone (`considered: 0`).

---

## 9. Coverage accounting

Twelve V1 shapes, each mapping to exactly one expected outcome, asserted by
`every_shape_lands_where_expected` rather than eyeballed. Identical on both dialects.

| Shape | Runs | Ledger outcome |
|---|---:|---|
| `complete` | 80 | MIGRATED |
| `complete_large` (12 evidence items) | 16 | MIGRATED |
| `reworked` (`rework_count = 2`) | 20 | MIGRATED |
| `demo` | 8 | MIGRATED |
| `with_contradictions` | 12 | MIGRATED |
| `cancelled_as_failed` | 8 | MIGRATED (status stays `FAILED`) |
| `empty_checkpoint` | 16 | EMPTY |
| `missing_checkpoint` | 12 | CHECKPOINT_MISSING |
| `unreadable_checkpoint` | 4 | READ_FAILURE |
| `no_report` | 12 | NO_REPORT |
| `orphan_evidence` | 8 | INCONSISTENT_V1 / `EVIDENCE_SOURCE_UNRESOLVED` |
| `plan_approved_no_report` | 4 | INCONSISTENT_V1 / `REVIEW_WITHOUT_REVISION` |
| **total** | **200** | considered 200, accounted 200, **remainder 0** |

**The corpus is synthetic, and that is a stated limitation.** M2E-2 forbids touching
production, so the eleven live sessions in `research_db` were **not read** and are **not**
represented here. The shapes are derived from V1's own writers — `sessions.sources` is
produced by calling `graph._number_sources` rather than hand-written, so a hand-authored
source list that no V1 code path could emit cannot make the comparison pass. What this does
not establish is the *distribution*: production may hold shapes in different proportions, or
a thirteenth shape nobody has thought of. §17 makes running against a restored copy of
production a precondition for readiness.

---

## 10. V2 row counts (200 runs, identical on Postgres and SQLite)

| Table | Rows |
|---|---:|
| `research_runs` | 188 |
| `research_plans` | 188 |
| `sources` | 708 |
| `evidence` | 612 |
| `contradictions` | 12 |
| `revisions` | 176 |
| `claims` | 672 |
| `claim_evidence_links` | 576 |
| `reviews` | 352 |
| `audit_events` | 352 |
| **total** | **3,836** |

188 runs from 200 sessions: the 12 `INCONSISTENT_V1` sessions wrote nothing at all. 176
revisions from 188 runs: the 12 `no_report` sessions produced no revision. `rows_written`
summed from the ledger equals the database count for every table
(`rows_written_matches_the_database`).

**A note worth carrying into M2F.** `EMPTY`, `CHECKPOINT_MISSING` and `READ_FAILURE` all
produce a `research_run` row with zero evidence. Reading V2 alone, those three are
indistinguishable — the distinction survives **only in `migration_ledger`**. That is the
concrete reason the ledger must not be dropped, and a reason M2F must not present "0
evidence" as a measured fact.

---

## 11. Bundle equivalence

Both sides go through the same `research_engine.bundle.assemble`, so any difference is a
difference in the data. The V1 side reproduces `export_bundle_json` field for field. Only two
fields are normalised, and both are properties of the act of assembling: `created_at` (the
wall clock at assembly) and `bundle_hash` (a digest over every other field including
`created_at`, recomputed over the normalised dict on both sides so it still detects any
difference in the fields that *are* compared). Nothing else is normalised.

| Verdict | Runs | |
|---|---:|---|
| `BUNDLE_EQUIVALENT` | 124 | |
| `BUNDLE_MISMATCH` | 28 | 16 `SOURCE_SNIPPETS_NOT_STORED`, 12 `CONTRADICTION_PAIR_NOT_STORED` |
| `NOT_COMPARABLE` | 48 | 28 V1 not COMPLETED, 12 checkpoint missing, 4 checkpoint unreadable, 4 AWAITING_PLAN |

**What `BUNDLE_EQUIVALENT` means, and what it does not.** It means exactly one thing:

> the V1 representation and the V2 representation are the same

It does **not** mean the historical V1 evidence was truthful, that its citations resolved,
that its claims were epistemically correct, or that any attestation was valid. Those are
properties of the *run*; this is a property of the *migration*. The fixture makes the
distinction concrete: `test_bundle_equivalence_is_not_a_claim_about_truthfulness` asserts a
bundle-equivalent run whose evidence is still `UNCHECKED` and still carries the empty snippet
V1 blanked when verification failed.

**Mismatches are never silently ignored.** Every mismatch is classified against a small
`KNOWN_LOSSY` table of named V2 storage gaps; a field set not in that table classifies as
`UNCLASSIFIED`, and the dry run **fails** on it (`every_bundle_mismatch_is_a_named_limitation`).
An unrecognised difference is therefore louder than a recognised one. `KNOWN_LOSSY` is itself
pinned by a test so it cannot be widened to absorb a real defect.

---

## 12. Write performance

M2C.5 measured the checkpoint **read** path. This is the first measurement of the V2 **write**
path, against the real M2D schema, with checkpoint reads served by a real LangGraph
`AsyncSqliteSaver` rather than a stub.

| | Postgres 15 (pgvector image) | SQLite |
|---|---:|---:|
| runs considered | 200 | 200 |
| rows inserted | 3,836 | 3,836 |
| wall clock | 7.71 s | 6.22 s |
| rows / sec | 497 | 617 |
| per-run mean | 32.1 ms | 25.9 ms |
| per-run p50 | 30 ms | 25 ms |
| per-run p95 | 86 ms | 69 ms |
| per-run p99 | 95 ms | 76 ms |
| per-run max | 108 ms | 79 ms |
| peak heap | 2.58 MB | 2.27 MB |
| failures | 0 | 0 |
| retries | 0 | 0 |

Per-run duration **is** the transaction duration: the timer spans read → derive → insert →
ledger → commit.

The p95/p99 spread is the `complete_large` shape (12 evidence items, 12 sources, 12 claims —
roughly 60 rows against 19 for the common case), not variance in the engine.

**No concurrency was introduced, and none is warranted.** M2C.5 showed concurrent checkpoint
reads flat on throughput and 14× worse at p99. Nothing here changes that conclusion:
extrapolating the Postgres figure, the eleven live production sessions would migrate in well
under a second, and 2.6 MB of peak heap for 200 runs leaves no memory pressure to batch away.
Introducing concurrency would add a failure mode to buy nothing measurable.

---

## 13. Planted failure results

Every plant was applied to shipped code, the migration suite was run, the file restored, and
the suite re-run. **17 applied, 17 fired, 17 restored green.**

| # | Violation | Fired | Caught by |
|---|---|---|---|
| P1 | `Unmigratable` no longer rolls back | ✓ | `test_a_refused_run_leaves_no_partial_v2_rows` |
| P1b | a generic error no longer rolls back | ✓ | `test_a_failure_mid_transaction_leaves_no_v2_rows` |
| P2 | bundle mismatch ignored for known fields | ✓ | `test_a_v2_difference_is_reported_not_ignored` |
| P3 | **deterministic child ids replaced by `uuid4`** | ✓ | `test_child_identity_is_deterministic_across_independent_databases` |
| P4 | ledger row omitted for a refused run | ✓ | `test_every_considered_session_has_exactly_one_terminal_outcome` |
| P5 | missing checkpoint treated as EMPTY | ✓ | `test_missing_checkpoint_is_CHECKPOINT_MISSING_not_empty` |
| P6 | unreadable checkpoint treated as EMPTY | ✓ | `test_the_tri_state_holds_against_a_real_langgraph_saver` |
| P7 | unresolved source silently synthesised | ✓ | `test_evidence_with_no_resolvable_source_is_classified_not_invented` |
| P8 | plan review silently dropped | ✓ | `test_a_review_without_a_report_is_classified_not_dropped` |
| P9 | historical cancellation converted to CANCELLED | ✓ | `test_a_cancelled_run_stays_FAILED` |
| P10 | `rework_count` manufactures revisions | ✓ | `test_rework_count_does_not_manufacture_revisions` |
| P11 | claim lineage inferred from text | ✓ | `test_claim_lineage_is_never_inferred` |
| P12 | evidence migrated as ATTESTED | ✓ | `test_no_v1_evidence_becomes_attested` |
| P13 | duplicate approval accepted | ✓ | `test_two_approvals_for_one_revision_are_refused_not_retried` |
| P14 | `--limit` stops nothing | ✓ | `test_absence_from_the_ledger_means_not_processed` |
| P15 | malformed draft hash padded | ✓ | `test_a_malformed_draft_hash_is_refused_not_padded` |
| P16 | unknown audit action skipped | ✓ | `test_an_unknown_audit_action_stops_the_run_rather_than_being_skipped` |

P13, P15 and P16 were **silent when first run**, which is how the three missing refusal tests
were found. Their tests were written in response, and the sweep re-run to confirm.

---

## 14. Unrecoverable V1 information

Facts V1 did not record. Migrating them would mean inventing them, so V2 records their
absence instead.

| Lost | Why | V2 |
|---|---|---|
| per-item evidence attestation | V1's check is skipped in fake mode, records nothing per item, and *blanks* the snippet on failure rather than flagging it | `provenance_state='UNCHECKED'`, `attested_against` NULL, `attestation_run_at` NULL |
| superseded report drafts | V1 overwrote `draft_report` in place on rework | exactly one revision per run; `rework_count` is discarded, not converted |
| whether a plan was proposed or edited | V1 overwrote `plan_json` with the approved plan | `research_plans.origin = 'UNKNOWN'` |
| whether a page was fetched or only seen in a search result | V1 never recorded it | `sources.retrieval_status = 'UNKNOWN'` |
| claim identity across revisions | nothing in V1 observed it; matching by text would manufacture a relationship | `claims.lineage_id` NULL in every migrated row |
| user cancellation | recorded as `FAILED` with the message `"Research stopped by user."` — prose, not a contract | stays `FAILED`; `cancelled_at` NULL, satisfying `ck_run_cancelled` |
| which evidence rows a contradiction paired | V1 keys the pair by source URL | `evidence_a_id`/`evidence_b_id` NULL, `detection_state='NOT_RUN'` |
| the Redis `session:{id}:cancelled` key | write-only; nothing ever read it | discarded |
| everything else in the checkpoint | execution state, not research | discarded |

**A caveat that belongs to the migration, not the run.** `claims` are derived by *today's*
extractor. Re-deriving later with a changed extractor would yield different claims for the
same report — which is precisely why V2 persists them (M2A §3.5) and why
`extraction_method = 'DERIVED_FROM_REPORT'` says plainly where they came from.

---

## 15. Inconsistent V1 cases

Both are reported here, both are real, and neither is repaired by the migration.

### `EVIDENCE_SOURCE_UNRESOLVED` — 8 of 200 in the dry-run corpus

Evidence exists in the checkpoint whose `source_url` has no entry in `sessions.sources`.

*How V1 produces it.* `graph._number_sources` skips evidence with an empty `source_url`, and
`sessions.sources` is written only by `synthesizer_node`. A run that failed before synthesis
therefore has evidence and no sources at all. This is **legitimate V1 behaviour**, not
corruption.

*Why it cannot be migrated.* `evidence.source_id` is NOT NULL and is the target of the
composite FK `(source_id, run_id) → sources(id, run_id)`. There is no honest placeholder.

*What the migration does.* Refuses the run: `INCONSISTENT_V1`, zero V2 rows, V1 untouched,
reason recorded. **No synthetic `Source` is created.** Planted as P7.

### `REVIEW_WITHOUT_REVISION` — 4 of 200 in the dry-run corpus

An `audit_log` row exists for a session that has no report.

*How V1 produces it.* `submit_plan` requires status `AWAITING_PLAN`, which precedes any
draft. A `plan_approved` row with no report is therefore **normal**, not a defect.

*Why it cannot be migrated.* `reviews.revision_id` is NOT NULL. The approval cannot be
attached to anything, and dropping it would destroy a human decision, which C3 forbids.

*What the migration does.* Refuses the run: `INCONSISTENT_V1`, zero V2 rows, the V1
`audit_log` row untouched and still there. **No `Revision` is fabricated.** Planted as P8.

*Whose problem it is.* This is a **V2 domain/schema issue, not a migration issue** — the
schema cannot express "a human approved a plan for a run that never produced a report". It is
explicitly out of scope for M2E-2: `Review.revision_id` was not changed, the M2D schema was
not touched, and no data was invented. Fixing it is M2F's decision (§16).

---

## 16. V2 schema limitations discovered

Four, all found by M2E-2, none fixed here.

**1. `reviews.revision_id` is NOT NULL, so a plan review needs a report.** §15. The plan gate
legitimately fires before any revision exists. Candidate resolutions for M2F, listed without
recommending one: make `revision_id` nullable and lean on `ck_review_plan`; give `reviews` a
polymorphic subject; or admit a plan-scoped review table. Each has consequences for
`uq_review_approval` and for the artifact FK chain, which is why it is not decided here.

> **Superseded by M2F (F1).** This item's classification was wrong and its name has changed
> to `V1_SOURCE_SNAPSHOT_DIVERGED_FROM_EVIDENCE`. The field is derived data — `_number_sources`
> computes it, `verify_bundle` never reads it — and the V1 bundle for a mismatching run fails
> its own `claim_evidence_linkage` check. It is a V1 inconsistency, not a V2 storage gap. The
> measurement below stands; the reading of it does not. See
> `V2_Migration_Fidelity_M2F.md` §9.1 and the amendment §2 C1.

**2. `sources` does not store the snippet list, so `sessions.sources` cannot round-trip.**
16 of 200 bundles mismatched on this field (`SOURCE_SNIPPETS_NOT_STORED`). V1's source entry
carries `snippet` and `snippets`, both derived by `_number_sources` from the evidence. V2
stores neither, so the bundle rebuilds them by replaying that derivation over the migrated
evidence — which reproduces V1 exactly *when* the evidence still matches the snapshot V1
recorded, and cannot when it does not (a pruned or emptied checkpoint being the clearest
case). Not a data-loss bug: the snippets live in `evidence`. It is a statement that V2 has no
way to record *what the source list said at synthesis time*.

**3. `contradictions` cannot be reconstructed.** 12 of 200 bundles mismatched
(`CONTRADICTION_PAIR_NOT_STORED`). V1's pair is `(source_a, source_b, claim_a, claim_b)`,
keyed by URL. V2 keys the pair by evidence id, and the migration leaves both NULL because V1
never recorded which evidence row a side came from. Recording `DETECTED` without the pair
would violate `ck_contra_pair`; `NOT_RUN` with summaries is the truthful compromise, and it
means the V1 "Conflicting evidence" block cannot be regenerated from V2 alone.

**4. `reviews` has no per-run ordinal.** V1 orders the approval chain by `audit_log.id`. V2
can only order by `(created_at, id)`, and the id is a uuid5 — so two reviews sharing a
timestamp have an ambiguous order in the rebuilt bundle. Not observed in the dry run (its
audit rows carry distinct timestamps by construction) and not repaired, because repairing it
means adding a column to M2D. Recorded so M2F can decide.

**Also recorded, not a schema limitation:** `EMPTY`, `CHECKPOINT_MISSING` and `READ_FAILURE`
are indistinguishable in the V2 domain tables — see §10.

> **Resolved by M2F (F1), without a schema change.** The distinction stays in
> `migration_ledger`, and the V2 bundle assembler now consults it: a run whose checkpoint could
> not be read produces no bundle rather than one asserting zero evidence. Absence of a ledger
> row means the run is V2-native, so its evidence rows are the complete record. Amendment §9.

---

## 17. Production readiness assessment

**Verdict: not ready. Do not run this against `research_db`.**

What is established:

- ✅ deterministic, idempotent, resumable, one transaction per run
- ✅ identical behaviour on PostgreSQL and SQLite — same rows, same statuses, same verdicts
- ✅ 17/17 planted violations fire; three real defects found and fixed
- ✅ every considered session lands in exactly one terminal outcome, no remainder
- ✅ refuses rather than invents, in five distinct situations
- ✅ write performance measured and comfortable; no concurrency needed
- ✅ the CLI cannot reach production without an explicit, matching confirmation

What blocks it:

1. **`REVIEW_WITHOUT_REVISION` has no ruling.** Any production run in that state migrates as
   `INCONSISTENT_V1` — nothing lost, but nothing migrated either. It needs a V2 domain
   decision (§16.1) before a production migration can claim full coverage.
2. **`EVIDENCE_SOURCE_UNRESOLVED` has no ruling.** Same shape: the run is classified, not
   migrated. Whether V2 should gain a representation for "evidence whose source was never
   recorded" is an M2F question.
3. **The corpus is synthetic.** No production row has been read. The next step is a dry run
   against a *restored copy* of production — never production itself — to confirm the shape
   distribution and surface any thirteenth shape.
4. **`migration_ledger` is not in production's schema.** Production is at
   `0015_citation_resolution_rate`; both `eafdf189af24` (M2D) and the new `0016_migration_ledger`
   are unapplied. Applying them is a separate, reviewable act.
5. **The bundle comparison runs after the transaction, not inside it.** So
   `MIGRATED_WITH_MISMATCH` is never written today. If a production migration is expected to
   record bundle fidelity per run, that wiring is still to do.

Recommended order once M2F has ruled on 1 and 2: apply `eafdf189af24` + `0016` to a restored
copy → dry run against that copy → review the ledger → only then consider production, with
`--apply --confirm-database research_db` typed deliberately.

---

## 18. What changed in M2E-2

| File | Change |
|---|---|
| `backend/migration/checkpoint.py` | **fix:** a decode that does not raise is not a decode that succeeded (§5) |
| `backend/migration/runner.py` | **fix:** ids-then-rows, so one rollback no longer aborts the migration; deterministic `(created_at, id)` order; status precedence documented |
| `backend/migration/bundle_equivalence.py` | new — V1/V2 bundle assembly, canonical comparison, `KNOWN_LOSSY` classification |
| `backend/migration/cli.py` | new — explicit, fail-closed migration CLI |
| `backend/migration/dryrun.py` | new — disposable corpus, measurement, and 14 invariant checks |
| `backend/alembic/versions/0016_migration_ledger.py` | new — the ledger table, with no FK to `sessions` by design |
| `backend/alembic/env.py` | import `migration.ledger` so autogenerate does not propose dropping it |
| `backend/tests/migration_support.py` | new — shared disposable-database scaffolding |
| `backend/tests/test_migration_engine.py` | +3 refusal tests, +2 deterministic-identity tests |
| `backend/tests/test_migration_dryrun.py` | new — 21 tests: resume, partial failure, retry, ledger accounting, bundle equivalence, real-saver tri-state |
| `backend/tests/test_migration_cli.py` | new — 14 tests, all about refusing |
| `internal/m2e_dryrun/*.json` | the three dry-run results this report is computed from |

**Not done, deliberately:** production was not migrated, reads and writes were not switched,
no dual-read or dual-write was added, the frontend and LangGraph were untouched, no V1 table
or column was removed, `Review.revision_id` was not changed, the M2D schema was not modified,
and M2F was not started.
