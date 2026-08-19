# Migrating V1 data to V2

V2 adds tables; it does not rewrite V1's. Upgrading a deployment to v2.0.0 does **not**
migrate your existing research — `alembic upgrade head` creates the V2 schema and leaves
every V1 session exactly as it was. Moving that history into the V2 domain is a separate,
explicit act, performed by a tool you run yourself.

This page is about that tool. If you are starting fresh, you need none of it: a run started
on v2.0.0 records everything from the beginning.

> **No production database has been migrated by this project.** The tooling is validated
> against disposable copies, including one restored from real production data — see
> [what has actually been measured](#what-has-actually-been-measured). Running it on your own
> data is your decision, against your own backup.

## Why this is a tool and not a startup step

A schema migration that runs itself is appropriate when the transformation is mechanical. This
one is not. V1 recorded some things V2 wants and never recorded others, and the interesting
question is not "did the rows move" but **"is anything in V2 now asserting something V1 never
said"**. That question needs answering per session, with an outcome you can read afterwards —
which is what the ledger is for.

So: it is a CLI, it defaults to a dry run, it refuses to write without being told the database
name out loud, and it records one terminal outcome for every session it considers.

## What it will not do

The migration recovers facts. It does not manufacture them. Where V1 holds no answer, V2
records the absence rather than filling it in.

| V1 did not record | V2 does **not** invent |
|---|---|
| Per-item verification of evidence | Evidence is written `UNCHECKED` — *nobody checked*, not *it passed* |
| Superseded report drafts (V1 overwrote them) | One revision, not a reconstructed history |
| Whether a plan was proposed or edited (V1 overwrote that too) | No edit history, no diff |
| Whether a run was cancelled (recorded as a message, not a state) | No cancellation state |
| A citation number for a source the synthesizer never numbered | `citation_index` stays `NULL` — retrieved, never cited |
| Claim lineage across revisions | No links; matching by text would manufacture a relationship nothing observed |

Two V1 states cannot be represented at all without inventing a fact, and the run is **refused**
rather than approximated:

- **`EVIDENCE_SOURCE_UNRESOLVED`** — evidence whose `source_url` was never recorded anywhere in
  V1. No identity exists to point a `Source` row at, so creating one would be an invention.
- **`PLAN_REVIEW_WITHOUT_PLAN`** — an audit row approving a plan for a run that has neither
  `plan_json` nor `outline_json`. There is nothing for the review to target.

A refused session writes **no partial rows**. V1 is left untouched and the reason is recorded.

## The outcome ledger

Every session the migration considers gets exactly one row in `migration_ledger`, and exactly
one terminal status. **Absence of a row means `NOT_PROCESSED` — never `EMPTY`.** That
distinction is the reason the table exists.

| Status | Means |
|---|---|
| `MIGRATED` | Evidence, report, claims, and review decisions were recovered. |
| `MIGRATED_WITH_MISMATCH` | Migrated, but the fidelity gate found V2 saying something different from V1. Recorded, not silently accepted. |
| `EMPTY` | The checkpoint was **read**, and the run genuinely gathered no evidence. |
| `CHECKPOINT_MISSING` | There was no snapshot at all. Not the same as `EMPTY`. |
| `READ_FAILURE` | A snapshot existed and could not be decoded. Also not the same as `EMPTY`. |
| `NO_REPORT` | The run never produced a report to migrate. |
| `INCONSISTENT_V1` | Unmigratable without inventing a fact — one of the two refusals above. |
| `FAILED` | An error during migration. **The one retryable outcome** (`--retry-failed`). |

**`EMPTY`, `CHECKPOINT_MISSING`, and `READ_FAILURE` all produce a V2 run with zero evidence,
and nothing in the V2 domain tables tells them apart.** Only the ledger does. That is why the
ledger is not dropped when the migration finishes, and why "0 evidence" read from V2 alone is
not a measured fact — `app/v2_bundle.py` consults the ledger before claiming a run gathered
nothing.

## The three gates

The tool answers three different questions and **keeps the answers separate**. Collapsing them
into one number would be the whole failure this design exists to avoid: "the migration
succeeded" can be true on all three axes for different reasons, and false on one while true on
the others.

### 1. Fidelity — *does V2 say what V1 said?*

Assembles the bundle V1 would have exported and the bundle V2 now produces, and compares them.

| Verdict | Means |
|---|---|
| `BUNDLE_EQUIVALENT` | V2's bundle carries the same research V1's did. **Representation fidelity only** — it says nothing about whether the research was any good. |
| `BUNDLE_MISMATCH` | They differ. A defect until proven otherwise. |
| `NOT_COMPARABLE` | There is no V1 bundle to compare against, and the reason is stated on both sides. |

`NOT_COMPARABLE` is **not** a soft pass, and it is not a ledger status — it is a fidelity
verdict recording that the comparison could not be made. The commonest case is
`v1=V1_STATUS_NOT_COMPLETED | v2=V2_PRESENT`: V1's own export route refuses a session that
never completed, so no V1 bundle exists — while V2 migrated the run in full. Both halves of
the reason are recorded, so a not-comparable result can never be read as "equivalent" or as
"failed".

### 2. Validity — *is the result internally consistent?*

Runs the shipped standalone verifier over the migrated bundle. The question that matters is
not "did it pass" but **"did the migration change the answer"**:

- `v1=valid → v2=invalid` — the migration broke something. **Must be zero.**
- `v1=invalid → v2=valid` — the migration *laundered* something. **Must also be zero**, and it
  is the more dangerous direction: it would mean V2 produced a verifiable artifact for research
  V1 could not verify.
- `v1=unassembled → v2=assembled` — a bundle appearing where there was none. **Zero.**

Inherited invalidity is fine and expected. A V1 draft nobody ever approved fails
`approval_chain` on both sides, because a draft nobody approved has no approval to verify. The
migration must not repair that.

### 3. Grounding — *is every migrated fact traceable to something V1 recorded?*

Every column the engine writes must be declared `FROM` (copied from a named V1 column),
`DERIVED` (computed from named V1 columns), `CONST` (a fixed value, with the reason), or `NULL`
(absent, with the reason). Three checks enforce it:

- `undeclared_columns` — the engine writes a column nothing declares. **Must be empty.**
- `stale_declarations` — a declaration describes a column the engine no longer writes. **Must
  be empty**, so the declarations cannot become a description of the past.
- `constant_violations` — a declared `CONST` does not hold in the rows actually produced.
  Checked against real output, not against the source.

## Running it

### Dry run first — and it is the default

```bash
cd backend
python -m migration.cli --database-url postgresql+asyncpg://USER@HOST/DBNAME
```

Without `--apply` the migration runs in full and **rolls back**. You get the complete report —
every ledger outcome, every gate — having written nothing.

`--database-url` is **required, and `DATABASE_URL` is never read.** A tool that defaulted to
the operator's environment would be one sourced shell away from migrating production.

Add `--report path.json` to write the full JSON report, `--limit N` to process a subset.

### Applying it

```bash
python -m migration.cli \
  --database-url postgresql+asyncpg://USER@HOST/DBNAME \
  --apply --confirm-database DBNAME
```

`--apply` refuses to run unless `--confirm-database` matches the database name in the DSN. The
target must already be at the current schema (`alembic upgrade head`).

Other flags: `--checkpoint-url` when the LangGraph checkpointer lives in a different database
(it defaults to `--database-url`), `--retry-failed` to re-attempt sessions in the `FAILED`
state, and `--resume`, which documents the default — terminal sessions are always skipped, so
re-running is safe and does not create a competing outcome.

### Recommended sequence

1. **Back up.** `pg_dump` the production database. This is the only step that touches it.
2. **Restore into a disposable copy** whose name makes it obvious it is disposable.
3. `alembic upgrade head` on the copy.
4. **Dry run** against the copy. Read every gate.
5. **Apply** to the copy, then verify the artifacts you expect to be verifiable.
6. Only then decide about the real thing.

The dry-run *tool* (`python -m migration.dryrun`) is a different program: it seeds its own V1
corpus and therefore refuses any target whose `sessions` table is not empty. It is for
exercising the migration at scale, not for rehearsing yours.

## What has actually been measured

Two validation runs, both on disposable databases.

**Synthetic** — a generated V1 corpus on both Postgres and SQLite, including planted failures,
exercising every terminal state and both refusal categories.

**Restored production** (2026-08-18) — a `pg_dump` of the real production database restored
into a disposable copy carrying **real LangGraph checkpoints**, so the evidence the migration
read is the evidence those runs actually gathered.

| | Result |
|---|---:|
| Sessions considered | 11 |
| `MIGRATED` | **11** |
| Refused / failed / retries | **0 / 0 / 0** |
| `BUNDLE_EQUIVALENT` | 7 |
| `BUNDLE_MISMATCH` | **0** |
| `NOT_COMPARABLE` | 4 — all `v1=V1_STATUS_NOT_COMPLETED \| v2=V2_PRESENT` |
| `v1=valid, v2=valid` | 7 |
| `v1=invalid, v2=invalid` | 4 — `approval_chain` on both sides, inherited |
| **Dangerous validity transitions** | **0** |
| Grounding | clean — no undeclared columns, no stale declarations, no constant violations |
| Artifacts expected to verify | **7 of 7 PASS**, all six checks, under the standalone verifier |

234 V2 rows in 0.416 s. No defects were found and no code changed as a result.

**The production database itself was never written to.** `pg_dump` was the only command that
touched it, and it was re-checked read-only afterwards: `alembic_version` still
`0015_citation_resolution_rate`, 11 sessions, 20 audit rows, 214 agent logs, 0 V2 tables —
byte-identical to the pre-run snapshot.

**The honest limit of what this proves.** That estate is small and homogeneous: 11 sessions,
all `COMPLETED` or `AWAITING_APPROVAL`, none cancelled, none with a missing or unreadable
checkpoint, none with contradictions. Six of the eight terminal states and both refusal
categories were **never exercised by real data** — they are covered only by the synthetic
corpus and the planted-failure suite. That is a property of this deployment's history rather
than a gap in the tooling, but it is the limit.

## After migrating

- The **ledger stays**. It is the record of what could and could not be recovered, and it
  outlives the migration.
- **No V2 artifacts are created.** An artifact is a frozen snapshot taken when a human
  approves, not a migrated fact. The migration records whether one *could* be authorized; it
  does not authorize one. Only an approved **REPORT** review can, and that rule is enforced in
  the database, the application, the bundle serialization, and the verifier.
- **V1 data is untouched** and the V1 API keeps serving it.

## See also

- [The V2 research model](../getting-started/24-v2-research-model.md) — what a run records and
  what approval means
- [Data model](../architecture/05-data-model.md) — every table and the migration policy
- [Bundle format](../reference/15-bundle-format.md) — what the verifier checks
