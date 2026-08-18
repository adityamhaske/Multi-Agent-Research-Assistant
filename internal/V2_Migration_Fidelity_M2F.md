# M2F — Migration Fidelity & Domain Gap Resolution

**Status:** proposal and review. **No code changed. No schema changed. Production untouched.**
**Input:** the seven fidelity gaps M2E-2 surfaced and M2E-3 recorded.
**Output:** for each gap — the authoritative V1 fact, whether V2 holds it, whether the loss
was intentional, and what (if anything) must change in the schema, the migration, or the
bundle-equivalence rules.
**Precondition it unblocks:** the restored-production dry run, which is **not** authorised by
this document.

M2E-2's conclusions stand and are not re-litigated here: 17/17 planted failures fire, 200/200
runs accounted, resumable, idempotent, Postgres and SQLite agree, production untouched.

---

## 1. Executive summary

Seven gaps were investigated against V1's own code. They do not have one shape, and treating
them as one list of "things to store" would be the wrong conclusion:

| # | Gap | Verdict |
|---|---|---|
| 1 | `SOURCE_SNIPPETS_NOT_STORED` | **Not a V2 gap.** The field is derived/rendered. The 16 mismatches are a *V1* internal inconsistency, and the M2E-3 framing of this as a V2 schema limitation was wrong. |
| 2 | `CONTRADICTION_PAIR_NOT_STORED` | **Accidental loss, and larger than reported.** V1 stores seven fields per pair; the migration maps two. `nature` has no V2 column at all. The relationship *is* a domain fact and is resolvable from V1 data. |
| 3 | `REVIEW_WITHOUT_REVISION` | **Accidental over-constraint.** V2 already names the correct target (`plan_version_id`); it merely also demands a revision. Fixable without inventing anything — but it opens a hole in the artifact FK chain that must be closed in the same change. |
| 4 | `EVIDENCE_SOURCE_UNRESOLVED` | **Partly recoverable.** The source URL and title are recorded on the evidence chunk itself — a V1 fact in another table, not an invention. What cannot be recovered is `citation_index`. Splits into a recoverable and an unrecoverable sub-case. |
| 5 | 48 `NOT_COMPARABLE` | **Classifier defect.** The reasons are mutually exclusive only because the first matching check wins, which hides a migration failure behind a V1 property in 12 of 48 cases. Three reason codes are unreachable dead paths. |
| 6 | Review ordering | **Accidental.** Worse than reported: `reviews` has no `run_id`, so a run's approval chain cannot be *collected* without joining two different parents, let alone ordered. |
| 7 | `EMPTY` vs `CHECKPOINT_MISSING` vs `READ_FAILURE` | **Intentional at M2B, wrong in hindsight.** V2 has no way to say "evidence unavailable", so migrated runs display an unmeasured zero — the failure mode this product exists to prevent. |

Two of the seven need **no** schema change (1, 5). Four need a schema change that adds a
column or relaxes a constraint without inventing data (2, 3, 4, 6). One needs a new
vocabulary column (7).

A separate finding, not on the original list, is recorded in §9.4: **the M2E-2 corpus's
bundles do not pass `verify_bundle`**, because their `draft_hash` values are placeholders
rather than real report hashes. Bundle *equivalence* is unaffected — two representations were
compared and they matched — but "equivalent" was never "verifiable", and the restored-production
dry run must check both.

Nothing here fabricates a historical fact. Where V1 did not record something (§10), the
proposal is to record its absence, not to fill it in.

---

## 2. Every known fidelity gap

Counts are from `m2e_dryrun/dryrun-postgres-200.json` (identical on SQLite).

| # | Gap | Corpus incidence | Surfaces as |
|---|---|---|---|
| 1 | Source snippet list not stored | 16 / 200 | `BUNDLE_MISMATCH` on `sources` |
| 2 | Contradiction pair not stored | 12 / 200 | `BUNDLE_MISMATCH` on `contradictions` |
| 3 | Review with no revision | 4 / 200 | `INCONSISTENT_V1` — run not migrated |
| 4 | Evidence with no resolvable source | 8 / 200 | `INCONSISTENT_V1` — run not migrated |
| 5 | Not-comparable taxonomy | 48 / 200 | `NOT_COMPARABLE` with a masked reason |
| 6 | No review ordinal | 0 observed | latent; the corpus gives every review a distinct timestamp |
| 7 | Evidence availability not representable | 32 / 200 | invisible in V2; only `migration_ledger` knows |

---

## 3. V1 authority — where each fact actually lives

The question this section answers for every gap: *what did V1 write, and which table or field
is the authority for it?*

| Fact | V1 authority | Written by | Notes |
|---|---|---|---|
| an evidence snippet | checkpoint `state["evidence"][i].snippet` | `executor_node` → `submit_evidence` | verbatim, ≤500 chars; blanked in place by `verify_evidence_snippets` **before** it is stored (real mode only) |
| the source of an evidence item | checkpoint `state["evidence"][i].source_url` / `.source_title` | `executor_node` | `EvidenceChunk.source_url` is a **required** field; it may be the empty string |
| the numbered citation list | `sessions.sources` | `synthesizer_node` → `_number_sources` | one writer, confirmed by grep across `app/`, `desktop/`, `research_engine/` |
| a source's snippet / snippets | `sessions.sources[i].snippet` / `.snippets` | the same `_number_sources` call | **computed from evidence**, stripped and de-duplicated |
| the citation index `[n]` | `sessions.sources[i].index` | the same call | first-appearance order over evidence |
| a contradiction | checkpoint `state["contradictions"][j]` | `contradiction_detector_node` → `validate_pairs` | seven fields: `claim_a/b`, `snippet_a/b`, `source_a/b`, `nature` |
| the granularity of a contradiction | **source-level** | `group_snippets_by_source` | the detector is shown `{url: [snippets]}`, capped at 12 sources × 4 snippets; it never sees an evidence row |
| a human decision | `audit_log` row | `submit_plan`, the report gate | three actions only: `approved`, `rework_requested`, `plan_approved` |
| the order of decisions | `audit_log.id` (BIGSERIAL) | the database | monotonic; `created_at` is not guaranteed distinct |
| the trace | `agent_logs` | both hosts' sinks | payloads carry counts and messages, **not** evidence — so `agent_logs` is not a recovery route for §4 |

---

## 4. V2 authority — what the schema can hold today

| Fact | V2 home | Holds it? |
|---|---|---|
| evidence snippet | `evidence.snippet` + `content_hash` | ✅ verbatim, empty included |
| evidence → source | `evidence.source_id` → `sources(id, run_id)` | ✅ but **NOT NULL** |
| citation index | `sources.citation_index` | ⚠️ **NOT NULL**, `>= 1`, unique per run |
| source snippet list | — | ❌ by design; derivable from `evidence` |
| contradiction sides | `contradictions.summary_a/summary_b` | ⚠️ only the *claim* text |
| contradiction pair | `evidence_a_id`, `evidence_b_id` | ⚠️ **evidence-level**, which is finer than V1's data |
| contradiction quoted text | — | ❌ no column |
| contradiction `nature` | — | ❌ no column (survives only as prose inside `revisions.report_markdown`) |
| plan-gate review target | `reviews.plan_version_id` + `ck_review_plan` | ✅ **already correct** |
| a review with no revision | — | ❌ `reviews.revision_id` is NOT NULL |
| review ordinal | — | ❌ no ordinal, and no `run_id` either |
| evidence availability | — | ❌ only `migration_ledger` distinguishes the three states |

---

## 5. Loss classification

Using the taxonomy the task asks for: **intentional** (a decision recorded in M2A/M2B),
**accidental** (nobody decided it), or **not a loss**.

| # | Classification | Evidence |
|---|---|---|
| 1 | **Not a loss** | M2B §2.4 gives `sources` no snippet column deliberately; the data lives in `evidence`, which is strictly richer |
| 2 | **Accidental** | M2A §2.8 models a contradiction as "between two pieces of evidence" without noticing V1's detector works source-level; `nature` is simply absent from the model. M2C §13 planned `detection_state='DETECTED'` where pairs exist — the implementation writes `NOT_RUN` because `ck_contra_pair` made the plan unstorable. **Plan and code disagree; the code is right and the plan was never updated.** |
| 3 | **Accidental** | M2A §2.10 and M2B §2.10 both describe the plan gate and both give `reviews` a `plan_version_id`; neither says a plan review must also have a revision. The NOT NULL is an unexamined default |
| 4 | **Accidental** | M2B §2.4 requires `citation_index NOT NULL` on the implicit assumption that every source was numbered. Sources retrieved by a run that failed before synthesis were never numbered — a state V1 produces and V2 cannot express |
| 5 | **Accidental** | `compare_run` returns on the first matching condition; nothing decided that a V1 property should outrank a V2 absence |
| 6 | **Accidental** | M2A §2.10 gives `Review` its subject but no position; V1's ordinal was a free consequence of BIGSERIAL and its loss was not noticed |
| 7 | **Intentional, and wrong in hindsight** | M2B deliberately kept execution state out of the domain (M2A §3.4). But "we could not read the evidence" is a fact about the *record*, not about the execution, and V2's own honesty rule (`citation_resolution_rate` NULL ≠ 0) applies to it exactly |

---

## 6. Proposed domain changes

Six domain statements this proposal would add or correct. Schema follows in §7; nothing here
is implemented.

**D1 — A source's snippet list is a projection of evidence, not a stored fact.**
Three independent lines of evidence, all checked in code rather than assumed:

1. `graph._number_sources` computes `snippet` and `snippets` from the evidence list, stripping
   and de-duplicating. It has exactly one caller, `synthesizer_node`, and `sessions.sources`
   has exactly one writer (`outcome.sources`, both hosts).
2. `research_engine/verify_bundle.py` — the offline third-party verifier — **never reads**
   `sources[].snippet` or `sources[].snippets`. Evidence integrity is checked against
   `evidence[].content_hash`; `_check_claim_evidence_linkage` uses only `sources[].index` and
   `sources[].url`. The field is outside the trust boundary.
3. The frontend consumes it through `citations.tsx::snippetsOf()`, a rendering helper that
   already falls back to a legacy single `snippet` for older rows.

**Therefore the snippet on a source is derived/rendered data, and V2 storing it would create a
second copy that can disagree with the first.** V2 is correct as it stands.

**D2 — A contradiction's relationship is a domain fact, and its authoritative granularity is
source-level.** V1's detector is shown `{source_url: [snippets]}` and returns a pair naming two
source URLs. `validate_pairs` drops any pair whose URL was not in that input, so for every
surviving pair **both source URLs are guaranteed to be present in the evidence**, and hence in
`sessions.sources`. V2 models the pair one level finer than V1 ever observed it. The pair, the
two verbatim snippets, and `nature` are all facts the system produced and acted on — `nature`
is rendered into the report's "Conflicting evidence" block — and all three should be preserved.

**D3 — A plan-gate review's subject is a `ResearchPlan` version, not a `Revision`.** This is
already what the schema says (`ck_review_plan`: `(gate = 'PLAN') = (plan_version_id IS NOT NULL)`).
The only change needed is to stop *also* requiring a revision. `submit_plan` runs at
`AWAITING_PLAN`, which precedes any draft, so a plan approval with no report is normal V1
behaviour and must remain representable without fabricating anything.

**D4 — A `Source` may exist without a citation index.** "Retrieved" and "cited" are different
facts. V1 conflates them because the only writer of `sessions.sources` is the numbering
function. A run that gathered evidence and failed before synthesis retrieved sources that were
never numbered; V2 should be able to say so.

**D5 — A review has a position within its run.** The approval chain is an ordered record. V2
should be able to collect and order one run's reviews without joining through two different
parents.

**D6 — "No evidence" and "evidence unavailable" are different findings.** The same rule the
product already applies to `citation_resolution_rate` (NULL means unmeasured, never 0).

---

## 7. Proposed schema changes — isolated proposal, not applied

**None of this is implemented. The M2D schema is unchanged and `Review.revision_id` is
untouched.** Each item is scoped to be independently reviewable and independently revertible.

### S1 — `reviews`: allow a plan review with no revision *(gap 3)*

```
ALTER  reviews.revision_id       DROP NOT NULL
ADD    CHECK ck_review_report    (gate = 'REPORT') = (revision_id IS NOT NULL)
```

Consequences, each checked against the existing schema:

| Existing object | Effect |
|---|---|
| `uq_review_approval` (partial, `decision='APPROVED' AND gate='REPORT'`) | unaffected — `gate='REPORT'` now implies `revision_id IS NOT NULL` |
| `ix_review_revision` | now contains NULLs; still serves the report-gate read |
| delete chain `run → CASCADE revisions → RESTRICT reviews` | still protected for plan reviews via `run → CASCADE research_plans → RESTRICT reviews.plan_version_id` (that FK is already `RESTRICT`) |
| **`research_artifacts` composite FK to `reviews(id, decision)`** | ⚠️ **a new hole.** `ck_artifact_approved` checks only `decision='APPROVED'`; with plan approvals now storable without a revision, an artifact could reference a *plan* approval. **S1 must not ship without S2.** |

### S2 — `research_artifacts`: an artifact must cite a *report* approval *(consequence of S1)*

```
ADD    research_artifacts.review_gate  (mirrors reviews.gate, as review_decision mirrors decision)
ADD    UNIQUE reviews (id, decision, gate)
ALTER  FK fk_artifact_review → reviews(id, decision, gate)
ADD    CHECK ck_artifact_gate  review_gate = 'REPORT'
```

Exactly the technique already used for `review_decision`: the wrong reference becomes
unrepresentable rather than merely discouraged.

### S3 — `sources`: a source may be retrieved but never numbered *(gap 4)*

```
ALTER  sources.citation_index    DROP NOT NULL
DROP   UNIQUE uq_source_index (run_id, citation_index)
ADD    partial UNIQUE INDEX uq_source_index ON sources(run_id, citation_index)
                                            WHERE citation_index IS NOT NULL
KEEP   CHECK ck_source_cidx      citation_index IS NULL OR citation_index >= 1
```

Both dialect predicates (`postgresql_where` **and** `sqlite_where`) are required, per the trap
already documented for `uq_plan_approved` and `uq_review_approval`.

### S4 — `contradictions`: hold the pair at the granularity V1 recorded it *(gap 2)*

```
ADD    source_a_id, source_b_id   nullable, composite FK → sources(id, run_id)
ADD    quote_a, quote_b           nullable TEXT   (V1 snippet_a / snippet_b)
ADD    nature                     nullable TEXT
REPLACE CHECK ck_contra_pair
        (detection_state = 'DETECTED') =
          ((evidence_a_id IS NOT NULL AND evidence_b_id IS NOT NULL)
           OR (source_a_id IS NOT NULL AND source_b_id IS NOT NULL))
```

The relaxation is what lets a migrated pair say `DETECTED` truthfully: V1 detected it, at
source granularity, and V2 records exactly that. A V2-native detector that works evidence-level
still satisfies the same CHECK via the first disjunct. `evidence_a_id <> evidence_b_id` is
retained and mirrored for sources.

### S5 — `reviews`: a run-scoped ordinal *(gap 6)*

```
ADD    reviews.run_id     NOT NULL, FK → research_runs(id) ON DELETE RESTRICT
ADD    reviews.sequence   NOT NULL
ADD    UNIQUE (run_id, sequence)
```

`RESTRICT` for consistency with the rest of `reviews`: a review outlives its subject.
`sequence` is populated from the rank of `audit_log.id` within the session — a **lookup of a V1
fact**, not a generated ordering.

### S6 — `research_runs`: evidence availability *(gap 7)*

```
ADD    research_runs.evidence_capture  NOT NULL DEFAULT 'CAPTURED'
       CHECK IN ('CAPTURED',                       -- evidence rows are the complete record
                 'NONE_GATHERED',                  -- the run genuinely gathered nothing
                 'UNAVAILABLE_CHECKPOINT_MISSING',
                 'UNAVAILABLE_CHECKPOINT_UNREADABLE')
ADD    CHECK  evidence_capture <> 'CAPTURED' OR ... -- see note
```

The two `UNAVAILABLE_*` values are writable **only by the migration**. A V2-native run writes
evidence in the same transaction as the run, so it is always `CAPTURED` or `NONE_GATHERED`.

*Alternative considered and rejected:* leave the distinction in `migration_ledger` and require
every reader to join it. Rejected because the ledger is a migration artifact — V2 will hold
runs that never appear in it — so a reader would have to treat "no ledger row" as a fourth,
ambiguous state. That is the collapse this milestone exists to prevent, moved up a layer.

---

## 8. Proposed migration changes

Each is a *lookup* of a fact V1 recorded, never a fabrication.

**M1 — Contradictions map all seven fields *(gap 2, needs S4).***
`summary_a ← claim_a`, `quote_a ← snippet_a`, `nature ← nature`, and:

- `source_a_id ← sources` row whose `normalized_url` matches `_norm_url(source_a)`.
  Guaranteed present for validated pairs *when `sessions.sources` survives*.
- `evidence_a_id ←` the evidence row for that source whose `snippet` equals `snippet_a`
  exactly, **only if that match is unique**. Both sides are capped at 500 characters
  (`MAX_SNIPPET_CHARS` and `EvidenceChunk.snippet.max_length`), so an exact match is the
  expected case, but the detector is *asked* to copy verbatim and may not.
- `detection_state = 'DETECTED'` when either pair resolves; the pair columns that did not
  resolve stay NULL. **No fallback to "the first evidence row from that source"** — that would
  assert a link V1 never made.

Note `normalize_pairs` may have swapped `source_*` and `snippet_*` for weaker models. The
stored pair is post-normalisation, so the migration reads what V1 stored and does not re-run
the repair.

**M2 — Plan reviews migrate against the plan *(gap 3, needs S1+S2).***
`plan_approved` → `Review(gate='PLAN', plan_version_id=<the migrated plan>, revision_id=NULL)`.
The `REVIEW_WITHOUT_REVISION` refusal is then removed **only for the plan gate**. A `approved`
or `rework_requested` row with no report remains `INCONSISTENT_V1`: a report review with no
report is genuinely incoherent, not merely unrepresentable.
A `plan_approved` row for a run with **no plan** (`plan_json` and `outline_json` both NULL)
also remains a refusal — there is nothing to point `plan_version_id` at, and inventing a plan
version is out of bounds.

**M3 — Sources may be recovered from the evidence chunk *(gap 4, needs S3).***
Split the current single refusal in two:

| Sub-case | Today | Proposed |
|---|---|---|
| evidence with a **non-empty** `source_url` absent from `sessions.sources` | `INCONSISTENT_V1` | create the `Source` from the evidence's own `source_url` / `source_title`, `citation_index = NULL`, `retrieval_status = 'UNKNOWN'` |
| evidence with an **empty** `source_url` | `INCONSISTENT_V1` | **unchanged — still refuse** |

The first is not synthesis: `EvidenceChunk.source_url` is a required field written by the
executor, and it is the *only* other place a source URL is recorded (`agent_logs` payloads
carry counts, not evidence — checked). The second has no identity at all; V1's own numbering
already excluded it, and a `Source` for an empty URL would be an invention.

*Rejected alternative for the second sub-case:* migrate the run and silently drop the nameless
evidence item. Rejected **for now** because V2 cannot currently express "this run's evidence is
incomplete" — that is gap 7. Once S6 lands, a partial migration becomes expressible and this
should be revisited; the ordering in §13 reflects that.

**M4 — Review sequence *(gap 6, needs S5).*** `sequence` = rank of `audit_log.id` within the
session, 1-based; `run_id` = the session id.

**M5 — Evidence capture state *(gap 7, needs S6).*** Set from the tri-state read the migration
already performs: `READ` + items → `CAPTURED`; `READ` + none → `NONE_GATHERED`; `MISSING` →
`UNAVAILABLE_CHECKPOINT_MISSING`; `UNREADABLE` → `UNAVAILABLE_CHECKPOINT_UNREADABLE`. This
duplicates no judgement — it moves a distinction the ledger already holds into the domain,
where a reader will find it.

**M6 — Not-comparable taxonomy *(gap 5, no schema change).*** See §9.2.

---

## 9. Bundle-equivalence implications

### 9.1 The `sources` rule changes meaning, not mechanism

The V2 bundle already rebuilds `sources[].snippet(s)` by replaying `_number_sources` over the
migrated evidence, which is correct under D1. What changes is the **name and the reading** of
the resulting mismatch.

`SOURCE_SNIPPETS_NOT_STORED` should be renamed **`V1_SOURCE_SNAPSHOT_DIVERGED_FROM_EVIDENCE`**,
because that is what it detects: `sessions.sources` was computed from evidence that no longer
matches it. **Measured, not argued** — assembling the V1 bundle for a mismatching run and
running the shipped verifier over it:

```
claim_evidence_linkage  FAIL  3 linkage gap(s):
  claim cites [1] (https://example.invalid/doc-1) which has no evidence snippet
  claim cites [2] (…) which has no evidence snippet
```

The *V1* bundle fails its own integrity check. V2 is not lossy here; V1 was inconsistent, and
the comparison is correctly reporting a V1 fact. **M2E-3 §16.2 classified this as a V2 schema
limitation. That classification was wrong and is corrected here.**

Follow-on rule: a mismatch of this class should be reported alongside the V1 bundle's own
verifier verdict, so a reader can tell "V2 lost something" from "V1 disagreed with itself".

### 9.2 `NOT_COMPARABLE` — the 48 cases, decomposed

Today's reasons are mutually exclusive only because `compare_run` returns at the first match.
That ordering puts a V1 property ahead of a V2 absence, so **12 of the 48 report a V1 status when
the material fact is that the migration refused the run** — the 12 `INCONSISTENT_V1` runs, every
one of which is reported as though V1 were the reason. Three reason codes are unreachable.

Actual composition of the 48, traced to the seeding shape:

| Reported reason | n | True composition | What is actually being said |
|---|---:|---|---|
| `V1_STATUS_FAILED` | 28 | `no_report` 12 | V1 has no report; V1 would not export a bundle |
| | | `cancelled_as_failed` 8 | V1 has a report and evidence, and **V2 migrated it fine** — only V1's export route refuses non-COMPLETED runs |
| | | `orphan_evidence` 8 | **V2 has no run at all** (`INCONSISTENT_V1`) — masked |
| `V1_CHECKPOINT_MISSING` | 12 | — | no snapshot; the V1 bundle cannot be assembled truthfully |
| `V1_CHECKPOINT_UNREADABLE` | 4 | — | snapshot undecodable |
| `V1_STATUS_AWAITING_PLAN` | 4 | `plan_approved_no_report` 4 | **V2 has no run at all** — masked |
| **unreachable** | 0 | `V1_NO_REPORT` | shadowed by the status check |
| **unreachable** | 0 | `V2_RUN_ABSENT` | shadowed |
| **unreachable** | 0 | `V2_NO_REVISION` | shadowed |

Proposed replacement (M6): evaluate **both axes** and report both, with no generic bucket.

```
V1 side  — could V1 have exported a bundle?
  V1_EXPORTABLE
  V1_STATUS_NOT_COMPLETED          (V1's own route refuses it)
  V1_NO_REPORT
  V1_CHECKPOINT_MISSING
  V1_CHECKPOINT_UNREADABLE

V2 side  — does V2 hold a comparable representation?
  V2_PRESENT
  V2_RUN_ABSENT                    (ledger says INCONSISTENT_V1 or FAILED)
  V2_NO_REVISION
  V2_EVIDENCE_UNAVAILABLE          (once S6 lands)

verdict = EQUIVALENT | MISMATCH   iff  V1_EXPORTABLE and V2_PRESENT
        = NOT_COMPARABLE(v1_reasons, v2_reasons)  otherwise
```

**Each axis yields a set, not a winner.** A run can be both non-COMPLETED and report-less, and
picking one would repeat, one level down, exactly the mistake this replaces. Under that
taxonomy the same 48 read:

| V1 reasons | V2 reasons | n | Shape |
|---|---|---:|---|
| `STATUS_NOT_COMPLETED`, `NO_REPORT` | `PRESENT` | 12 | `no_report` |
| `STATUS_NOT_COMPLETED` | `PRESENT` | 8 | `cancelled_as_failed` — V2 migrated it fine |
| `STATUS_NOT_COMPLETED`, `NO_REPORT` | `RUN_ABSENT` | 8 | `orphan_evidence` |
| `CHECKPOINT_MISSING` | `PRESENT` | 12 | `missing_checkpoint` |
| `CHECKPOINT_UNREADABLE` | `PRESENT` | 4 | `unreadable_checkpoint` |
| `STATUS_NOT_COMPLETED`, `NO_REPORT` | `RUN_ABSENT` | 4 | `plan_approved_no_report` |

Every case names both sides; the 12 `V2_RUN_ABSENT` runs are visible as migration outcomes
rather than as V1 properties; nothing lands in a generic bucket.

### 9.3 New expected outcomes once §7–§8 land

| Change | Effect on the 200-run corpus |
|---|---|
| M1 + S4 | the 12 `CONTRADICTION_PAIR_NOT_STORED` mismatches become `BUNDLE_EQUIVALENT`, **provided** the V1 bundle's contradiction dicts and the V2 rebuild agree field for field — which requires the V2 bundle to emit `snippet_a/b`, `source_a/b` and `nature`, not just the claims |
| M2 + S1 + S2 | 4 runs move from `INCONSISTENT_V1` to `MIGRATED`; their bundles become comparable |
| M3 + S3 | 8 runs move from `INCONSISTENT_V1` to `MIGRATED`; note their V1 status is `FAILED`, so they become `NOT_COMPARABLE(V1_STATUS_NOT_COMPLETED, V2_PRESENT)` rather than equivalent |
| M6 | `NOT_COMPARABLE` count unchanged at 48; the *reasons* stop masking |
| M4 + S5, M5 + S6 | no bundle effect; M4 removes a latent ordering ambiguity |

`KNOWN_LOSSY` shrinks to one entry (the renamed source-divergence class). The rule that an
**unclassified mismatch fails the dry run** is retained unchanged — it is what stopped these
gaps from being absorbed as "expected" in the first place.

### 9.4 A separate defect in the M2E-2 corpus

The dry-run fixtures use placeholder `draft_hash` values (`"a"*64`, `"b"*64`) rather than
`sha256(report)`. Consequence, verified by running the shipped verifier over an assembled
fixture bundle:

```
approval_chain  FAIL  No 'approved' entry's draft_hash matches report_hash
                      — the approval record does not apply to this report
```

Every bundle in the M2E-2 corpus fails `approval_chain`, on both sides. This does **not**
invalidate the equivalence result — two representations were compared and found equal, which is
what `BUNDLE_EQUIVALENT` claims and all it claims — but it means M2E-2 never demonstrated that
a migrated run produces a bundle that *verifies*. The corpus must set `draft_hash =
sha256(report)`, and the dry run must additionally assert that every `BUNDLE_EQUIVALENT` run's
bundle passes `verify_bundle` on **both** sides. Listed as a precondition in §14.

---

## 10. Historical information that cannot be recovered

Unchanged from M2E-3 §14 — per-item attestation, superseded drafts, plan origin, retrieval
status, claim lineage, user cancellation, the Redis cancel key, and the rest of the checkpoint.
This section records only what §6–§8 **do not** recover, and why.

| Not recovered | Why | Proposal |
|---|---|---|
| the citation index of a source that was never numbered | the synthesizer assigns it and never ran | `citation_index = NULL` (S3). Never generated |
| the evidence row behind a contradiction side whose `snippet_a` matches no evidence snippet, or matches more than one | V1 stored the quote, not a reference | leave `evidence_a_id` NULL; `source_a_id` still resolves (S4/M1) |
| the source of an evidence item whose `source_url` is the empty string | no identity exists anywhere in V1 | the run stays `INCONSISTENT_V1` (M3) |
| `nature` for a contradiction detected by a run that never synthesised | the field is stored in the checkpoint, so it **is** recovered — but a run with no report has no rendered block to cross-check it against | stored as-is; no cross-check claimed |
| the ordering of two `audit_log` rows if `id` ordering is ever lost | BIGSERIAL is the only ordinal V1 has | S5 copies it while it still exists — **this is a reason not to defer M2F indefinitely** |
| whether a `plan_approved` hash ever matched anything | nothing in V1 has ever verified the plan-gate `draft_hash` (M2A §8) | `reviewed_hash` stays opaque for the plan gate; the bundle must not assert it resolves |

---

## 11. Risks

| # | Risk | Severity | Mitigation |
|---|---|---|---|
| R1 | **S1 without S2 lets an artifact cite a plan approval** — the load-bearing "approval as a database fact" property silently weakens | **High** | ship S1 and S2 as one migration; plant "artifact references a PLAN review" and require it to fail |
| R2 | M1's snippet matching links the wrong evidence row when a source has two identical snippets | Medium | require the match to be **unique**; leave NULL otherwise. Plant "ambiguous snippet resolves to the first row" |
| R3 | M3 creates a `Source` per unique URL from evidence and collides with `uq_source_url` if normalisation differs from V1's | Medium | reuse `_norm_url`; migration is per-run and deterministic, so a collision is a bug not a race. Plant it |
| R4 | S3 makes `citation_index` nullable and a future reader assumes it is present | Medium | the partial unique index and `ck_source_cidx` keep the invariant for numbered sources; readers must treat NULL as "not cited", and the V2 bundle assembler must skip unnumbered sources |
| R5 | S6's `evidence_capture` becomes a second, drifting copy of the ledger's `evidence_outcome` | Medium | the ledger stays authoritative **for the migration**; the column is authoritative **for the domain**. One writer each. A parity test should pin them for migrated runs |
| R6 | Relaxing `ck_contra_pair` (S4) admits a pair with sources but no evidence for V2-*native* detection, which should be evidence-level | Low | acceptable and deliberate: the constraint enforces *coherence*, not *ambition*. Revisit if a native detector regresses |
| R7 | Five schema changes at once means a large, hard-to-review Alembic revision | Medium | §13 sequences them into four independently revertible steps |
| R8 | **The V2 tables are still empty in production, so all of this is cheap now and expensive later** | — | this is the argument for doing M2F before, not after, the production migration |

---

## 12. Migration safety implications

Nothing in §7–§8 changes the safety properties M2E-2 established, and each must be re-proven
rather than assumed:

- **One transaction per run** — unchanged. M3 adds inserts inside the same transaction.
- **Deterministic identity** — the recovered `Source` rows in M3 need a deterministic key.
  `_det("source", sid, norm)` already keys on the normalised URL, so a recovered source and a
  snapshot source with the same URL produce the **same id** by construction. That is correct
  (they are the same source) and must be pinned by a test, because it is the one place M3 could
  silently produce a duplicate.
- **Idempotency** — `research_runs.id = session.id` remains the top-level boundary; uuid5 child
  ids remain defence in depth. The P3 two-database test must be extended to cover the new child
  rows (recovered sources, plan-gate reviews).
- **Resume** — unchanged; the ledger contract is untouched.
- **Refusals** — two of the five refusals narrow (§8 M2, M3), three are unchanged. Every
  narrowing needs its plant re-verified: the plants must now fail for the *remaining* case and
  pass for the newly-migratable one, or the safety net has been widened rather than moved.
- **Never invent** — the rule is unchanged and is the reason M3 splits in two and M1 leaves
  unresolved sides NULL.

**Ledger consequences.** `INCONSISTENT_V1` counts drop from 12/200 to 0/200 in the corpus.
That is a real improvement and also a hazard: a smaller refusal count must not be read as
"the migration got better at recovering data" when part of it is "the schema stopped
forbidding data V1 always had". The M2F validation report should state both numbers.

---

## 13. Recommended implementation order

Four steps. Each is independently revertible and each ends with the dry run green on both
dialects and every plant firing.

| Step | Contents | Why here |
|---|---|---|
| **F1** | M6 + the §9.4 corpus fix + the rename in §9.1 | **No schema change at all.** Fixes the measurement before changing what is measured, so every later step is judged against an honest baseline |
| **F2** | S1 + S2 + M2 | The highest-value gap and the one with a security-shaped consequence (R1). Ships as one migration so the artifact hole never exists |
| **F3** | S3 + M3, then S6 + M5 | S3 recovers sources; S6 then makes the residual empty-URL case expressible, at which point M3's rejected alternative can be reconsidered on evidence |
| **F4** | S4 + M1, then S5 + M4 | Lowest risk, no effect on refusals; S5 should not be deferred past the point where `audit_log.id` ordering is still available (§10) |

Each step's exit criteria: dry run green on Postgres **and** SQLite, all plants fire, the new
plants for R1/R2/R3 fire, and `KNOWN_LOSSY` has not grown.

---

## 14. Explicit decisions required before a restored-production dry run

Nine, each needing a yes/no rather than a discussion. The first four block; the rest can be
taken during F1–F4.

| # | Decision | Recommendation |
|---|---|---|
| **1** | Does a plan-gate review attach to `ResearchPlan` and not `Revision`? (S1) | **Yes** — the schema already says so; only the NOT NULL disagrees |
| **2** | Must an artifact cite a REPORT approval, enforced in the database? (S2) | **Yes** — and it must ship with S1, not after |
| **3** | May a `Source` exist with no citation index? (S3) | **Yes** — "retrieved" and "cited" are different facts |
| **4** | Is a `Source` derived from `evidence.source_url` a recovery or an invention? (M3) | **Recovery.** `EvidenceChunk.source_url` is a required V1 field written by the executor; no other V1 location records it |
| 5 | Should `contradictions` hold the pair at source granularity, and store `quote_a/b` and `nature`? (S4) | **Yes** — source-level is the granularity V1 observed; `nature` currently survives only as prose |
| 6 | Should `reviews` gain `run_id` + `sequence`? (S5) | **Yes**, and early — the ordinal exists only while `audit_log` does |
| 7 | Should evidence availability be a domain column or stay ledger-only? (S6) | **Domain column** — V2 will hold runs the ledger never saw |
| 8 | Should the bundle comparison report both a V1 reason and a V2 reason? (M6) | **Yes** — 12 of 48 currently mask a migration failure |
| 9 | Must every `BUNDLE_EQUIVALENT` run also pass `verify_bundle` on both sides? (§9.4) | **Yes** — equivalence without verifiability was never the claim, but it is what a reader will assume |

**Still not authorised by this document:** migrating production, running against a restored
production copy, switching reads or writes to V2, dual-read, dual-write, removing any V1 table
or column, or implementing any of S1–S6 or M1–M6.
