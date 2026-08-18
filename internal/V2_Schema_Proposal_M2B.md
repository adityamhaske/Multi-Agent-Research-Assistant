# M2B — Proposed V2 Relational Schema

**Status:** Proposal for review. **DESIGN ONLY.**
**Derives strictly from:** `internal/V2_Domain_Model_RFC.md` (M2A, approved with Amendment 1).
**Nothing here has been executed.** No migration exists, no table has been created, no
production code, API, frontend, LangGraph topology, `bundle_version` or `METRICS_VERSION` has
been touched.

> **The DDL in §4 is illustrative and MUST NOT be run.** It is written to be read, not
> applied. Alembic revisions are M2C's business, and no revision file exists.

---

## 0. The constraint that shapes everything

The ORM models are shared by two hosts. The server runs **Postgres via Alembic**; the desktop
sidecar runs **SQLite via `create_all`** (`app/models/types.py`, docs/13 §7). One set of model
definitions renders on both.

That is not a footnote — it decides which invariants can be enforced in the database at all:

| Mechanism | Postgres | SQLite | Usable here |
|---|---|---|---|
| `CHECK` constraints | yes | yes | **yes** |
| Partial unique indexes (`WHERE …`) | yes | yes (≥3.8) | **yes** |
| Composite foreign keys | yes | yes | **yes** |
| `ON DELETE CASCADE` / `SET NULL` | yes | yes (pragma on) | **yes** |
| Triggers | yes | yes | **no** — incompatible syntax, two hand-maintained copies |
| Column-level privileges (revoke UPDATE) | yes | no roles at all | **no** |
| `DEFERRABLE` constraints | yes | no | **no** |
| Exclusion constraints | yes | no | **no** |
| `pgvector` | yes | no | **Postgres only** — memory embeddings stay server-side, as today |

**Consequence:** immutability cannot be enforced by the database portably. Nothing stops an
`UPDATE` on an immutable column without a trigger, and a trigger would be the ninth "two homes,
one contract" hazard in this repository. Immutability is therefore **application-enforced and
verifier-enforced**, and §3 labels it that way rather than pretending otherwise.

What the database *can* enforce, it should — and §3 shows several M2A invariants that become
structural through composite foreign keys, which is the most under-used portable mechanism
available here.

---

## 1. Entity Relationship Diagram

```
                            ┌──────────┐
                            │  users   │
                            └────┬─────┘
                                 │ owner
                    ┌────────────┼───────────────────────────┐
                    ▼            ▼                           ▼
              ┌──────────┐  ┌──────────────────┐      ┌──────────────┐
              │ projects │  │ research_artifacts│      │ audit_events │
              └────┬─────┘  └────────┬─────────┘      └──────────────┘
                   │ 1..n            │                 (no FK to subject —
                   ▼                 │                  polymorphic, §3.6)
            ┌──────────────┐         │
            │ research_runs│◄────────┘ run_id (ON DELETE SET NULL)
            └──────┬───────┘
                   │
   ┌───────────────┼──────────────┬──────────────┬─────────────────┐
   ▼               ▼              ▼              ▼                 ▼
┌────────────┐ ┌─────────┐  ┌──────────┐  ┌───────────────┐ ┌─────────────┐
│research_   │ │ sources │  │ evidence │  │ contradictions│ │  revisions  │
│  plans     │ └────┬────┘  └────┬─────┘  └───────────────┘ └──────┬──────┘
│ (versioned)│      │ 1..n       │              (2 evidence refs)   │
└─────┬──────┘      └───────────►│                                  │
      │                          │                                  │ 1..n
      │                          │                                  ▼
      │                          │                            ┌──────────┐
      │                          │                            │  claims  │
      │                          │                            └────┬─────┘
      │                          │                                 │
      │                          │   ┌──────────────────────┐      │
      │                          └──►│ claim_evidence_links │◄─────┘
      │                              └──────────────────────┘
      │                                                            │
      │                                                     ┌──────▼──────────┐
      │                                                     │claim_annotations│
      │                                                     └─────────────────┘
      │                                                       (advisory only)
      │            ┌─────────┐
      └───────────►│ reviews │◄──────────── revisions
   plan_version_id └────┬────┘  revision_id
   (gate = PLAN)        │
                        │ the approving review
                        ▼
              ┌───────────────────┐
              │ research_artifacts│
              └─────────┬─────────┘
                        │ 1..n
                        ▼
        ┌───────────────────────────┐      ┌──────────────────────┐
        │ project_memory_provenance │─────►│ project_memory_items │
        └───────────────────────────┘      └──────────────────────┘
                (many-capable, §3.8)
```

Two arrows carry most of the design:

- **`reviews → research_artifacts`** is the approval boundary. An artifact cannot exist
  without an approving review, and §3.5 makes that a composite foreign key rather than a
  convention.
- **`research_artifacts → project_memory_provenance`** is the memory boundary. Memory reaches
  artifacts and nothing else.

---

## 2. Table catalogue

Column notation: **I** = immutable after insert, **M** = mutable, **D** = derived/cached.

---

### 2.1 `projects`

**Purpose.** Workspace and scoping unit. **Unchanged from V1** apart from column renames noted
in §5.

**PK** `id UUID`. **FK** `owner_id → users(id) ON DELETE CASCADE`.
**NOT NULL:** `id`, `owner_id`, `name`, `created_at`. **Nullable:** `description`,
`archived_at`.
**Unique:** `(owner_id, lower(name))` — *not adopted*; V1 permits duplicate names and nothing
in M2A requires uniqueness. Constraints are not added because they are tidy (§3.0).
**Indexes:** `(owner_id, archived_at)` — the project switcher's only query.
**Lifecycle owner:** the user.
**Immutable:** `id`, `owner_id`, `created_at`. **Mutable:** `name`, `description`,
`archived_at`.
**Deletion:** cascades to runs and memory items. **Does not cascade to artifacts or audit
events** (M2A §2.1) — see §3.7.
**Isolation:** the root of the tenant boundary.
**Versioning:** none. **Provenance:** user-authored.

---

### 2.2 `research_runs`

**Purpose.** One execution. The *execution* record, not the result (M2A §3.12).

**PK** `id UUID`. Also the LangGraph `thread_id`, as in V1.
**FK** `project_id → projects(id) ON DELETE CASCADE`, `owner_id → users(id) ON DELETE CASCADE`.

`owner_id` is denormalised from `projects`. Justified: every authorization check in the API
filters by owner, and a single-table predicate is the difference between an isolation rule
that is obviously right and one that depends on a join being written correctly every time
(M2A §2.1). Cost: one redundant column, immutable, set at insert.

**NOT NULL:** `id`, `project_id`, `owner_id`, `question`, `status`, `depth`, `corpus_mode`,
`demo`, `skip_plan_gate`, `created_at`.
**Nullable:** `model_routing`, `error_message`, `elapsed_seconds`, `cancelled_at`,
`cancel_requested_by`, `citation_resolution_rate`, `topic_seeds`, `outline_template`,
`archived_at`.

**CHECK constraints**

| Constraint | M2A invariant |
|---|---|
| `status IN ('PENDING','RUNNING','AWAITING_PLAN','AWAITING_REVIEW','COMPLETED','FAILED','CANCELLED')` | §6.1 vocabulary |
| `depth IN ('fast','balanced','comprehensive')` | run config is closed |
| `(status = 'CANCELLED') = (cancelled_at IS NOT NULL)` | §3.11 — cancellation state is durable and *coherent*; a cancelled run without a timestamp, or a timestamp without the status, is not representable |
| `cost_usd >= 0 AND tokens_input >= 0 AND tokens_output >= 0` | metrics are counts |
| `citation_resolution_rate IS NULL OR (0 <= citation_resolution_rate <= 1)` | **NULL means unmeasured** — the "unmeasured is not zero" rule made structural |

**Indexes:** see §5.
**Immutable:** `id`, `project_id`, `owner_id`, `question`, `depth`, `corpus_mode`, `demo`,
`skip_plan_gate`, `topic_seeds`, `outline_template`, `created_at`, and `model_routing` after
first resolution.
**Mutable:** `status`, metrics, `error_message`, `cancelled_at`, `cancel_requested_by`,
`archived_at`, `citation_resolution_rate` (**D**).
**Deletion:** cascades to plans, sources, evidence, revisions, contradictions, reviews.
**Sets null** on artifacts (§3.7).
**Versioning:** none — output is versioned via `revisions`.
**Provenance:** `question` and config user-authored; metrics system-measured.

---

### 2.3 `research_plans`

**Purpose.** A versioned, immutable plan proposal or edit (M2A §2.3).

**PK** `id UUID`. **FK** `run_id → research_runs(id) ON DELETE CASCADE`.
**NOT NULL:** `id`, `run_id`, `version`, `tasks`, `outline_sections`, `origin`, `created_at`.
**Nullable:** `approved_at`.

**Unique:** `(run_id, version)` — version identity.
**Partial unique:** `(run_id) WHERE approved_at IS NOT NULL` — **at most one approved plan per
run** (M2A §6.2). DB-enforced.

**CHECK:** `origin IN ('MODEL_PROPOSED','HUMAN_EDITED','TEMPLATE','UNKNOWN')`, `version >= 1`.
`UNKNOWN` exists solely for migrated V1 rows (§5) and must never be written by new code.

**Immutable:** everything except `approved_at`, which is write-once.
**Deletion:** cascades with the run.
**Versioning:** the point of the table. A human edit inserts `version + 1`; it never updates
the proposal. This is the V1 behaviour change M2A §2.3 argues for — V1 overwrote `plan_json`
and destroyed the model-vs-human diff on every run.
**Provenance:** `origin` distinguishes model output from human authorship. Never conflated.

---

### 2.4 `sources`

**Purpose.** One retrieved document. What a citation resolves *to*.

**PK** `id UUID`. **FK** `run_id → research_runs(id) ON DELETE CASCADE`.
**NOT NULL:** `id`, `run_id`, `url`, `normalized_url`, `citation_index`, `kind`,
`retrieval_status`, `retrieved_at`. **Nullable:** `title`, `corpus_document_id`.

**Unique:** `(run_id, normalized_url)` — one source row per URL per run, which is what
`graph._number_sources` already computes.
**Unique:** `(run_id, citation_index)` — `[n]` is unambiguous within a run.
**Unique:** `(id, run_id)` — *not for its own sake*; it is the composite-FK target that lets
`evidence` and `claim_evidence_links` prove same-run membership (§3.4).

**CHECK:** `kind IN ('WEB','CORPUS')`,
`retrieval_status IN ('FETCHED','SEARCH_RESULT_ONLY','FAILED','UNKNOWN')`,
`citation_index >= 1`,
`(kind = 'CORPUS') = (corpus_document_id IS NOT NULL)` — a corpus source without a document
reference, or a web source with one, is not representable.

**Immutable:** all columns.
**Deletion:** cascades with the run. **No FK to corpus documents** — `corpus_document_id` is a
plain identifier, deliberately: deleting an uploaded file must not invalidate a historical
source record (M2A §10, rejected merge of Source and corpus documents).
**Versioning:** none. The same URL in a later run is a different row (M2A §3.6).
**Provenance:** `retrieval_status` is new and load-bearing — V1 could not distinguish a fetched
page from a search-result mention, and §3.9's attestation grading needs it.

---

### 2.5 `evidence`

**Purpose.** One immutable extracted snippet with its provenance state.

**PK** `id UUID`. **FK** `run_id → research_runs(id) ON DELETE CASCADE`,
`(source_id, run_id) → sources(id, run_id)` — composite, so evidence cannot reference another
run's source. DB-enforced (§3.4).

**NOT NULL:** `id`, `run_id`, `source_id`, `sequence`, `snippet`, `content_hash`,
`provenance_state`, `created_at`. **Nullable:** `task_id`, `key_fact`, `attested_against`,
`attestation_run_at`.

**Unique:** `(run_id, sequence)` — the monotonic per-run ordering `revisions.evidence_watermark`
points into (§3.9). **Unique:** `(id, run_id)` — composite-FK target for links.

**CHECK constraints — the provenance model made structural (M2A §4):**

| Constraint | Enforces |
|---|---|
| `provenance_state IN ('ATTESTED','UNATTESTED','UNCHECKED')` | the three states, no fourth |
| `(provenance_state = 'UNCHECKED') = (attestation_run_at IS NULL)` | **UNCHECKED means the check did not run** — a timestamp on an unchecked row, or a checked row with no timestamp, is not representable |
| `(attested_against IS NOT NULL) = (provenance_state = 'ATTESTED')` | grading applies only to attestation |
| `attested_against IS NULL OR attested_against IN ('FETCHED_BODY','SEARCH_SNIPPET','CORPUS_DOCUMENT')` | closed vocabulary |
| `sequence >= 1` | ordering is positive |

These four are the most valuable constraints in the proposal. They make it **impossible to
store the "unmeasured became zero" failure**: a row cannot claim attestation without recording
when it happened, and cannot be `UNCHECKED` while carrying evidence that a check ran.

**Immutable:** every column, without exception. This is the M2A §3.7 reversal of V1 —
`verify_evidence_snippets` currently blanks `snippet` in place on failure; V2 keeps the text
and records `UNATTESTED`, because destroying fabricated text makes the fabrication
unauditable.
**Deletion:** cascades with the run.
**Versioning:** none; append-only within a run.

---

### 2.6 `revisions`

**Purpose.** One report version. **Not** a research-state snapshot (M2A §13.1).

**PK** `id UUID`. **FK** `run_id → research_runs(id) ON DELETE CASCADE`.

**NOT NULL:** every column — `id`, `run_id`, `version`, `report_markdown`, `report_hash`,
`evidence_watermark`, `created_at`. **Nullable:** none.

**Unique:** `(run_id, version)`. **Unique:** `(id, run_id)` — composite-FK target for claims.

**CHECK:** `version >= 1`, `length(report_hash) = 64`, `evidence_watermark >= 0`.

> **Amendment 2 (§9.1) removed `state` and `superseded_by_id`.** Both were derivable, and
> `state` mixed four unrelated concerns in one column. See §9.1 for the derivations. The
> table now has **zero mutable columns**.

**`evidence_watermark`** is the last `evidence.sequence` visible at synthesis (M2A §13.1).
`0` is legal and means "synthesized against no evidence", which a failed run can genuinely
produce. It is *not* a foreign key — it is a position in an append-only sequence, and pointing
it at a row would imply that row is special.

**Immutable:** **every column**, plus every `claim` and `claim_evidence_link` beneath it.
**Mutable:** none.
**Deletion:** cascades with the run, and to its claims — but a run carrying an approving
review cannot be deleted at all (§9.3).
**Versioning:** the unit of it. Rework inserts `version + 1`; nothing is overwritten.
`rework_count` is `count(revisions) - 1` and is **not stored** (M2A §3.3).

---

### 2.7 `claims`

**Purpose.** One persisted assertion belonging to one revision.

**PK** `id UUID`. **FK** `(revision_id, run_id) → revisions(id, run_id) ON DELETE CASCADE`.
**NOT NULL:** `id`, `revision_id`, `run_id`, `position`, `text`, `extraction_method`,
`verification_state`, `verification_method`, `created_at`. **Nullable:** `lineage_id`.

**Unique:** `(revision_id, position)`. **Unique:** `(id, run_id)` — composite-FK target for
links.

**CHECK:** `position >= 0`,
`extraction_method IN ('DERIVED_FROM_REPORT','MODEL_STRUCTURED','HUMAN_EDITED')`,
`verification_state IN ('SUPPORTED','UNSUPPORTED','INSUFFICIENT_EVIDENCE','UNCHECKED')`,
`verification_method IN ('NUMERIC_GROUNDING','MODEL_JUDGE','NOT_RUN')`,
`(verification_state = 'UNCHECKED') = (verification_method = 'NOT_RUN')` — the same
unmeasured-vs-measured coherence as evidence.

**`lineage_id`** is nullable and **NULL in every row V2 initially writes** (M2A §13.3). It is
reserved for when the synthesizer emits structured claims and can assign stable identity. It
is never backfilled by text matching. No index yet — an index on an all-NULL column is dead
weight; it arrives with the first non-NULL writer.

**Immutable:** all columns. A changed claim is a new claim in a new revision.
**Deletion:** cascades with the revision.
**Versioning:** via revision. **No claim is ever updated.**

---

### 2.8 `claim_evidence_links`

**Purpose.** The claim↔evidence relation. **Authoritative**; `[n]` markers in prose are a
rendering of this table (M2A C7).

**PK** `id UUID`.
**FK** `(claim_id, run_id) → claims(id, run_id) ON DELETE CASCADE`,
`(evidence_id, run_id) → evidence(id, run_id) ON DELETE CASCADE`.

Both composite, sharing the row's single `run_id` column. **This is the constraint that makes
cross-run contamination unrepresentable**: a link cannot join a claim from one run to evidence
from another, because one `run_id` must satisfy both foreign keys. DB-enforced, portable, and
it is the reason `(id, run_id)` uniques exist on the parent tables.

**NOT NULL:** all. **Unique:** `(claim_id, evidence_id)` — one link per pair; stance changes
are a new revision, not an update.

**CHECK:** `stance IN ('SUPPORTS','CONTRADICTS','CONTEXT')`,
`origin IN ('CITATION_MARKER','MODEL_ASSERTED','HUMAN_ASSERTED')`.

**Immutable:** all columns.
**Deletion:** cascades from either side.
**Provenance:** `origin = CITATION_MARKER` says plainly that a link came from a typographic
marker rather than a considered judgement (M2A §2.7).

---

### 2.9 `contradictions`

**Purpose.** A detected conflict between two evidence items. Preserved, never resolved.

**PK** `id UUID`. **FK** `run_id`, and `(evidence_a_id, run_id)` / `(evidence_b_id, run_id)` →
`evidence(id, run_id) ON DELETE CASCADE` — same-run enforcement as links.

**NOT NULL:** `id`, `run_id`, `detection_state`, `created_at`, `review_state`.
**Nullable:** `evidence_a_id`, `evidence_b_id`, `summary_a`, `summary_b`, `dimension`.

Evidence refs are nullable because `detection_state` may be `NOT_RUN` or
`DETECTOR_UNAVAILABLE`, in which case there is no pair — and recording *that the detector did
not run* is the point (M2A §2.8).

**CHECK:** `detection_state IN ('DETECTED','NOT_RUN','DETECTOR_UNAVAILABLE')`,
`dimension IS NULL OR dimension IN ('TIMEFRAME','METHODOLOGY','POPULATION','WORKLOAD','SOURCE_QUALITY','UNCLASSIFIED')`,
`review_state IN ('UNREVIEWED','ACKNOWLEDGED','DISMISSED')`,
`(detection_state = 'DETECTED') = (evidence_a_id IS NOT NULL AND evidence_b_id IS NOT NULL)`,
`evidence_a_id IS NULL OR evidence_a_id <> evidence_b_id`.

**Immutable:** all except `review_state`.
**Deletion:** cascades with the run.

---

### 2.10 `reviews`

**Purpose.** A human decision about a specific versioned object. **The only approval authority
in the system** (M2A §13.2).

**PK** `id UUID`.
**FK** `revision_id → revisions(id) ON DELETE RESTRICT`,
`reviewer_id → users(id) ON DELETE RESTRICT`,
`plan_version_id → research_plans(id) ON DELETE RESTRICT`.

**`ON DELETE RESTRICT`, not CASCADE.** M2A §2.10: a Review outlives its subject, because
deleting a run must not silently erase the record that a human approved something. Deleting a
run therefore requires dealing with its reviews explicitly — the database refuses to make that
decision quietly. See §3.7 for the ordering this imposes.

**NOT NULL:** `id`, `revision_id`, `reviewer_id`, `decision`, `gate`, `reviewed_hash`,
`created_at`. **Nullable:** `feedback`, `plan_version_id`.

**Unique:** `(id, decision)` — *not for its own sake*. It is the composite-FK target that lets
`research_artifacts` prove its review is an approval (§3.5).
**Partial unique:** `(revision_id) WHERE decision = 'APPROVED' AND gate = 'REPORT'` — **at most
one approving report review per revision.** DB-enforced (M2A §13.2, §6.1 race table).

**CHECK:** `decision IN ('APPROVED','REWORK_REQUESTED','REJECTED')`, `gate IN ('PLAN','REPORT')`,
`length(reviewed_hash) = 64`,
`(gate = 'PLAN') = (plan_version_id IS NOT NULL)` — resolves the V1 `draft_hash` overload
structurally (M2A §3.2): the hash's meaning is determined by `gate`, and a plan review without
a plan reference is not representable.

**Immutable:** every column. Reviews are never edited or deleted.
**Deletion:** never cascades away. §3.7 covers run deletion.

---

### 2.11 `claim_annotations`

**Purpose.** A reviewer's note on one claim. **Advisory. Carries no approval authority**
(M2A §13.2).

**PK** `id UUID`. **FK** `claim_id → claims(id) ON DELETE CASCADE`,
`author_id → users(id) ON DELETE CASCADE`.
**NOT NULL:** `id`, `claim_id`, `author_id`, `kind`, `created_at`. **Nullable:** `note`.
**CHECK:** `kind IN ('FLAG_UNSUPPORTED','REQUEST_EVIDENCE','COMMENT')`.

**Deliberately not in `reviews`.** Putting claim notes in the reviews table with a third `gate`
value would make them look like a third approval — the redundancy M2A §13.2 forbids. A separate
table with no `decision` column cannot be mistaken for one.

**Cascades with the claim**, which means annotations do **not** carry forward across revisions
(M2A §13.3). That is the accepted cost of not manufacturing claim lineage, and it is visible
here in the schema rather than hidden in a service.

---

### 2.12 `research_artifacts`

**Purpose.** The immutable, self-contained, hash-verifiable approved record.

**PK** `id UUID`.
**FK** `owner_id → users(id) ON DELETE CASCADE`,
`run_id → research_runs(id) ON DELETE SET NULL`,
`project_id → projects(id) ON DELETE SET NULL`,
`revision_id → revisions(id) ON DELETE SET NULL`,
`(review_id, review_decision) → reviews(id, decision)` — **composite**, with
`CHECK (review_decision = 'APPROVED')`.

**That composite FK is the load-bearing constraint of this proposal.** It makes "an artifact
exists only because an approving review exists" a database fact rather than an application
convention (M2A §13.2, §3.10). An artifact row cannot be inserted referencing a
`REWORK_REQUESTED` review; the check on the denormalised `review_decision` column and the
composite foreign key together make the alternative unrepresentable.

**`owner_id` NOT NULL is why the SET NULLs are safe.** M2A §2.1 and §2.11 require artifacts to
survive project and run deletion. Something must still own them, or a deleted project would
orphan artifacts outside every tenant boundary. `owner_id` is that anchor, and it is the one
FK that cascades.

**NOT NULL:** `id`, `owner_id`, `format_version`, `payload`, `artifact_hash`,
`review_decision`, `demo`, `created_at`.
**Nullable:** `run_id`, `project_id`, `revision_id`, `review_id` — all four may become NULL
when their subject is deleted. The artifact remains complete because the payload is a snapshot
(M2A C4, §3.9), not a set of joins.

**Unique:** `(run_id) WHERE run_id IS NOT NULL` — at most one artifact per run (M2A §6.1 race
table). Partial, so multiple orphaned artifacts remain legal after run deletion.
**Unique:** `artifact_hash` — content identity. Two artifacts with the same hash are the same
artifact.

**CHECK:** `format_version >= 1`, `length(artifact_hash) = 64`,
`review_decision = 'APPROVED'`.

**`format_version` stays 1.** M2A §3.8 — the payload is V1's bundle, unchanged, and
`verify_bundle.py` verifies it untouched.

**Immutable:** every column, always. There is no update path (M2A §6.4).
**Deletion:** explicit and separate from run deletion.
**Isolation:** `owner_id`, independent of project.

---

### 2.13 `audit_events`

**Purpose.** Append-only accountability log. **Not** the record of a decision — that is
`reviews` (M2A §3.1).

**PK** `id BIGINT` (portable autoincrement, `BigIntAutoType`).
**FK** `actor_id → users(id) ON DELETE SET NULL` — the log survives the account.
**No foreign key to the subject.** `(subject_type, subject_id)` is polymorphic by design: an
audit event may reference a row that has since been deleted, and that is exactly when it is
most needed. Labelled **impossible to enforce structurally** in §3.

**NOT NULL:** `id`, `action`, `subject_type`, `occurred_at`. **Nullable:** `actor_id`,
`subject_id`, `metadata`.
**Indexes:** `(subject_type, subject_id, id)`, `(actor_id, occurred_at DESC)`.
**Immutable:** every column. **Deletion:** never; cascades from nothing.

---

### 2.14 `project_memory_items` and `project_memory_provenance`

**Purpose.** Retrievable approved knowledge, with explicit provenance (M2A §13.5).

**Two tables, because M2A §13.5 declines to fix cardinality.** A single `artifact_id` column
would bake one-artifact-per-item into the schema on the strength of "that is what today's
chunker does" — an implementation fact, not a domain one. A link table costs one join and
leaves multi-artifact derivation available without a schema break.

**`project_memory_items`**
**PK** `id UUID`. **FK** `project_id → projects(id) ON DELETE CASCADE`.
**NOT NULL:** `id`, `project_id`, `chunk_index`, `text`, `embedding`, `embedding_model`,
`created_at`.
**Unique:** `(project_id, embedding_model, provenance_digest, chunk_index)` — idempotent
re-ingestion, which V1 achieves with a count-and-skip in application code.
**CHECK:** `chunk_index >= 0`.
**Postgres only** — `embedding` is `pgvector`, excluded from desktop `create_all` exactly as
V1's `memory_chunks` is.

**`project_memory_provenance`**
**PK** `(memory_item_id, artifact_id)`.
**FK** `memory_item_id → project_memory_items(id) ON DELETE CASCADE`,
`artifact_id → research_artifacts(id) ON DELETE CASCADE`.

**This link table is the memory boundary.** Its only artifact-side foreign key points at
`research_artifacts`, and §2.12 makes an artifact impossible without an approving review. So
"only approved research becomes memory" is enforced by two foreign keys and a check
constraint, not by a status comparison in a service (M2A §3.10). There is **no** column
anywhere that could point memory at a revision, a run, or a chat message.

**Application-enforced remainder:** that every item has *at least one* provenance row. A
"child must exist" rule is not portably expressible; §3.8 labels it.

---

## 3. Invariant enforcement register

Every invariant, with an honest label. §3.0 states the rule both directions.

### 3.0 The two rules for constraints

1. **No constraint without a domain invariant.** Convenience is not a justification. Examples
   declined: unique project names (V1 permits duplicates, M2A requires nothing), `NOT NULL` on
   `sources.title` (a title may genuinely be absent), a `CHECK` on `question` length.
2. **Every invariant that can be portably enforced in the database, is.** Where it cannot, the
   label says which weaker mechanism carries it — never silence.

### 3.1–3.12 Register

| # | Invariant (M2A ref) | Mechanism | Label |
|---|---|---|---|
| 1 | Status vocabulary is closed (§6.1) | `CHECK` on `research_runs.status` | **DB** |
| 2 | Cancellation state is coherent (§3.11) | `CHECK ((status='CANCELLED') = (cancelled_at IS NOT NULL))` | **DB** |
| 3 | **CANCELLED is absorbing** — no outcome write may leave it (§3.11, §6.1) | needs "previous value" — a trigger, not portable | **Application** + regression test. *This is the #54 guard and the most important non-DB invariant in the proposal.* |
| 4 | Unmeasured is not zero: `citation_resolution_rate` NULL vs 0 (§4) | `CHECK` range + nullable | **DB** |
| 5 | Provenance is three-valued (§4) | `CHECK provenance_state IN (…)` | **DB** |
| 6 | `UNCHECKED` ⟺ no attestation timestamp (§4) | `CHECK` equality | **DB** |
| 7 | Attestation grading only where attested (§4) | `CHECK` equality | **DB** |
| 8 | `content_hash = sha256(snippet)` (§13.4) | no portable computed-column check | **Verifier** (`verify_bundle._check_evidence_integrity`) |
| 9 | Evidence immutable (§3.7) | no portable column-level lock | **Application** + **verifier** (hashes detect it) |
| 10 | Revision text immutable (§13.1) | as above | **Application** + **verifier** (`report_hash`) |
| 11 | One approving review per revision (§13.2) | partial unique index | **DB** |
| 12 | Approval targets a *specific* revision (§13.2) | `revision_id` NOT NULL FK | **DB** |
| 13 | **Artifact requires an approving review** (§13.2) | composite FK `(review_id, review_decision)` + `CHECK review_decision='APPROVED'` | **DB** |
| 14 | One artifact per run (§6.1) | partial unique index | **DB** |
| 15 | `reviewed_hash = report_hash` for the approving review (§13.4) | cross-table equality, not portable | **Verifier** (`_check_approval_chain`) |
| 16 | Artifact hash covers the payload (§13.4) | computed at assembly | **Verifier** (`compute_bundle_hash`) |
| 17 | Artifact immutable (§6.4) | no update path in code | **Application** + **verifier** |
| 18 | Plan-gate review references a plan (§3.2) | `CHECK ((gate='PLAN') = (plan_version_id IS NOT NULL))` | **DB** |
| 19 | One approved plan per run (§6.2) | partial unique index | **DB** |
| 20 | Claims belong to one revision (§13.3) | FK + `UNIQUE(revision_id, position)` | **DB** |
| 21 | **Links never cross runs** (§2.7) | dual composite FKs sharing one `run_id` | **DB** |
| 22 | Contradiction pair coherent with detection state (§2.8) | `CHECK` equality | **DB** |
| 23 | **Memory derives only from artifacts** (§13.5) | FK to `research_artifacts` only; no other provenance column exists | **DB** |
| 24 | Every memory item has ≥1 provenance row (§13.5) | "child must exist" — not portably expressible | **Application** |
| 25 | Audit events are append-only (§2.12) | no update/delete path; no cascading FK | **Application** (structurally: no FK can delete one) |
| 26 | Audit subject may be deleted (§2.12) | polymorphic `(subject_type, subject_id)` | **Impossible to enforce structurally** — and correct: an FK would delete the log with its subject |
| 27 | Tenant isolation (§2.1) | `owner_id` on runs and artifacts; every read filters in SQL | **Application**, DB-assisted. *Row-level security is Postgres-only; the desktop has one user and no roles.* |
| 28 | `lineage_id` never assigned by text matching (§13.3) | a policy about *how* a value is computed | **Impossible to enforce structurally** — code review and the M2A record |
| 29 | Rework count is derived, not stored (§3.3) | column absent | **DB**, by omission — the strongest form |
| 30 | Report is never authoritative (C7) | claims/links/reviews exist independently of prose | **Application**, structurally supported |

**Six invariants are not DB-enforceable** (3, 8, 9, 10, 15, 24, 26, 28). Three of those — the
hash equalities — are exactly what `verify_bundle.py` already checks offline with no database
at all, which is the stronger guarantee anyway: it holds for a bundle emailed to a stranger.

---

## 4. Proposed DDL

> **Illustrative. NOT FOR EXECUTION.** Postgres dialect shown; `app/models/types.py`
> variants render the SQLite equivalents (`JSONB→JSON`, `UUID→CHAR(32)`,
> `BIGINT→INTEGER`). No Alembic revision exists.

```sql
-- ─────────────────────────────────────────────────────────────── runs

CREATE TABLE research_runs (
    id                        UUID PRIMARY KEY,
    project_id                UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    owner_id                  UUID NOT NULL REFERENCES users(id)    ON DELETE CASCADE,
    question                  TEXT NOT NULL,
    status                    VARCHAR(20) NOT NULL,
    depth                     VARCHAR(16) NOT NULL,
    corpus_mode               BOOLEAN NOT NULL DEFAULT FALSE,
    demo                      BOOLEAN NOT NULL DEFAULT FALSE,
    skip_plan_gate            BOOLEAN NOT NULL DEFAULT FALSE,
    topic_seeds               JSONB,
    outline_template          VARCHAR(64),
    model_routing             JSONB,
    cost_usd                  NUMERIC(12,6) NOT NULL DEFAULT 0,
    tokens_input              BIGINT  NOT NULL DEFAULT 0,
    tokens_output             BIGINT  NOT NULL DEFAULT 0,
    elapsed_seconds           NUMERIC(12,3),
    citation_resolution_rate  NUMERIC(5,4),          -- NULL = unmeasured, never 0
    error_message             TEXT,
    cancelled_at              TIMESTAMPTZ,
    cancel_requested_by       UUID REFERENCES users(id) ON DELETE SET NULL,
    archived_at               TIMESTAMPTZ,
    created_at                TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT ck_run_status CHECK (status IN
        ('PENDING','RUNNING','AWAITING_PLAN','AWAITING_REVIEW','COMPLETED','FAILED','CANCELLED')),
    CONSTRAINT ck_run_depth  CHECK (depth IN ('fast','balanced','comprehensive')),
    -- §3.11: cancellation is durable and coherent
    CONSTRAINT ck_run_cancelled CHECK ((status = 'CANCELLED') = (cancelled_at IS NOT NULL)),
    CONSTRAINT ck_run_metrics CHECK (cost_usd >= 0 AND tokens_input >= 0 AND tokens_output >= 0),
    -- unmeasured is NULL, not zero
    CONSTRAINT ck_run_resolution CHECK (
        citation_resolution_rate IS NULL OR
        (citation_resolution_rate >= 0 AND citation_resolution_rate <= 1))
);

-- ─────────────────────────────────────────────────────────────── plans

CREATE TABLE research_plans (
    id               UUID PRIMARY KEY,
    run_id           UUID NOT NULL REFERENCES research_runs(id) ON DELETE CASCADE,
    version          INTEGER NOT NULL,
    tasks            JSONB NOT NULL,
    outline_sections JSONB NOT NULL,
    origin           VARCHAR(16) NOT NULL,
    approved_at      TIMESTAMPTZ,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT uq_plan_version UNIQUE (run_id, version),
    CONSTRAINT ck_plan_version CHECK (version >= 1),
    CONSTRAINT ck_plan_origin  CHECK (origin IN
        ('MODEL_PROPOSED','HUMAN_EDITED','TEMPLATE','UNKNOWN'))   -- UNKNOWN: migration only
);
-- §6.2: at most one approved plan per run
CREATE UNIQUE INDEX uq_plan_approved ON research_plans (run_id) WHERE approved_at IS NOT NULL;

-- ─────────────────────────────────────────────────────────────── sources

CREATE TABLE sources (
    id                 UUID PRIMARY KEY,
    run_id             UUID NOT NULL REFERENCES research_runs(id) ON DELETE CASCADE,
    url                TEXT NOT NULL,
    normalized_url     TEXT NOT NULL,
    title              TEXT,
    kind               VARCHAR(8)  NOT NULL,
    retrieval_status   VARCHAR(20) NOT NULL,
    citation_index     INTEGER NOT NULL,
    corpus_document_id TEXT,          -- deliberately NOT a foreign key (§2.4)
    retrieved_at       TIMESTAMPTZ NOT NULL,

    CONSTRAINT uq_source_url   UNIQUE (run_id, normalized_url),
    CONSTRAINT uq_source_index UNIQUE (run_id, citation_index),
    CONSTRAINT uq_source_run   UNIQUE (id, run_id),          -- composite-FK target
    CONSTRAINT ck_source_kind  CHECK (kind IN ('WEB','CORPUS')),
    CONSTRAINT ck_source_ret   CHECK (retrieval_status IN
        ('FETCHED','SEARCH_RESULT_ONLY','FAILED','UNKNOWN')),
    CONSTRAINT ck_source_cidx  CHECK (citation_index >= 1),
    CONSTRAINT ck_source_corpus CHECK ((kind = 'CORPUS') = (corpus_document_id IS NOT NULL))
);

-- ─────────────────────────────────────────────────────────────── evidence

CREATE TABLE evidence (
    id                 UUID PRIMARY KEY,
    run_id             UUID NOT NULL REFERENCES research_runs(id) ON DELETE CASCADE,
    source_id          UUID NOT NULL,
    sequence           BIGINT NOT NULL,       -- revisions.evidence_watermark points here
    task_id            TEXT,
    snippet            TEXT NOT NULL,         -- retained even when UNATTESTED (§3.7)
    content_hash       CHAR(64) NOT NULL,
    key_fact           TEXT,
    provenance_state   VARCHAR(12) NOT NULL,
    attested_against   VARCHAR(20),
    attestation_run_at TIMESTAMPTZ,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT fk_evidence_source FOREIGN KEY (source_id, run_id)
        REFERENCES sources (id, run_id) ON DELETE CASCADE,
    CONSTRAINT uq_evidence_seq UNIQUE (run_id, sequence),
    CONSTRAINT uq_evidence_run UNIQUE (id, run_id),          -- composite-FK target

    -- §4, the provenance model made structural
    CONSTRAINT ck_ev_state CHECK (provenance_state IN ('ATTESTED','UNATTESTED','UNCHECKED')),
    CONSTRAINT ck_ev_unchecked CHECK
        ((provenance_state = 'UNCHECKED') = (attestation_run_at IS NULL)),
    CONSTRAINT ck_ev_grade CHECK
        ((attested_against IS NOT NULL) = (provenance_state = 'ATTESTED')),
    CONSTRAINT ck_ev_grade_vocab CHECK (attested_against IS NULL OR attested_against IN
        ('FETCHED_BODY','SEARCH_SNIPPET','CORPUS_DOCUMENT')),
    CONSTRAINT ck_ev_seq CHECK (sequence >= 1)
);

-- ─────────────────────────────────────────────────────────────── revisions

-- Amendment 2 (§9.1): `state` and `superseded_by_id` are REMOVED. Every value they
-- carried derives from reviews, run status, and version position. This table now has
-- ZERO mutable columns.
CREATE TABLE revisions (
    id                 UUID PRIMARY KEY,
    run_id             UUID NOT NULL REFERENCES research_runs(id) ON DELETE CASCADE,
    version            INTEGER NOT NULL,
    report_markdown    TEXT   NOT NULL,       -- immutable; the approved bytes
    report_hash        CHAR(64) NOT NULL,
    evidence_watermark BIGINT NOT NULL,       -- ordering position, not an FK (§2.6)
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT uq_revision_version UNIQUE (run_id, version),
    CONSTRAINT uq_revision_run     UNIQUE (id, run_id),      -- composite-FK target
    CONSTRAINT ck_revision_version CHECK (version >= 1),
    CONSTRAINT ck_revision_hash    CHECK (length(report_hash) = 64),
    CONSTRAINT ck_revision_wm      CHECK (evidence_watermark >= 0)
);

-- ─────────────────────────────────────────────────────────────── claims

CREATE TABLE claims (
    id                  UUID PRIMARY KEY,
    revision_id         UUID NOT NULL,
    run_id              UUID NOT NULL,
    position            INTEGER NOT NULL,
    text                TEXT NOT NULL,
    extraction_method   VARCHAR(24) NOT NULL,
    verification_state  VARCHAR(24) NOT NULL,
    verification_method VARCHAR(20) NOT NULL,
    lineage_id          UUID,                  -- reserved; NULL in every row V2 writes
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT fk_claim_revision FOREIGN KEY (revision_id, run_id)
        REFERENCES revisions (id, run_id) ON DELETE CASCADE,
    CONSTRAINT uq_claim_position UNIQUE (revision_id, position),
    CONSTRAINT uq_claim_run      UNIQUE (id, run_id),        -- composite-FK target
    CONSTRAINT ck_claim_position CHECK (position >= 0),
    CONSTRAINT ck_claim_extract  CHECK (extraction_method IN
        ('DERIVED_FROM_REPORT','MODEL_STRUCTURED','HUMAN_EDITED')),
    CONSTRAINT ck_claim_state    CHECK (verification_state IN
        ('SUPPORTED','UNSUPPORTED','INSUFFICIENT_EVIDENCE','UNCHECKED')),
    CONSTRAINT ck_claim_method   CHECK (verification_method IN
        ('NUMERIC_GROUNDING','MODEL_JUDGE','NOT_RUN')),
    CONSTRAINT ck_claim_unchecked CHECK
        ((verification_state = 'UNCHECKED') = (verification_method = 'NOT_RUN'))
);

-- ─────────────────────────────────── links: cross-run contamination impossible

CREATE TABLE claim_evidence_links (
    id          UUID PRIMARY KEY,
    run_id      UUID NOT NULL,
    claim_id    UUID NOT NULL,
    evidence_id UUID NOT NULL,
    stance      VARCHAR(12) NOT NULL,
    origin      VARCHAR(20) NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- One run_id satisfies both: a claim cannot link to another run's evidence.
    CONSTRAINT fk_link_claim FOREIGN KEY (claim_id, run_id)
        REFERENCES claims (id, run_id) ON DELETE CASCADE,
    CONSTRAINT fk_link_evidence FOREIGN KEY (evidence_id, run_id)
        REFERENCES evidence (id, run_id) ON DELETE CASCADE,
    CONSTRAINT uq_link UNIQUE (claim_id, evidence_id),
    CONSTRAINT ck_link_stance CHECK (stance IN ('SUPPORTS','CONTRADICTS','CONTEXT')),
    CONSTRAINT ck_link_origin CHECK (origin IN
        ('CITATION_MARKER','MODEL_ASSERTED','HUMAN_ASSERTED'))
);

-- ─────────────────────────────────────────────────────────────── contradictions

CREATE TABLE contradictions (
    id              UUID PRIMARY KEY,
    run_id          UUID NOT NULL REFERENCES research_runs(id) ON DELETE CASCADE,
    evidence_a_id   UUID,
    evidence_b_id   UUID,
    summary_a       TEXT,
    summary_b       TEXT,
    dimension       VARCHAR(20),
    detection_state VARCHAR(24) NOT NULL,
    review_state    VARCHAR(16) NOT NULL DEFAULT 'UNREVIEWED',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT fk_contra_a FOREIGN KEY (evidence_a_id, run_id)
        REFERENCES evidence (id, run_id) ON DELETE CASCADE,
    CONSTRAINT fk_contra_b FOREIGN KEY (evidence_b_id, run_id)
        REFERENCES evidence (id, run_id) ON DELETE CASCADE,
    CONSTRAINT ck_contra_state CHECK (detection_state IN
        ('DETECTED','NOT_RUN','DETECTOR_UNAVAILABLE')),
    CONSTRAINT ck_contra_dim CHECK (dimension IS NULL OR dimension IN
        ('TIMEFRAME','METHODOLOGY','POPULATION','WORKLOAD','SOURCE_QUALITY','UNCLASSIFIED')),
    CONSTRAINT ck_contra_review CHECK (review_state IN
        ('UNREVIEWED','ACKNOWLEDGED','DISMISSED')),
    -- a detected conflict has a pair; a detector that did not run has none
    CONSTRAINT ck_contra_pair CHECK
        ((detection_state = 'DETECTED') = (evidence_a_id IS NOT NULL AND evidence_b_id IS NOT NULL)),
    CONSTRAINT ck_contra_distinct CHECK (evidence_a_id IS NULL OR evidence_a_id <> evidence_b_id)
);

-- ─────────────────────────────────────── reviews: the only approval authority

CREATE TABLE reviews (
    id              UUID PRIMARY KEY,
    revision_id     UUID NOT NULL REFERENCES revisions(id)      ON DELETE RESTRICT,
    reviewer_id     UUID NOT NULL REFERENCES users(id)          ON DELETE RESTRICT,
    plan_version_id UUID          REFERENCES research_plans(id) ON DELETE RESTRICT,
    gate            VARCHAR(8)  NOT NULL,
    decision        VARCHAR(20) NOT NULL,
    feedback        TEXT,
    reviewed_hash   CHAR(64) NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT uq_review_decision UNIQUE (id, decision),   -- composite-FK target for artifacts
    CONSTRAINT ck_review_gate     CHECK (gate IN ('PLAN','REPORT')),
    CONSTRAINT ck_review_decision CHECK (decision IN
        ('APPROVED','REWORK_REQUESTED','REJECTED')),
    CONSTRAINT ck_review_hash     CHECK (length(reviewed_hash) = 64),
    -- §3.2: resolves the V1 draft_hash overload — the hash's meaning follows the gate
    CONSTRAINT ck_review_plan CHECK ((gate = 'PLAN') = (plan_version_id IS NOT NULL))
);
-- §13.2: at most one approving report review per revision
CREATE UNIQUE INDEX uq_review_approval ON reviews (revision_id)
    WHERE decision = 'APPROVED' AND gate = 'REPORT';

CREATE TABLE claim_annotations (           -- advisory; no decision column, by design
    id         UUID PRIMARY KEY,
    claim_id   UUID NOT NULL REFERENCES claims(id) ON DELETE CASCADE,
    author_id  UUID NOT NULL REFERENCES users(id)  ON DELETE CASCADE,
    kind       VARCHAR(24) NOT NULL,
    note       TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT ck_annotation_kind CHECK (kind IN
        ('FLAG_UNSUPPORTED','REQUEST_EVIDENCE','COMMENT'))
);

-- ───────────────────────────────── artifacts: approval is a database fact

CREATE TABLE research_artifacts (
    id              UUID PRIMARY KEY,
    owner_id        UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,  -- survives project
    run_id          UUID REFERENCES research_runs(id) ON DELETE SET NULL,
    project_id      UUID REFERENCES projects(id)      ON DELETE SET NULL,
    revision_id     UUID REFERENCES revisions(id)     ON DELETE SET NULL,
    review_id       UUID,
    review_decision VARCHAR(20) NOT NULL,
    format_version  INTEGER  NOT NULL DEFAULT 1,      -- V1 bundle format, unchanged
    payload         JSONB    NOT NULL,                -- the frozen snapshot (C4)
    artifact_hash   CHAR(64) NOT NULL,
    demo            BOOLEAN  NOT NULL DEFAULT FALSE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- The load-bearing constraint: an artifact exists only because approval exists.
    CONSTRAINT fk_artifact_review FOREIGN KEY (review_id, review_decision)
        REFERENCES reviews (id, decision) ON DELETE SET NULL,
    CONSTRAINT ck_artifact_approved CHECK (review_decision = 'APPROVED'),
    CONSTRAINT uq_artifact_hash UNIQUE (artifact_hash),
    CONSTRAINT ck_artifact_format CHECK (format_version >= 1),
    CONSTRAINT ck_artifact_hashlen CHECK (length(artifact_hash) = 64)
);
CREATE UNIQUE INDEX uq_artifact_run ON research_artifacts (run_id) WHERE run_id IS NOT NULL;

-- ─────────────────────────────────────────────────────────────── audit

CREATE TABLE audit_events (
    id           BIGSERIAL PRIMARY KEY,
    actor_id     UUID REFERENCES users(id) ON DELETE SET NULL,
    action       VARCHAR(48) NOT NULL,
    subject_type VARCHAR(32) NOT NULL,
    subject_id   UUID,                 -- polymorphic: no FK, deliberately (§2.13)
    metadata     JSONB,
    occurred_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ────────────────────────────── memory: provenance to artifacts only

CREATE TABLE project_memory_items (
    id                UUID PRIMARY KEY,
    project_id        UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    chunk_index       INTEGER NOT NULL,
    text              TEXT NOT NULL,
    embedding         VECTOR(768) NOT NULL,     -- Postgres/pgvector only
    embedding_model   VARCHAR(128) NOT NULL,
    provenance_digest CHAR(64) NOT NULL,        -- of the ordered artifact-hash set
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT uq_memory_chunk UNIQUE (project_id, embedding_model, provenance_digest, chunk_index),
    CONSTRAINT ck_memory_chunk CHECK (chunk_index >= 0)
);

CREATE TABLE project_memory_provenance (
    memory_item_id UUID NOT NULL REFERENCES project_memory_items(id)  ON DELETE CASCADE,
    artifact_id    UUID NOT NULL REFERENCES research_artifacts(id)    ON DELETE CASCADE,
    PRIMARY KEY (memory_item_id, artifact_id)
);
-- The only artifact-side FK in the memory subsystem. No column anywhere can point
-- memory at a revision, a run, or a chat message.
```

---

## 5. Index Strategy

Indexes derived from queries the code actually issues, not from column types. Primary keys and
unique constraints already provide their own indexes and are not repeated.

| Index | Access pattern | Evidence it is real |
|---|---|---|
| `research_runs (project_id, archived_at, created_at DESC)` | The history list: this user's project, unarchived, newest first, paged | `research.list_sessions` filters exactly these three and orders by `created_at DESC` |
| `research_runs (owner_id, status)` | "Do I have anything running?"; usage roll-ups | `usage.summary` aggregates by owner |
| `revisions (run_id, version DESC)` | Latest revision for a run — the hot read on every session detail page | one query per page load |
| `claims (revision_id, position)` | Render a revision's claims in order | covered by `uq_claim_position`; listed for visibility |
| `claim_evidence_links (claim_id)` | "What supports this claim?" — the review panel's main query | one per claim expansion |
| `claim_evidence_links (evidence_id)` | **Reverse:** "Which claims cite this evidence?" — the evidence drawer | the direction V1 cannot answer at all, since links exist only as prose markers |
| `evidence (run_id, sequence)` | Bundle assembly; watermark range scans | covered by `uq_evidence_seq` |
| `evidence (source_id)` | Source detail: its extracted snippets | citation drawer |
| `sources (run_id, citation_index)` | `[n]` → source resolution | covered by `uq_source_index` |
| `reviews (revision_id, created_at)` | The approval chain, in order, for the bundle | `export_bundle_json` orders audit rows ascending today |
| `research_artifacts (owner_id, created_at DESC)` | An artifacts list, independent of project | survives project deletion, so it cannot be reached by project |
| `audit_events (subject_type, subject_id, id)` | "What happened to this run?" | the accountability query |
| `audit_events (actor_id, occurred_at DESC)` | "What has this account done?" | the other accountability query |
| `project_memory_items` HNSW on `embedding`, filtered by `(project_id, embedding_model)` | Vector retrieval within one project and one model | `memory.retrieve` filters both before ordering by distance — V1's index shape, kept |

**Deliberately not indexed**

| Not indexed | Why |
|---|---|
| `claims.lineage_id` | NULL in every row V2 writes (M2A §13.3). An index on an all-NULL column is pure write cost. It arrives with the first non-NULL writer. |
| `evidence.content_hash` | Nothing looks evidence up by hash; the verifier recomputes and compares in memory. |
| `revisions.report_hash` | Same — verification is offline, not a lookup. |
| `sources.url` (unnormalised) | All lookups go through `normalized_url`. |
| `research_runs.question` | No search feature exists. Full-text search would be a different index and a different decision. |
| `contradictions.dimension` | Low cardinality, tiny table, always read with its run. |

---

## 6. Migration Mapping

**Rule: V1 uncertainty must never become V2 certainty.**

### 6.1 Field-by-field

| V1 | V2 destination | Transformation | Provenance status | Discarded? |
|---|---|---|---|---|
| `projects.*` | `projects.*` | rename `user_id`→`owner_id` | certain | no |
| `sessions.id` | `research_runs.id` | direct | certain | no |
| `sessions.user_id` | `research_runs.owner_id` | direct | certain | no |
| `sessions.project_id` | `research_runs.project_id` | direct | certain | no |
| `sessions.prompt` | `research_runs.question` | direct | certain | no |
| `sessions.status` | `research_runs.status` | `AWAITING_APPROVAL`→`AWAITING_REVIEW` | certain | no |
| `sessions.research_depth`, `corpus_mode`, `demo`, `skip_plan_gate`, `topic_seeds`, `outline_template` | `research_runs.*` | direct | certain | no |
| `sessions.model_routing`, cost, token counts, `elapsed_seconds`, `error_message`, `archived_at`, timestamps | `research_runs.*` | direct | certain | no |
| `sessions.citation_resolution_rate` | `research_runs.citation_resolution_rate` | direct; **NULL stays NULL** | certain | no |
| `sessions.final_report` / `draft_report` | **one** `revisions` row, `version = 1` | `final_report` preferred; `report_hash = sha256(text)`; `evidence_watermark` = max evidence sequence, else 0 | certain for the surviving text | **yes — earlier drafts** |
| `sessions.sources` (JSON) | `sources` rows | one row per array entry; `citation_index` from `index`; `kind` from `corpus://` prefix; `retrieval_status = 'UNKNOWN'` | url/title/index certain; **retrieval status unknown** | no |
| `sessions.plan_json` + `outline_json` + `plan_approved_at` | **one** `research_plans` row, `version = 1` | `origin = 'UNKNOWN'` | **plan certain, authorship unknown** — V1 overwrote the proposal with the approved plan | no |
| `sessions.rework_count` | *nothing* | becomes `count(revisions) - 1` | derived | **yes — as a stored value** |
| `audit_log` (`approved` / `rework_requested`) | `reviews`, `gate='REPORT'` | `draft_hash`→`reviewed_hash`; `revision_id` = the single migrated revision | certain | no |
| `audit_log` (`plan_approved`) | `reviews`, `gate='PLAN'` | `draft_hash`→`reviewed_hash`; `plan_version_id` = the migrated plan | hash is **opaque** — nothing has ever verified it (M2A §8) | no |
| `audit_log` (all rows) | `audit_events` **as well** | one event per row; the §3.1 split writes both | certain | no |
| checkpoint `state["evidence"]` | `evidence` rows | `provenance_state='UNCHECKED'`, `attested_against=NULL`, `attestation_run_at=NULL` | **UNCHECKED — never ATTESTED** | no, where the checkpoint survives |
| checkpoint `state["contradictions"]` | `contradictions` rows | `detection_state='DETECTED'` where pairs exist, else `NOT_RUN` | pairs certain; absence ambiguous | no |
| checkpoint everything else | *nothing* | execution state (M2A §3.4) | n/a | **yes** |
| `agent_logs` | unchanged | referenced by artifacts as trace | certain | no |
| `memory_chunks` | `project_memory_items` + provenance rows | re-pointed from `source_session_id` to the run's artifact | certain **once artifacts are backfilled** | no |
| Redis `session:{id}:cancelled` | *nothing* | write-only, TTL'd, never read (#54) | n/a | **yes** |
| `chat_messages`, `chat_threads` | unchanged | out of scope for this RFC | n/a | no |
| — | `claims`, `claim_evidence_links` | **derived** by `claims.claim_lines` + `[n]` parsing over the migrated report | `extraction_method='DERIVED_FROM_REPORT'`, `verification_state='UNCHECKED'`, link `origin='CITATION_MARKER'`, `stance='SUPPORTS'` | derived-at-migration, recorded as such | n/a |
| — | `research_artifacts` | assembled for `COMPLETED` runs with an approving review | `format_version = 1` | n/a |

### 6.2 The one that matters most

**V1 evidence migrates as `UNCHECKED`, never `ATTESTED`.** The temptation is real: the text is
there, the in-graph check usually ran, the row looks fine. But "usually ran" is not "ran for
this item" — V1's check is skipped entirely in fake mode, records nothing per item, and
*blanks* the snippet on failure rather than flagging it. Marking these `ATTESTED` would write a
verification claim that nobody made.

The `CHECK` constraint on `evidence` makes this structural rather than disciplinary: a row
claiming `ATTESTED` must carry `attestation_run_at`, and the migration has no honest value to
put there.

A V1 row with an **empty** snippet is doubly ambiguous — fabricated-and-blanked, absent, or
never populated. It migrates as `UNCHECKED` with empty text and no inference.

---

## 7. Migration Safety

### 7.1 Ordering

Strictly additive. **No V1 table or column is dropped in M2.**

| Phase | Action | Reversible? |
|---|---|---|
| **P0** | Create V2 tables. Nothing reads or writes them. | yes — drop |
| **P1** | Dual-write: new runs populate V1 *and* V2. V1 stays authoritative for every read. | yes — stop writing |
| **P2** | Backfill historical runs per §6. | yes — truncate V2 |
| **P3** | **Verification gate** (§7.5). No flip until it passes. | n/a |
| **P4** | Flip reads to V2, one surface at a time. V1 columns still written. | yes — flip back |
| **P5** | *A later milestone.* Stop dual-writing; deprecate V1 columns. | **first irreversible step** |

P5 is deliberately outside M2.

### 7.2 Dual-write

Required, for P1–P4. Both writes occur in **one transaction** — the existing pattern for
audit rows (`db.add(...)` then a single `commit`), so a partial write is not representable.

Dual-write is the risky phase, because a V2 write path with a bug corrupts V2 silently while
V1 stays correct and every user-facing surface looks fine. §7.5's gate is what catches that,
and it must run **continuously during P1**, not once at the end.

### 7.3 Rollback

| Phase | Rollback |
|---|---|
| P0–P2 | Ignore or truncate V2. V1 untouched and authoritative. |
| P4 | Flip the read path back. V1 columns are still being written, so no data is lost. A per-surface feature flag makes this a config change, not a deploy. |
| P5 | Requires a restore. This is why P5 is a separate milestone with its own gate. |

### 7.4 Compatibility window

V1 columns remain written and correct for **at least one full release after P4**. During the
window:

- `bundle_version` / `format_version` stays **1**. Bundles exported before, during and after
  migration verify with the same unmodified `verify_bundle.py`.
- `METRICS_VERSION` stays **4**. No metric definition changes, so eval results before and after
  remain comparable.
- The API contract is unchanged; `tests/test_host_parity.py` passes throughout, including
  `KNOWN_DESKTOP_GAPS == {}`.
- The desktop host migrates on the same schedule — `create_all` builds the same tables minus
  `project_memory_items` (pgvector), exactly as it excludes `memory_chunks` today.

### 7.5 The verification gate — byte-identical historical artifacts

The gate on P4, and the strongest check available.

**Method.** For every historical run that reached `COMPLETED` with an approving review:

1. Assemble a bundle through the **V1 path** — session row, checkpoint, `audit_log`,
   `agent_logs` — using `bundle.assemble`.
2. Assemble a bundle through the **V2 path** — runs, revisions, sources, evidence, claims,
   links, reviews — using the *same* `bundle.assemble`.
3. Inject an identical `created_at` into both. This is the only field that must be normalised:
   V1 stamps assembly time, so two assemblies of the same session legitimately differ (M2A
   §13.4 notes storing once fixes this permanently).
4. Compare `bundle.serialize(...)` output **byte for byte**.
5. Any difference fails the gate and blocks P4.

This is the technique that proved M0A behaviour-preserving — a golden diff over a real corpus,
not a spot check — and it is available here for the same reason: `bundle.assemble` is pure, has
no DB access, and takes plain data from either source.

**What it proves:** the V2 tables contain everything needed to reconstruct exactly what V1
produced. **What it does not prove:** that V2 captures anything V1 never had — attestation
states, plan authorship, superseded drafts. Those are §6's unverifiable rows, and no gate can
recover them.

**Runs it cannot cover**, which must be counted and reported rather than passed over:
runs whose checkpoint was pruned (no evidence to compare), runs never approved (no artifact),
and demo runs (included, but they prove less). A gate that silently skips is the failure this
whole project is about.

---

## 8. Open Questions

Only what remains after M2A. Each blocks a specific decision, not the schema as a whole.

1. ~~**Does `evidence.sequence` survive parallel research?**~~ **RESOLVED — §9.2: gaps accepted.**
   <sub>Original question retained for the record.</sub>
   **Does `evidence.sequence` survive parallel research?** `executor_node` runs tasks
   concurrently; assigning a gap-free monotonic sequence across concurrent writers needs either
   a per-run counter under a lock, or acceptance of gaps. Gaps are harmless for a watermark
   (it is a threshold, not a count) but would make `sequence` useless as an ordinal. **Leaning:
   allow gaps, document it, order by `(sequence, id)`.**
2. **Is `payload JSONB` the right artifact storage?** A large artifact with a full trace could
   reach several MB. JSONB is queryable but not the cheapest; a blob column or object storage
   would be. M2A §11.6 defers this and the schema is agnostic — the column type can change
   without touching the domain.
3. ~~**What deletes a run whose reviews are `ON DELETE RESTRICT`?**~~ **RESOLVED — §9.3: nothing does; archive is the operational path.**
   **What deletes a run whose reviews are `ON DELETE RESTRICT`?** The application must either
   refuse to delete runs that carry reviews, or explicitly detach them. This is a *product*
   question (may a user delete research they approved?) with a schema consequence. §2.10 states
   the invariant; the workflow is unresolved.
4. **`provenance_digest` on memory items** assumes memory identity derives from its artifact
   set. If a future item derives from a *subset* of an artifact, the digest is insufficient.
   Adequate for one-artifact-per-item, which is all M2A commits to.
5. **Does the desktop host need `research_artifacts.owner_id`?** It has exactly one user. The
   column is harmless there and load-bearing on the server; keeping one schema is worth a
   redundant column, but it is worth naming as a deliberate cost.
6. ~~**Should `revisions.state` exist at all?**~~ **RESOLVED — §9.1: removed, along with `superseded_by_id`.**
   **Should `revisions.state` exist at all,** or be derived from the presence of reviews and
   `superseded_by_id`? It is currently the only mutable column pair on an otherwise immutable
   table, and derived state cannot drift. **Leaning: derive it**, but that changes read paths
   and belongs in M2C.
7. **Retention for orphaned artifacts.** After a project is deleted, artifacts persist with
   `project_id = NULL`, owned by the user. Nothing lists them today. A product decision
   (M2A §11.7) with an index consequence (§5 already anticipates `(owner_id, created_at)`).

---

## 9. Amendment 2 — decisions taken at M2B review

Six items. §§1–8 stand except where §9.7 records a change.

---

### 9.1 `revisions.state` is removed

**Challenge:** demonstrate a lifecycle state that cannot be derived, or derive it.

**It cannot be demonstrated. The column is removed.** So is `superseded_by_id`.

`state` was mixing four unrelated concerns in one field, which is exactly the objection:

| Value | Concern |
|---|---|
| `DRAFT`, `UNDER_REVIEW` | generation lifecycle |
| `REWORK_REQUESTED` | review decision |
| `APPROVED` | approval |
| `SUPERSEDED` | supersession |

Each derives from an authoritative fact that already exists:

| Derived value | Derivation |
|---|---|
| `APPROVED` | `EXISTS(review WHERE revision_id = r AND gate='REPORT' AND decision='APPROVED')` |
| `REWORK_REQUESTED` | `EXISTS(review WHERE revision_id = r AND decision='REWORK_REQUESTED')` |
| `SUPERSEDED` | `EXISTS(revision WHERE run_id = r.run_id AND version > r.version)` |
| `UNDER_REVIEW` | no review for `r`, `r` is the highest version, and `run.status = 'AWAITING_REVIEW'` |
| `DRAFT` | no review for `r`, `r` is the highest version, and `run.status <> 'AWAITING_REVIEW'` |

**`superseded_by_id` goes with it.** Rework is linear — `graph.route_after_gate` has exactly
one rework path, back to the synthesizer, which inserts `version + 1`. There is no branching,
so "the revision that superseded this one" is `version + 1` of the same run and needs no
column.

**Result: `revisions` has zero mutable columns.** Every column is immutable, which is a
materially stronger property than M2A §13.1 asked for — it said `state` and `superseded_by_id`
were "exactly the two mutable columns permitted", and it turns out neither is needed. A table
with no mutable columns cannot drift from the facts it is supposed to reflect, because it
reflects none.

**Presentation.** A `revision_lifecycle` **view** (or a computed property) supplies the five
labels for the UI. Derived, never stored.

**When this decision reverses.** If revision branching is ever introduced — a human editing an
earlier revision to create an alternative rather than a successor (M2A §11.2) —
`superseded_by_id` becomes an authoritative fact again and must return. Recorded so the
reversal is a decision rather than a rediscovery.

---

### 9.2 `evidence.sequence` accepts gaps

**Decision: gaps are permitted and expected. No locking, no serialization.**

`executor_node` researches pending tasks concurrently, bounded by `max_parallel_tasks`.
Guaranteeing contiguous numbers across concurrent writers requires either a per-run lock or a
serialized allocator, and both would slow the pipeline's hot path to buy a property nothing
needs.

**`sequence` is an ordering value, not a gap-free ordinal.** It answers "was this evidence
gathered before that evidence", never "how many evidence items exist" — that is `COUNT(*)`.

**Deterministic ordering is `(sequence, id)`.** `sequence` alone can tie under concurrency;
`id` breaks the tie stably, so two reads of the same run return the same order.

`revisions.evidence_watermark` is unaffected: it is a **threshold**, not a count. "All evidence
with `sequence <= watermark`" is exact whether or not the numbers are contiguous.

The `CHECK (sequence >= 1)` constraint stays. `UNIQUE (run_id, sequence)` stays — gaps are
fine, duplicates are not, because a duplicate makes the watermark ambiguous.

---

### 9.3 Approved research is not destroyed by the ordinary deletion path

**Product decision, recorded here. No retention framework is built in M2B.**

Three distinct operations, deliberately not conflated:

| Operation | Meaning | Availability |
|---|---|---|
| **Archive** | Operational removal from the working view. Reversible, loses nothing. | Always. |
| **Delete** | Destroys the run and everything derived from it. | **Only when the run carries no approving review.** |
| **Permanent destruction of approved research** | Erasing an artifact and its provenance chain. | **Deferred.** Not available. |

**Approved research must not be hard-deleted in a way that invalidates
Review → Artifact → Memory provenance.** An artifact whose approving review has been erased
cannot be verified: `verify_bundle._check_approval_chain` would find a chain referencing a
decision that no longer exists, and the artifact would fail for a reason that has nothing to do
with its integrity.

**The schema already enforces this**, which is why no new constraint is needed:

```
DELETE research_runs
   → CASCADE revisions
       → RESTRICT reviews.revision_id     ← the delete fails here
```

`reviews.revision_id` is `ON DELETE RESTRICT` (§2.10), so deleting a run that carries any
review — approving or not — is refused by the database. Deleting a *project* fails the same
way, through the same chain. **DB-enforced**, portable, already in the §4 DDL.

**Application obligation:** the delete endpoint must detect this before attempting it and
return a clear refusal offering archive, rather than surfacing a foreign-key error. V1's
`DELETE /research/{id}` already refuses a RUNNING session with a specific message; this is the
same shape of guard.

**Explicitly deferred:** retention windows, legal-hold, redaction of approved research,
cascading artifact destruction, and any GDPR-style erasure path. Each needs a product decision
this RFC has no basis to make. What is settled is only that the *ordinary* delete path cannot
reach approved research.

---

### 9.4 Invariant Ownership Matrix

Supersedes the register in §3 by adding the reason each invariant sits where it does. The
labels are unchanged; what follows is *why*.

**DB-enforced** — a constraint makes the violation unrepresentable, portably on Postgres and
SQLite.

| Invariant | Mechanism | Why the DB can own it |
|---|---|---|
| Status/decision/state vocabularies are closed | `CHECK … IN (…)` | Value-level; no cross-row knowledge needed |
| Cancellation coherence (`status`↔`cancelled_at`) | `CHECK` equality | Both columns in the same row |
| Unmeasured is NULL, never 0 | nullable + range `CHECK` | Same row |
| Three-valued provenance and its coherence rules | 4 `CHECK`s on `evidence` | Same row; this is why the provenance model was designed as same-row columns rather than a side table |
| One approving review per revision | partial unique index | Single-table uniqueness |
| One approved plan per run | partial unique index | Single-table uniqueness |
| One artifact per run | partial unique index | Single-table uniqueness |
| **Artifact requires an approving review** | composite FK + `CHECK` | The denormalised `review_decision` brings the other table's fact into this row, where a `CHECK` can see it |
| **Links never cross runs** | dual composite FKs sharing one `run_id` | One column must satisfy two parent keys |
| Plan review references a plan | `CHECK ((gate='PLAN') = (plan_version_id IS NOT NULL))` | Same row |
| Contradiction pair ↔ detection state | `CHECK` equality | Same row |
| **Memory derives only from artifacts** | the only artifact-side FK points at `research_artifacts` | Absence of any alternative column is the enforcement |
| **Approved research survives ordinary deletion** | `ON DELETE RESTRICT` chain (§9.3) | Referential action |
| Rework count is not stored | column absent | The strongest form: unrepresentable |

**Application-enforced** — requires knowledge the database cannot portably see.

| Invariant | Why not the DB |
|---|---|
| **CANCELLED is absorbing** | Needs the *previous* value of a column. That is a trigger, and triggers are not portable across Postgres and SQLite (§0). Carried by code plus a regression test — this is issue #54's guard and the most important non-DB invariant here. |
| Evidence / revision / claim / artifact immutability | Requires blocking `UPDATE`, i.e. a trigger or column privileges. Neither is portable. Mitigated: hashes make violations *detectable* even though they are not preventable. |
| Every memory item has ≥1 provenance row | "A child row must exist" is not expressible as a constraint on the parent. |
| Audit events are append-only | No portable way to forbid `UPDATE`/`DELETE`. Structurally assisted: no FK cascades into the table, so nothing deletes one as a side effect. |
| Tenant isolation | Row-level security is Postgres-only and the desktop has no roles. `owner_id` makes the predicate cheap and obvious; writing it remains the application's job. |
| Delete refusal returns a helpful error | The DB refuses correctly (§9.3); only the *message* is the application's. |

**Verifier-enforced** — checked offline by `verify_bundle.py`, with no database at all.

| Invariant | Why this is the right owner |
|---|---|
| `content_hash = sha256(snippet)` | The check must hold for a bundle emailed to a stranger who has no access to our database. A DB constraint would not travel with the artifact. |
| `report_hash = sha256(report_markdown)` | Same. |
| `reviewed_hash = report_hash` for the approving review | Cross-table equality; and again, it must be checkable off-system. This is the load-bearing approval check. |
| `artifact_hash` covers the payload | Computed at assembly, verified anywhere. |

That these three live in the verifier is a **strength, not a gap**. A database constraint
protects our data; a verifier protects a third party who does not trust our database.

**Structurally unenforceable** — no mechanism at any level can prevent it.

| Invariant | Why |
|---|---|
| Audit subject may reference a deleted row | `(subject_type, subject_id)` is polymorphic. An FK is not merely impractical here — it would be *wrong*, since it would delete the audit record together with the thing it documents. |
| `lineage_id` is never assigned by text matching | A rule about *how* a value is computed, not about the value. Only code review and the M2A record carry it. |
| Migrated evidence is honestly `UNCHECKED` | The DB cannot know whether V1 ran a check. The `CHECK` constraint makes an *inconsistent* claim unrepresentable, which is the closest structural approximation available. |
| The report is never authoritative (C7) | An architectural property of how code reads data. Supported structurally — claims, links and reviews exist independently of prose — but not enforceable. |

---

### 9.5 The JSON escape hatch

**Rule: core domain facts are relational and queryable. JSON is for genuinely extensible
metadata, and never a substitute for a table.**

JSON must **never** hold claims, evidence, reviews, provenance, artifact relationships, or
lifecycle state. Those are precisely the things V1 kept as JSON blobs and checkpoint state,
and precisely why they could not be queried, constrained, or trusted.

Every JSON column in §4, justified:

| Column | Verdict | Justification |
|---|---|---|
| `research_runs.topic_seeds` | **allowed** | A user-supplied list of strings. No query targets an individual seed. |
| `research_runs.model_routing` | **allowed** | A small `role → route` map whose keys are open (a sixth role could be added). Read whole, never filtered by. |
| `research_plans.tasks`, `.outline_sections` | **allowed, and the closest call** | Read, edited and versioned as one immutable unit; nothing queries an individual task. **If a query ever needs individual tasks** — recurring topics across runs, per-task completion metrics — they become a table. Recorded so that change is a decision, not a workaround. |
| `audit_events.metadata` | **allowed** | Explicitly the extensibility slot; different actions carry different details. |
| `research_artifacts.payload` | **allowed — and required to be JSON** | It is a frozen snapshot for external verification (M2A C4), not a queryable domain fact. Its relational equivalents live in `claims`, `evidence`, `reviews` and are authoritative; the payload is the copy a third party verifies. Making it relational would defeat its purpose. |

**Declined by this rule:** storing claims or links inside `revisions` as JSON, storing the
review chain inside the artifact row only, and keeping `sources` as a JSON array — all three
being what V1 does.

---

### 9.6 Denormalization register

Every intentionally duplicated field, with the constraint that prevents disagreement. Nothing
here is convenience.

| Field | Why duplicated | Authoritative source | What prevents disagreement |
|---|---|---|---|
| `research_runs.owner_id` | Every authorization predicate becomes single-table. An isolation rule that needs a join is one a future query will get wrong. | `projects.owner_id` | Immutable, set at insert. **Gap: project ownership transfer is not modelled**; if it is ever added, it must update runs and artifacts in the same transaction. Recorded as a known obligation. |
| `evidence.run_id`, `revisions.run_id`, `claims.run_id`, `claim_evidence_links.run_id`, `contradictions.run_id` | Composite-FK targets for same-run enforcement, and single-hop scoping | the parent chain | **Self-enforcing.** The composite FK means a wrong `run_id` cannot resolve to a parent row at all. Disagreement is unrepresentable, not merely detected. |
| `research_artifacts.review_decision` | Brings the review's decision into the artifact row so a `CHECK` can see it | `reviews.decision` | The composite FK `(review_id, review_decision) → reviews(id, decision)`. Changing a review's decision would break the reference. |
| `research_artifacts.owner_id` | The artifact must survive project and run deletion and still be owned by someone (§2.12) | `projects.owner_id` at creation | Immutable. Once `project_id` goes NULL there is nothing left to disagree *with* — which is the intent. |
| `research_artifacts.project_id` | Convenience for listing | the run's project | **Accepted divergence**: becomes NULL on project deletion while the payload still names the project. This is snapshot semantics (M2A §3.9), not drift. |
| `evidence.content_hash` | The artifact must be verifiable offline | `snippet` | Verifier recomputes. Divergence *is* the tamper signal. |
| `revisions.report_hash` | Same | `report_markdown` | Same |
| `research_runs.citation_resolution_rate` | List views must not recompute per row | Revision + Sources | Recomputable. NULL means unmeasured, so a stale cache degrades to "unmeasured", never to a wrong number. |
| `project_memory_items.provenance_digest` | Idempotent re-ingestion without a group-by over the link table | the ordered artifact-hash set | Recomputable from `project_memory_provenance`. |

**Rejected as convenience denormalization:** `project_id` on evidence/claims/links (one extra
hop through `run_id` is enough), a cached `revision_count` on runs, a cached
`latest_revision_id` on runs, and a denormalised `owner_id` on every child table.

---

### 9.7 Effect on §§1–8

| Section | Change |
|---|---|
| §2.6 `revisions` | **Amended** — `state` and `superseded_by_id` removed; the table is now fully immutable (§9.1). |
| §2.5 `evidence` | Clarified — `sequence` may have gaps; order by `(sequence, id)` (§9.2). |
| §3 register | **Extended** by §9.4, which adds the reason for each label. Labels unchanged. |
| §4 DDL | `revisions` updated; nothing else. |
| §5 Index Strategy | `revisions (run_id, version DESC)` now also serves supersession and lifecycle derivation, strengthening its justification. |
| §8 Open Questions | Q1 (`sequence` gaps) **resolved** by §9.2. Q6 (`revisions.state`) **resolved** by §9.1. Q3 (deleting approved research) **resolved** by §9.3. Q5, Q2, Q4, Q7 remain open. |

Nothing in §§1, 6, 7 changes.

---

---

## 10. Out of scope for M2B

No migration executed, no table created, no Alembic revision authored, no production code, API,
frontend or LangGraph change, no `bundle_version` change, no `METRICS_VERSION` change, no data
migrated. The DDL in §4 is illustrative and has not been run against any database.

M2C, if this is approved, should be the **Alembic revision plan** — revision ordering,
`create_all` parity for the desktop host, and the dual-write implementation plan — reviewed on
its own before any table exists.
