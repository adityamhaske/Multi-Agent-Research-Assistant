# M2F Amendment — fidelity findings as explicit V2 domain invariants

**Status:** amendment to `V2_Migration_Fidelity_M2F.md`. **Documentation only.**
**No schema changed. No code changed. Production untouched. S1–S6 and M1–M6 remain unimplemented.**
**Supersedes** M2F §6–§9 where marked; M2F otherwise stands.

---

## 1. Amendment purpose

M2F answered *what was lost*. It did not state, in a form anything can be tested against,
*what V2 must guarantee instead*. This amendment converts the approved findings into numbered
invariants (I1–I14), each with a named enforcement layer and an acceptance test.

It also acts on a finding M2E-2 produced late and M2F recorded only as a footnote: **the dry-run
bundles used for equivalence do not pass the shipped standalone verifier.** That is not a
detail. It means "the V2 representation equals the V1 representation" and "the V2 bundle is
internally valid" are different properties that were being reported as one, and a migration
could satisfy the first while failing the second on every run. Three properties are therefore
separated here and must never be collapsed again:

| | Property | Question it answers |
|---|---|---|
| **A** | Representational fidelity | Does V2 say what V1 said? |
| **B** | Internal bundle validity | Does the V2 bundle pass `verify_bundle` on its own terms? |
| **C** | Historical non-fabrication | Is every migrated fact traceable to something V1 recorded? |

A bundle can be **equivalent but invalid** (the entire M2E-2 corpus). It can be **valid but
intentionally lossy**. It can be **non-comparable** and still be required to be non-fabricated.
No two of the three imply the third.

---

## 2. Changes from the original M2F

Six substantive changes. Three are reversals of M2F recommendations.

| # | Change | Why |
|---|---|---|
| **C1** | **S6 is withdrawn.** No `evidence_capture` column on `research_runs`. `EMPTY` / `CHECKPOINT_MISSING` / `READ_FAILURE` stay migration-ledger concepts, with a defined read contract (§9). | M2F rejected ledger-only on the grounds that "V2 will hold runs the ledger never saw", creating a fourth ambiguous state. **That reasoning was wrong.** Absence of a ledger row is not ambiguous: it means the run was never considered by the migration, i.e. it is V2-native, and a V2-native run writes evidence in the same transaction as the run — so zero rows is a measured zero. No product requirement for a domain column has been demonstrated, and nothing reads V2 yet. |
| **C2** | **S4's `ck_contra_pair` disjunction is replaced.** `DETECTED` now requires **both source references**, with evidence references as an optional refinement — not an alternative. | M2F's `(both evidence) OR (both sources)` still permitted a migrated pair to assert evidence-level precision. V1's detector never observed that level (§7). The disjunction made the imprecision *storable*; requiring source-level makes it *impossible to overstate*. |
| **C3** | **S1 is not approvable alone, and the hazard is wider than the database.** The review-target change, the artifact-authorization constraint, and a **bundle-serialization** invariant M2F missed are one unit (§4, §5). | `verify_bundle._check_approval_chain` filters on `action == "approved"`, so it rejects `plan_approved` today — but only because V1 happens to use a distinct string. Nothing tests that a V2 PLAN approval must not serialize as `"approved"`. Relaxing `revision_id` without pinning that would let a plan approval authorize an artifact *through the bundle*, where no database constraint reaches. |
| **C4** | Bundle validation becomes **three independent gates**, not one verdict (§10). | The M2E-2 corpus was `BUNDLE_EQUIVALENT` on 124 runs and would have failed `verify_bundle` on all of them. |
| **C5** | `NOT_COMPARABLE` becomes **two reason *sets***, with `V2_RUN_ABSENT` as a first-class V2-axis code (§10.1). | 12 of 48 cases reported a V1 property while the material fact was that the migration refused the run. |
| **C6** | The **Historical Non-Fabrication Principle** is promoted from a working rule to a stated project-level principle, and every S/M change is evaluated against it (§11). | It was implicit in M2E-1's four refusals and applied inconsistently in M2F's own proposals. |

M2F conclusions **retained unchanged**: gap 1 is not a V2 gap; gap 2 is larger than reported;
gap 4 splits into a recoverable and an unrecoverable sub-case; gap 5 is a classifier defect;
gap 6 is real and time-sensitive. M2E-2's mechanism results (17/17 plants, 200/200 accounted,
resumable, idempotent, both dialects) are untouched.

---

## 3. Revised domain invariants

Fourteen. Each names the layer that enforces it. "Application" means a service-layer rule with a
test; "Verifier" means `research_engine/verify_bundle.py` or the migration's own validation.

| # | Invariant | Enforced by |
|---|---|---|
| **I1** | A `Review` at the PLAN gate has a `ResearchPlan` version as its subject and no `Revision`. | Database (`ck_review_plan`, `ck_review_report`) |
| **I2** | A `Review` at the REPORT gate has a `Revision` as its subject. | Database (`ck_review_report`) |
| **I3** | A `ResearchArtifact` may reference only an **APPROVED REPORT** review. | Database (composite FK + `ck_artifact_gate`) |
| **I4** | A PLAN approval never serializes into a bundle as `action = "approved"`. | Application + Verifier |
| **I5** | A `Source` exists iff V1 (or V2) recorded a non-empty URL for it, within its run. | Application (migration) |
| **I6** | `sources.citation_index` is NULL iff the source was never assigned a citation number. It is never generated. | Database (nullable + partial unique) + Application |
| **I7** | A contradiction is a conflict between **two attributed quotations**, each anchored to a `Source`. | Database (`ck_contra_pair`) |
| **I8** | A contradiction's `evidence_*_id` is a *refinement*, present only when the quotation matched exactly one evidence row. | Application |
| **I9** | Reviews within a run are **totally ordered** by an explicit `sequence`, never by insertion order or timestamp. | Database (`UNIQUE (run_id, sequence)`) + Application |
| **I10** | Zero evidence rows on a **migrated** run means "unknown" unless the ledger says otherwise. No read path may render it as a measured zero without consulting the ledger. | Application + test |
| **I11** | Absence of a `migration_ledger` row means the run is V2-native; its evidence rows are the complete record. | Application (read contract) |
| **I12** | Every column of every migrated row is grounded: traceable to a V1 expression, a declared constant, or NULL. | Verifier (Gate C) |
| **I13** | A V1 state V2 cannot represent is recorded as an incompatibility; the V1 data is left untouched. | Application (migration refusals) |
| **I14** | Fidelity, validity and non-fabrication are reported separately and never combined into one verdict. | Verifier (three gates) |

---

## 4. Review target model

### 4.1 The two gates are different relationships

| | PLAN gate | REPORT gate |
|---|---|---|
| V1 writer | `submit_plan`, at status `AWAITING_PLAN` | the report gate, at `AWAITING_APPROVAL` |
| V1 action | `plan_approved` | `approved`, `rework_requested` |
| V2 subject | `ResearchPlan` version | `Revision` |
| V2 columns | `plan_version_id` NOT NULL, `revision_id` **NULL** | `revision_id` NOT NULL, `plan_version_id` NULL |
| `reviewed_hash` | **opaque** — nothing in V1 has ever verified the plan hash (M2A §8) | hashes `Revision.report_markdown`; checked by the verifier |
| Authorizes an artifact | **never** | only when `decision = 'APPROVED'` |

`ck_review_plan` — `(gate = 'PLAN') = (plan_version_id IS NOT NULL)` — already exists and is
already correct. The only defect is the unexamined `revision_id NOT NULL`, which makes I1
unstorable.

### 4.2 Why `plan_approved` with no plan is still a refusal

A `plan_approved` audit row on a session whose `plan_json` and `outline_json` are both NULL has
nothing to point `plan_version_id` at. The migration must not create a plan version to hold it
(that would be fabrication, §11). It stays `INCONSISTENT_V1` with a distinct category —
`PLAN_REVIEW_WITHOUT_PLAN` — separate from `REVIEW_WITHOUT_REVISION`, so the ledger does not
merge two different impossibilities.

### 4.3 Why a REPORT review with no report stays a refusal

`approved` or `rework_requested` on a session with no report is not merely unrepresentable —
it is **incoherent**: the V1 gate that writes those rows requires a draft to exist. Unlike the
plan case, relaxing a constraint would not make it truthful. Unchanged from M2F.

---

## 5. Artifact authorization invariant (I3, I4)

The strongest property in the V2 schema is that approval is a *database fact*: an artifact
carries a denormalised `review_decision` constrained to `'APPROVED'` and a composite FK to
`reviews(id, decision)`, so an artifact referencing a rework request is unrepresentable.

**Making `revision_id` nullable punches a hole in exactly that property**, because the FK
constrains the decision and not the gate. Three layers must therefore move together.

### 5.1 Database

```
reviews          ADD    UNIQUE (id, decision, gate)          -- the new FK target
research_artifacts
                 ADD    review_gate            (mirrors reviews.gate)
                 ALTER  fk_artifact_review  →  reviews(id, decision, gate)
                 ADD    CHECK ck_artifact_gate  review_gate = 'REPORT'
```

Same technique as `review_decision`, applied to the second axis. The old two-column unique
constraint `uq_review_decision` is retained or replaced depending on whether anything else
targets it — it is currently referenced only by this FK.

### 5.2 Application

Artifact assembly reads approvals through a single accessor that filters
`gate = 'REPORT' AND decision = 'APPROVED'`. Not two call sites with the same predicate —
this repository's recurring failure is the second copy.

### 5.3 Verifier — the layer M2F missed

`verify_bundle._check_approval_chain` selects `[a for a in approval_chain if a.action == "approved"]`
and requires at least one whose `draft_hash` equals `report_hash`. A `plan_approved` entry is
present in the chain but is **not** counted as an approval — correct behaviour, arrived at
by string inequality rather than by design.

The exposure is on the V2 side. `bundle_equivalence.REVIEW_TO_V1_ACTION` maps
`("PLAN", "APPROVED") → "plan_approved"`, which is right, and **nothing tests it**. If a future
assembler simplified that map to emit `"approved"` for any APPROVED review, a plan approval
would satisfy the verifier's load-bearing check — in a file the database cannot reach.

**I4 must therefore be pinned by a test and a planted failure**: map a PLAN approval to
`"approved"` and require the bundle to fail. Two secondary observations, recorded not fixed:

* `ApprovalRecord.action`'s field description says `'"approved" or "rework_requested"'` and
  omits `plan_approved`, which V1 has emitted since the design gate shipped. The bundle format
  under-documents its own vocabulary.
* `_check_approval_chain`'s empty-hash check covers *all* entries, so a plan review with an
  empty `reviewed_hash` fails the whole chain. Consistent with `ck_review_hash`; worth knowing
  before `reviewed_hash` is ever relaxed for the opaque plan-gate case.

---

## 6. Source recovery invariant (I5, I6)

### 6.1 Where source identity comes from

Source identity within a run is `_norm_url(url)` — lowercased, trailing slash stripped. That is
the key `_number_sources` uses for de-duplication, the key `validate_pairs` checks against, and
the key the migration's `_det("source", run_id, normalized_url)` derives from. One definition,
three consumers.

### 6.2 The two provenance classes, and why neither needs a column

| Class | V1 authority | `citation_index` |
|---|---|---|
| **From the snapshot** | `sessions.sources[i]`, written by `synthesizer_node` → `_number_sources` (single writer, grep-confirmed across `app/`, `desktop/`, `research_engine/`) | the recorded `index` |
| **From evidence** | `state["evidence"][j].source_url` / `.source_title`, written by `executor_node`; `EvidenceChunk.source_url` is a **required** field | **NULL** |

A source recovered from evidence and the same URL present in the snapshot **collapse to one
row by construction**, because `_det` keys on the normalized URL. That is correct — they are the
same source — and it is the one place recovery could silently duplicate, so it needs a test.

No provenance column is added. `citation_index IS NULL` already carries the distinction, and it
carries it as a *domain* fact rather than a migration one: "retrieved but never cited" is a
state a V2-native run can reach too, when a source is fetched and the synthesizer does not cite
it. This is the same test C1 applies to S6, and unlike S6 it passes.

### 6.3 The refusal that remains

Evidence whose `source_url` is the empty string has no identity anywhere in V1 — `_number_sources`
skips it, `group_snippets_by_source` skips it, and `agent_logs` payloads carry counts rather
than evidence (checked). A `Source` for it would be an invention. The run stays non-migratable,
category `EVIDENCE_SOURCE_UNRESOLVED`, with the count of offending items in the ledger detail.

*Deferred question, not decided here:* whether such a run should instead migrate with the
nameless evidence items dropped and the incompleteness recorded. That requires a way to say
"this run's evidence is incomplete", which C1 has just declined to add to the domain. It is
listed as open decision O4 (§17).

---

## 7. Contradiction semantics (I7, I8)

### 7.1 What V1 actually asserts

The detector is shown `group_snippets_by_source(evidence)` — a `{source_url: [snippets]}` map,
capped at 12 sources × 4 snippets × 500 characters. It never sees an evidence row, a claim, or
a report sentence. It returns seven fields, and `validate_pairs` drops any pair whose source URL
was not in the input.

So the assertion V1 makes is precisely:

> *this quoted text, attributed to source A, cannot both be true with that quoted text,
> attributed to source B, for the stated reason.*

### 7.2 Choosing the V2 concept

| Candidate | Verdict |
|---|---|
| **Source-level** | Too coarse alone — discards which quotation was meant, and a source can hold several |
| **Evidence-level** (V2 today) | **Overstates.** Implies the detector identified specific evidence rows. It did not |
| **Claim-level** | **Wrong entity.** V2 `claims` are report sentences derived from prose; the detector's `claim_a/b` are its own restatements of source text and are not report claims. Reusing the word would conflate two unrelated things |
| **Attributed quotation** | **Correct.** A quotation, anchored to a source, optionally resolvable to the evidence row that carries it |

**I7: a contradiction is a detected conflict between two attributed quotations.** The source
anchor is what V1 guarantees; the evidence anchor is a refinement that may or may not resolve.

### 7.3 Authoritative vs derived fields

| V1 field | V2 | Status |
|---|---|---|
| `source_a` / `source_b` | `source_a_id` / `source_b_id` | **Authoritative.** Validated against the evidence's own URLs; a hallucinated or injected URL was already dropped |
| `snippet_a` / `snippet_b` | `quote_a` / `quote_b` | **Authoritative** as *the text the detector quoted*. Not authoritative as *the evidence row it came from* |
| `claim_a` / `claim_b` | `summary_a` / `summary_b` | **Authoritative as the detector's restatement**, which is what it is. Not a fact about the world, and not a V2 `Claim` |
| `nature` | `nature` | **Authoritative.** Currently has no V2 column at all; survives only as prose inside `revisions.report_markdown`, where the deterministic block renderer wrote it |
| — | `evidence_a_id` / `evidence_b_id` | **Derived, optional.** Set only by an exact, unique match of `quote_*` against an evidence snippet within that source |
| — | `dimension` | Not recorded by V1; `UNCLASSIFIED` |
| — | `detection_state` | Derived from whether pairs exist and whether the detector ran |

### 7.4 The revised constraint

```
CHECK (detection_state = 'DETECTED')
      = (source_a_id IS NOT NULL AND source_b_id IS NOT NULL)

CHECK (evidence_a_id IS NULL) = (evidence_b_id IS NULL)     -- a half-resolved pair is not a pair
CHECK  source_a_id   IS NULL OR source_a_id   <> source_b_id
CHECK  evidence_a_id IS NULL OR evidence_a_id <> evidence_b_id
```

This replaces M2F's disjunction (C2). A migrated pair is `DETECTED` and truthful the moment its
two sources resolve — which for a validated V1 pair is guaranteed wherever the source snapshot
survives — and it can never claim evidence-level precision it does not have.

**No fallback.** If `quote_a` matches no evidence snippet, or matches more than one,
`evidence_a_id` stays NULL. "The first evidence row from that source" would assert a link V1
never made.

### 7.5 Consequence for the plan of record

M2C §13 planned `detection_state = 'DETECTED'` where pairs exist. The M2E-1 engine writes
`NOT_RUN` because `ck_contra_pair` made the plan unstorable. **The plan was right, the schema
was wrong, and the code was correct to refuse.** §7.4 is what lets the plan of record be
implemented as written.

---

## 8. Review ordering (I9)

### 8.1 Is order a domain fact? Yes.

`approved` then `rework_requested` and `rework_requested` then `approved` are different
histories of the same run — one is a report that was approved and later challenged, the other a
report that was reworked and then accepted. Nothing else in V2 records which happened.

It is also already treated as a fact in shipped code: **both** bundle assemblers order the
approval chain by `AuditLog.id.asc()` (`app/api/v1/research.py`, `desktop/sidecar.py`), and
`approval_chain` is a JSON list, so the order is serialized into every bundle and covered by
`bundle_hash`.

`verify_bundle._check_approval_chain` does **not** depend on order — it uses `any()`. So order
is a domain fact that no current check protects, which is exactly how it would be lost quietly.

### 8.2 The invariant

**I9: reviews within a run form a total order given by an explicit `sequence`, unique per run.**
Not `created_at` (V1 gives no distinctness guarantee, and two gates can share a timestamp), and
not insertion order (V2 review ids are uuid5, so id order is arbitrary).

`reviews` also gains `run_id`, because today a run's approval chain cannot even be *collected*
without joining through two different parents (`revisions` for REPORT, `research_plans` for
PLAN) — and after I1 a PLAN review has no `revision_id` at all, so the existing single-parent
read would silently omit every plan approval.

### 8.3 Migration source

`sequence` = the rank of `audit_log.id` within the session, 1-based. `audit_log.id` is BIGSERIAL
and monotonic; this is a **transformation of a V1 fact**, not a generated ordering. `run_id` =
the session id.

**Time-sensitivity.** The ordinal exists only while `audit_log` does. Any later milestone that
retires the V1 tables before this lands destroys the only record of decision order. This is the
one item in M2F with a deadline attached to it.

---

## 9. Checkpoint / migration-state separation (I10, I11)

### 9.1 Decision: these stay migration concepts. S6 is withdrawn.

`EMPTY`, `CHECKPOINT_MISSING` and `READ_FAILURE` describe **what the migration could see**, not
what the research produced. Nothing in the product reads V2 yet, so no product requirement for a
domain column has been demonstrated — and the test for adding one is a demonstrated requirement,
not an anticipated one.

M2F's argument for a column was that the ledger cannot cover V2-native runs. That argument does
not hold:

### 9.2 The read contract

```
evidence completeness for run R:

    L := migration_ledger row WHERE session_id = R.id

    L absent                                   → R is V2-native.
                                                 Evidence rows ARE the complete record.
                                                 Zero rows is a MEASURED zero.
    L.evidence_outcome = 'COPIED'              → complete
    L.evidence_outcome = 'NONE_PRESENT'        → measured zero
    L.evidence_outcome = 'CHECKPOINT_MISSING'  → UNKNOWN — never render as zero
    L.evidence_outcome = 'CHECKPOINT_UNREADABLE' → UNKNOWN — never render as zero
```

The join is unambiguous because `migration_ledger.session_id` is the V1 session id and a
V2-native run's id is a fresh UUID that can never collide with one. "No ledger row" therefore
means "not migrated", which means the transactional write path applied.

### 9.3 What this obliges

* **I10** — no V2 read path may present an evidence count, a citation-resolution figure, or an
  "N sources" summary for a migrated run without consulting the ledger. This is an application
  invariant with a test, and it becomes load-bearing the moment M2G adds dual-read. Until then
  nothing reads V2, so nothing can violate it — which is precisely why it is cheap to state now.
* **Operational:** `migration_ledger` must not be dropped after the migration (already M2C §12).
  With S6 withdrawn it is the *only* record of the distinction, so the retention rule is now
  load-bearing rather than merely good practice.
* **Re-open, don't forget:** if M2G finds the join impractical on a hot read path, S6 returns
  with a demonstrated requirement attached. Recorded as open decision O5.

---

## 10. Three-dimensional migration validation (I14)

### Gate A — Representational fidelity

*Does V2 say what V1 said?* Two reason **sets**, evaluated independently; a run may carry
several reasons on each axis.

```
V1 axis   V1_EXPORTABLE
          V1_STATUS_NOT_COMPLETED       V1's own export route refuses non-COMPLETED runs
          V1_NO_REPORT
          V1_CHECKPOINT_MISSING
          V1_CHECKPOINT_UNREADABLE

V2 axis   V2_PRESENT
          V2_RUN_ABSENT                 ledger says INCONSISTENT_V1 or FAILED
          V2_NO_REVISION
          V2_EVIDENCE_UNAVAILABLE       from the ledger read contract (§9.2)

verdict   EQUIVALENT | MISMATCH(limitation)   iff V1 axis = {V1_EXPORTABLE}
                                              and V2 axis = {V2_PRESENT}
          NOT_COMPARABLE(v1_reasons, v2_reasons)   otherwise
```

No mutually-exclusive enum, and **no generic bucket**: a run with no applicable code is a defect
in the taxonomy, not a run to be filed under "other". A `MISMATCH` whose differing field set is
not in `KNOWN_LOSSY` remains `UNCLASSIFIED` and fails the dry run — retained from M2E-2 unchanged.

### Gate B — Internal bundle validity

*Does the bundle pass `verify_bundle` on its own terms?* Run the shipped verifier against the
**V2 bundle**, and separately against the **V1 bundle**, recording both. Four outcomes, all of
which mean something different:

| V1 bundle | V2 bundle | Reading |
|---|---|---|
| VALID | VALID | the migration preserved a verifiable artifact |
| VALID | INVALID | **a migration defect** — V2 broke something that verified |
| INVALID | INVALID | V1 was already unverifiable; V2 inherited it. Not a migration defect, and must not be reported as one |
| INVALID | VALID | V2 "repaired" a V1 defect — **suspicious**, and a candidate fabrication (Gate C) |

The M2E-2 corpus sits in row 3 on every run, because its `draft_hash` values are placeholders
rather than `sha256(report)`. Fixing the corpus is a precondition (§16), and until it is fixed
Gate B cannot distinguish rows 1–3.

### Gate C — Historical non-fabrication

*Is every migrated fact grounded?* Mechanised as a **provenance map**: every column of every V2
table the migration writes is declared as exactly one of

* **`FROM(expr)`** — a V1 expression (`sessions.prompt`, `evidence[i].source_url`, `rank of audit_log.id`, …)
* **`CONST(value, reason)`** — a declared constant with its justification (`provenance_state='UNCHECKED'` because V1 recorded no per-item attestation; `origin='UNKNOWN'` because V1 overwrote the proposal; `retrieval_status='UNKNOWN'`)
* **`DERIVED(f, inputs)`** — a pure function of V1 data (`report_hash = sha256(report)`, `sequence`, `citation_index` from the snapshot)
* **`NULL(reason)`** — deliberately absent (`lineage_id`, `cancelled_at`, `attested_against`)

A column in none of those four classes fails Gate C. The test is structural: enumerate the
columns each `insert()` supplies, and require every one to appear in the map. Adding a column to
the migration without declaring its provenance then fails the build — which is the only durable
way to keep this principle from decaying into a slogan.

### Independence

The three gates are reported as three fields. `BUNDLE_EQUIVALENT` never implies validity;
`VALID` never implies fidelity; both together never imply grounding. **I14.**

---

## 11. Historical non-fabrication principle

> **Migration may transform, normalize, or recover information demonstrably present in V1, but
> must never manufacture historical facts to satisfy V2 constraints. When V2 cannot represent a
> valid V1 state, migration must record the incompatibility and preserve the original V1 data.**

This is a project-level principle, not an M2F rule. It is the generalisation of M2E-1's four
refusals and of the P0 rule in AGENTS.md: a fabricated historical fact is a false measurement
with a longer half-life, because nothing downstream can tell it apart from a real one.

**Three operations it permits**, each requiring a named V1 location:

* **transform** — rename, widen, re-encode (`AWAITING_APPROVAL` → `AWAITING_REVIEW`)
* **normalize** — a pure function of V1 data (`sha256(report)`, `_norm_url`)
* **recover** — read a fact from a different V1 location than the obvious one
  (`evidence[i].source_url` when `sessions.sources` is absent)

**Two it forbids:** inventing a value V1 never held, and *dropping* a valid V1 fact to make the
insert succeed. Both are failures; the second is the quieter one.

### Evaluation of every proposed change

| Change | Verdict | Grounding |
|---|---|---|
| **S1** `revision_id` nullable | ✅ Compliant | Records an absence V1 genuinely has. Removes a constraint; adds no value |
| **S2** artifact gate constraint | ✅ Compliant | Tightening only. Cannot introduce a fact |
| **S3** `citation_index` nullable | ✅ Compliant | The index is *not* generated; NULL states that V1 never assigned one |
| **S4** contradiction columns (as revised, §7.4) | ✅ Compliant **conditionally** | `source_*_id`, `quote_*`, `nature` are all V1-recorded. Compliance depends on the no-fallback rule: an unresolved `evidence_*_id` must stay NULL |
| **S5** `reviews.run_id` + `sequence` | ✅ Compliant | `sequence` is the rank of `audit_log.id` — a transformation. `run_id` is derivable from either parent |
| **S6** `evidence_capture` on `research_runs` | ⚪ **Withdrawn** (C1) | Not a fabrication — the values are true — but it relocates a migration fact into the research domain with no demonstrated reader |
| **M1** contradiction mapping | ✅ Compliant | Exact, unique quote match only. No "first evidence from that source" |
| **M2** plan reviews migrate against the plan | ✅ Compliant | No Revision fabricated. `plan_approved` with no plan remains a refusal |
| **M3** source recovery from evidence | ✅ Compliant | `EvidenceChunk.source_url` is a required V1 field written by the executor. Empty URL still refused |
| **M4** review sequence | ✅ Compliant | See S5 |
| **M5** evidence capture state | ⚪ Withdrawn with S6 | The distinction remains, in the ledger |
| **M6** two-axis not-comparable | ✅ Compliant | Reporting change only |

One conditional (S4) and one withdrawal (S6). Nothing proposed manufactures a historical fact.

---

## 12. Revised schema implications

Net effect on the isolated proposal. **Still not applied.**

| Item | Status after this amendment |
|---|---|
| **S1** `reviews.revision_id` nullable + `ck_review_report` | Retained. **Never ships alone** |
| **S2** artifact `review_gate` + composite FK + `ck_artifact_gate` | Retained, and **promoted to ship-with-S1** |
| **S3** `sources.citation_index` nullable + partial unique index | Retained unchanged. Both `postgresql_where` **and** `sqlite_where` required |
| **S4** contradictions: `source_a_id`, `source_b_id`, `quote_a`, `quote_b`, `nature`; revised CHECKs (§7.4) | **Revised** — source-level requirement replaces the disjunction |
| **S5** `reviews.run_id` + `sequence` + `UNIQUE (run_id, sequence)` | Retained. Rationale strengthened: without `run_id`, the existing read omits plan reviews entirely once I1 lands |
| **S6** `research_runs.evidence_capture` | **Withdrawn** |

Five schema items, not six. Every one is portable across Postgres and SQLite, which the M2D
parity suite must re-prove — partial unique indexes in particular, where omitting one dialect
keyword silently makes the index total.

---

## 13. Revised migration implications

| Item | Status |
|---|---|
| **M1** contradictions map all seven fields; `DETECTED` on source resolution; evidence refinement optional and exact-match-only | Revised per §7 |
| **M2** `plan_approved` → PLAN review against the plan; `PLAN_REVIEW_WITHOUT_PLAN` as a distinct refusal category | Revised per §4.2 |
| **M3** recover `Source` from `evidence.source_url`; empty URL still refused; deterministic id collapse with snapshot sources | Retained, with the collapse pinned by a test |
| **M4** `sequence` from `rank(audit_log.id)`; `run_id` from the session | Retained |
| **M5** evidence capture state | **Withdrawn** with S6 |
| **M6** two-axis reason sets including `V2_RUN_ABSENT` | Retained per §10 |
| **M7** *(new)* provenance map for Gate C | Added |
| **M8** *(new)* dry-run corpus uses `draft_hash = sha256(report)` | Added |

Safety properties that must be **re-proven, not assumed**, after any of these:

* one transaction per run — M3 and M1 add inserts inside the same transaction
* deterministic identity — the P3 two-database test must extend to recovered sources and plan-gate reviews
* narrowed refusals — every plant for a narrowed refusal must be re-verified to fire for the *remaining* case and pass for the newly-migratable one
* ledger accounting — `INCONSISTENT_V1` drops from 12/200 to 0/200 in the corpus, and the validation report must state that part of the drop is "the schema stopped forbidding data V1 always had", not "the migration got better at recovering"

---

## 14. Revised bundle-equivalence implications

1. **Three verdict fields, not one.** Every run reports `(fidelity, validity_v1, validity_v2, grounding)`.
2. **`SOURCE_SNIPPETS_NOT_STORED` → `V1_SOURCE_SNAPSHOT_DIVERGED_FROM_EVIDENCE`.** The V1 bundle
   for such a run fails its own `claim_evidence_linkage` check (measured in M2F §9.1), so Gate B
   on the V1 side explains the Gate A mismatch. Reporting them together is what stops it being
   read as a V2 loss.
3. **`KNOWN_LOSSY` shrinks to one entry** once M1 lands. The unclassified-mismatch failure rule
   is unchanged.
4. **The V2 bundle must emit the full contradiction record** — `snippet_a/b`, `source_a/b`,
   `nature` — or M1 will store the fields and the comparison will still mismatch.
5. **I4 becomes a bundle-level test:** a PLAN approval must serialize as `plan_approved`, never
   `approved`. Planted failure required.
6. **Gate B on the V1 side is diagnostic, not a pass/fail for the migration.** A V1 bundle that
   never verified is a V1 fact; the migration is judged on rows 1–2 of the §10 table.

---

## 15. Implementation sequencing

Five steps. Each is independently revertible, and each ends with the dry run green on both
dialects, every existing plant firing, and the new plants firing.

| Step | Contents | Gate it moves | Why here |
|---|---|---|---|
| **F1** | M6, M7, M8, the §14.2 rename, three-field reporting | A + B + C | **No schema change.** Fix the measurement before changing what is measured. Gate C's provenance map must exist *before* new columns are added, or the first thing it fails to cover is the change that motivated it |
| **F2** | S1 + S2 + M2 + the I4 test | A | Highest value, and the one with a security-shaped consequence. Ships as one migration so the artifact hole never exists, not even between commits |
| **F3** | S5 + M4 | — | Moved earlier than M2F had it: the ordinal exists only while `audit_log` does (§8.3), and after F2 the plan reviews it must order already exist |
| **F4** | S4 + M1 | A | Largest field-mapping change; no effect on refusals, so it cannot destabilise F2's results |
| **F5** | S3 + M3 | A | Last because it changes which runs migrate at all, and should be measured against a baseline the previous four steps have already stabilised |

M2F sequenced S3/M3 in F3 and S5 in F4. **Reversed here** for the two reasons above.

---

## 16. Acceptance criteria

Per step, and for the amendment as a whole. Each is a test, not a review opinion.

**Global**

* G1 — every invariant I1–I14 has a named test; I3, I4, I7, I9, I12 additionally have a planted failure that fires
* G2 — the dry run reports fidelity, validity and grounding as three fields; no code path combines them
* G3 — Gate C's provenance map covers 100% of columns supplied by every `insert()` in `migration/engine.py`; an undeclared column fails
* G4 — the dry-run corpus sets `draft_hash = sha256(report)`, and every `BUNDLE_EQUIVALENT` run is `VALID` on **both** sides
* G5 — `KNOWN_LOSSY` has not grown; any `UNCLASSIFIED` mismatch still fails the run
* G6 — production remains at `0015_citation_resolution_rate`, 11 sessions, 0 V2 tables, verified before and after every step

**Per step**

| Step | Must hold |
|---|---|
| F1 | 48 `NOT_COMPARABLE` cases decompose into reason sets with no generic bucket; 12 report `V2_RUN_ABSENT`; the three unreachable codes are either reachable or deleted |
| F2 | an artifact referencing a PLAN approval is rejected **by the database**; a PLAN approval serialized as `"approved"` is rejected **by the verifier**; the 4 `REVIEW_WITHOUT_REVISION` runs migrate; `PLAN_REVIEW_WITHOUT_PLAN` is a distinct refusal that still fires |
| F3 | review order round-trips through the bundle; two reviews with an identical `created_at` still order deterministically; a run's chain includes its PLAN reviews |
| F4 | the 12 contradiction mismatches become equivalent; a pair whose quote matches two evidence rows leaves `evidence_*_id` NULL; a `DETECTED` row without both sources is unstorable |
| F5 | the 8 `EVIDENCE_SOURCE_UNRESOLVED` runs migrate with `citation_index IS NULL`; an empty `source_url` still refuses; a recovered source and a snapshot source with the same URL are **one** row |

---

## 17. Decisions that remain open

M2F's decisions 1–4 are answered by this amendment (§4, §5, §6). These remain.

| # | Open decision | Recommendation |
|---|---|---|
| **O1** | Is "attributed quotation" the right contradiction concept, and should `summary_a/b` be renamed to say "the detector's restatement"? | Adopt the concept (§7.2). Rename is cosmetic — defer |
| **O2** | Should `reviews.reviewed_hash` stay NOT NULL for the PLAN gate, given nothing has ever verified a plan hash? | Keep NOT NULL. It is opaque, not absent, and relaxing it would trip the verifier's empty-hash check (§5.3) |
| **O3** | Is review order a domain fact worth a column? | **Yes** (§8). Confirmed by both hosts already ordering by `audit_log.id`. Needs sign-off because it adds a NOT NULL column to `reviews` |
| **O4** | Should a run with empty-`source_url` evidence migrate with those items dropped and the incompleteness recorded, rather than refusing? | **No, for now.** With S6 withdrawn there is no way to record the incompleteness in the domain. Revisit only with a demonstrated reader |
| **O5** | Does M2G's dual-read make the ledger join impractical, re-opening S6? | Unknown until dual-read exists. Recorded so the withdrawal is revisitable rather than forgotten |
| **O6** | Should Gate B's V1-side result gate the migration, or only annotate it? | **Annotate.** A V1 bundle that never verified is a V1 fact; blocking on it would make the migration hostage to historical defects it did not cause |
| **O7** | Does `ApprovalRecord.action`'s description need correcting to include `plan_approved`? | Yes, but it is a bundle-format documentation fix outside M2F's scope |

---

## 18. Scope statement

**Not authorised by this document:** implementing S1–S5 or M1–M8; modifying the M2D schema;
changing `Review.revision_id`; migrating production; running against a restored production copy;
switching reads or writes to V2; dual-read; dual-write; changes to the frontend or LangGraph;
removing any V1 table or column; starting M2G.

**Changed by this document:** nothing outside `internal/`.
