# RFC: V2 Domain Model

**Status:** Approved in principle (M2A) · **Amendment 1 applied** — see §13
**Scope:** Documentation only. No migrations, no tables, no code.
**Supersedes:** nothing yet. Informs M2B onward.
**Depends on:** the V1→V2 audit (`internal/V2_Audit_and_Migration_Map.md`) and the findings
of M0A, M0B, M0C, M1 and M1.5.

---

## 0. Why this document exists

V1 stores a research run as **one row plus three side-channels**: a `sessions` row carrying
the report text and a JSON blob of sources, a LangGraph checkpoint carrying the evidence and
contradictions, an `agent_logs` table carrying the trace, and an `audit_log` table carrying
human decisions. Nothing in the database says what a *claim* is — claims are re-derived from
report prose by a regex, on demand, at bundle-export time.

That arrangement produced every defect the M0/M1 milestones found. Claim extraction had two
implementations that could disagree (M0A). The artifact that proves the product's central
promise was unreachable from the product (M0C). Whole subsystems existed twice and never met
(M1.5). None of these were careless; they are what happens when the authoritative location of
a fact is not written down anywhere.

So this RFC's job is not to draw a prettier schema. It is to answer, for every fact the
product asserts, **exactly one question**: where does this live, and who is allowed to say it?

The V2 Master Plan §5 names the entities. This document defines them, and resolves twelve
ambiguities that V1 left open.

---

## 1. Design commitments

These constrain everything below.

**C1 — One authority per fact.** Every fact has exactly one authoritative representation.
Everything else is derived, cached, or a snapshot, and is labelled as such. Where V1 has two
homes for one fact, this RFC picks one and says what the other becomes.

**C2 — Provenance is three-valued.** Evidence is `ATTESTED`, `UNATTESTED`, or `UNCHECKED`.
Collapsing the third into either of the first two is the "unmeasured is not zero" failure in
a new costume, and it is forbidden. See §4.

**C3 — Approval applies to a specific text.** What a human approved must be recoverable
exactly, byte for byte, forever. V1 achieves this with `audit_log.draft_hash`; V2 keeps the
property and gives it a better home.

**C4 — Artifacts are snapshots, not views.** A `ResearchArtifact` is immutable and
self-contained. It does not join to live tables at read time. If the live data later changes,
the artifact does not.

**C5 — The domain does not depend on the orchestrator.** LangGraph checkpoints are execution
state. Nothing the product asserts may be readable *only* from a checkpoint. (V1 violates
this: evidence and contradictions live nowhere else.)

**C6 — Migration never manufactures provenance.** V1 did not record whether a snippet was
verified in most cases. V2 must not guess. Migrated evidence is `UNCHECKED` unless V1
genuinely recorded otherwise.

**C7 — The report is a rendering, never a source of truth.** The rendered report is never
authoritative for claims, evidence, citations, provenance, review, or approval. The domain
model is authoritative; the report is a projection of it.

This is the commitment V1 most thoroughly lacked, and nearly every defect M0/M1 found is a
consequence of its absence: claims were regex-extracted from prose, `[n]` markers *were* the
claim↔evidence relation, and the only record of what a human approved was a hash of a text
that had since been overwritten. Anything the product asserts must be readable from the
domain model with the report absent. Where the two disagree, the domain model is right and
the report is stale — never the reverse. Added by Amendment 1 (§13).

---

## 2. Entity catalogue

Notation: **A** = authoritative, **D** = derived (recomputable), **S** = snapshot (frozen
copy), **I** = immutable after creation, **M** = mutable.

---

### 2.1 Project

**Purpose.** A persistent workspace for a topic or decision. The unit of scoping for corpus,
memory and history.

**Identity.** `id` (UUID, surrogate). Names are mutable and not identifying.

**Ownership / security boundary.** `owner_id`. Every read of anything beneath a Project must
filter on ownership *in SQL*, before content reaches a model. This is V1's rule
(`app/services/memory.py`) and it is upheld, not relaxed.

**Lifecycle.** `active → archived → deleted`. Archiving is reversible and loses nothing.

| Field | Kind |
|---|---|
| `id`, `owner_id`, `created_at` | A, I |
| `name`, `description` | A, M |
| `archived_at` | A, M |

**Relationships.** Has many `ResearchRun`, many `ProjectMemory` entries, one corpus.

**Deletion.** Cascades to runs, revisions, reviews, memory. **Does not cascade to
`ResearchArtifact` or `AuditEvent`** — see §2.11 and §2.12.

**Versioning.** None. Projects are mutable containers.

**Provenance.** User-authored throughout.

**V1 mapping.** `projects` table, essentially unchanged. Safe to migrate.

---

### 2.2 ResearchRun

**Purpose.** One execution of research against one question. Replaces `sessions` as the
*execution* record — but not as the *result* record, which is what V1 conflated (§3.12).

**Identity.** `id` (UUID). Also the LangGraph `thread_id`, as in V1.

**Ownership.** Via `project_id`. A run outside a project is not representable.

**Lifecycle.** See §6.1. `PENDING → RUNNING → AWAITING_PLAN → RUNNING → AWAITING_REVIEW →
{COMPLETED | FAILED | CANCELLED}`.

| Field | Kind | Note |
|---|---|---|
| `id`, `project_id`, `created_at` | A, I | |
| `question` | A, I | The run's question does not change. A new question is a new run. |
| `depth`, `corpus_mode`, `demo`, `skip_plan_gate`, `topic_seeds`, `outline_template` | A, I | Run configuration, frozen at start. |
| `status` | A, M | |
| `cancelled_at`, `cancel_requested_by` | A, M | New in V2. See §3.11. |
| `model_routing` | A, I after first resolution | What was actually dialled, not what is configured now. |
| `cost_usd`, `tokens_input`, `tokens_output`, `elapsed_seconds` | A, M | Accumulate during the run, frozen at terminal state. |
| `error_message` | A, M | |
| `citation_resolution_rate` | **D** | Recomputable from the current Revision + Sources. Cached for list views. |

**Relationships.** Belongs to Project. Has one current `ResearchPlan`, many `Source`, many
`Evidence`, many `Revision`, many `Review`, many `Contradiction`, at most one
`ResearchArtifact`.

**Deletion.** Cascades to plan, sources, evidence, revisions, reviews, contradictions.
**Does not delete the artifact or the audit events** (§2.11, §2.12).

**Versioning.** The run is not versioned. Its *output* is, via `Revision`.

**Provenance.** `question` and config are user-authored. Metrics are system-measured.

**V1 mapping.** `sessions`, minus the report columns (→ `Revision`), minus `sources` JSON
(→ `Source`), minus `rework_count` (→ derived, §3.3), minus `plan_json`/`outline_json`
(→ `ResearchPlan`).

---

### 2.3 ResearchPlan

**Purpose.** The structured set of tasks and the report outline the run intends to
investigate. The thing a human edits at the design gate.

**Identity.** `id`; `(run_id, version)` unique.

**Lifecycle.** `PROPOSED → (edited) → APPROVED`, or `PROPOSED → SUPERSEDED`. See §6.2.

| Field | Kind |
|---|---|
| `id`, `run_id`, `version`, `created_at` | A, I |
| `tasks` (ordered, each with `include`), `outline_sections` | A, I *per version* |
| `origin` (`MODEL_PROPOSED` \| `HUMAN_EDITED` \| `TEMPLATE`) | A, I |
| `approved_at` | A, M (write-once) |

**Immutability.** A plan version is immutable once written. A human edit creates version
`n+1` with `origin = HUMAN_EDITED`; it does not overwrite the model's proposal. **This is a
deliberate change from V1**, which overwrote `plan_json` with the approved plan and thereby
destroyed the evidence of what the model had proposed and what the human changed. That diff
is one of the product's more interesting signals (the Master Plan's "human correction rate",
§28), and V1 threw it away on every run.

**Relationships.** Belongs to ResearchRun.

**Deletion.** Cascades with the run.

**Provenance.** `MODEL_PROPOSED` versions are model output. `HUMAN_EDITED` are user-authored.
Never conflated.

**V1 mapping.** `sessions.plan_json` + `outline_json` + `plan_approved_at`. Migrates as a
**single** version with `origin = UNKNOWN`, because V1 cannot tell us whether the stored plan
was edited (§8).

---

### 2.4 Source

**Purpose.** A document that was retrieved — a web page or a corpus document. The thing a
citation resolves *to*.

**Identity.** `id`; unique on `(run_id, normalized_url)`.

**Ownership.** Via run → project.

**Lifecycle.** Created during evidence gathering. Never updated.

| Field | Kind |
|---|---|
| `id`, `run_id`, `url`, `normalized_url`, `retrieved_at` | A, I |
| `title` | A, I |
| `kind` (`WEB` \| `CORPUS`) | A, I |
| `corpus_document_id` | A, I, nullable |
| `citation_index` | A, I | The `[n]` this source is cited as, assigned at first appearance. |
| `retrieval_status` (`FETCHED` \| `SEARCH_RESULT_ONLY` \| `FAILED`) | A, I |

`retrieval_status` is new and load-bearing. V1 could not distinguish "we fetched this page
and read it" from "we only ever saw a search-result snippet mentioning it". The provenance
model (§4) needs that distinction, because a snippet attested against a search result is a
weaker claim than one attested against fetched body text.

**Relationships.** Belongs to run. Has many Evidence.

**Deletion.** Cascades with the run.

**Versioning.** None. A re-fetch in a later run is a *different run's* Source. External
content changing over time is explicitly not modelled (§9).

**Provenance.** `url` and `title` as reported by the retrieval tool. **Note the honest
limitation:** in V1 these arrive through the model's `submit_evidence` arguments, so a
model-invented URL is recorded as a Source. V2 keeps this exposure at the *Source* level and
addresses it at the *Evidence* level (§4). Closing it fully means having the executor emit
source records from tool output directly rather than through the model — worth doing, and
deferred (§10).

**V1 mapping.** `sessions.sources` JSON. Migratable; `retrieval_status` becomes `UNKNOWN`.

---

### 2.5 Evidence

**Purpose.** One concrete extracted piece of source-derived information — a verbatim snippet
plus the paraphrase the executor drew from it. The atom of the verifiability claim.

**Identity.** `id`; content-addressed by `content_hash = sha256(snippet)` for integrity.

**Ownership.** Via run → project.

**Lifecycle.** Created during gathering, then **immutable**.

| Field | Kind |
|---|---|
| `id`, `run_id`, `source_id`, `task_id`, `created_at` | A, I |
| `snippet` | A, I | The verbatim quotation. |
| `content_hash` | **D**, I | `sha256(snippet)`. Derived but stored, for artifact integrity. |
| `key_fact` | A, I | The executor's paraphrase. **Never citable on its own** (§3.5). |
| `provenance_state` | A, I | `ATTESTED` \| `UNATTESTED` \| `UNCHECKED`. See §4. |
| `attested_against` | A, I | `FETCHED_BODY` \| `SEARCH_SNIPPET` \| `CORPUS_DOCUMENT` \| `null`. |
| `attestation_run_at` | A, I | Null iff `UNCHECKED`. |

**Immutability.** Total. V1 *mutates* evidence: `verify_evidence_snippets` blanks the
`snippet` field in place when it fails verification. V2 does not — it records
`provenance_state = UNATTESTED` and **keeps the text**, because a snippet the model invented
is itself evidence of a problem, and destroying it makes the failure unauditable. Rendering
rules (do not display an unattested quotation as a quotation) belong to the presentation
layer, not to storage.

**Relationships.** Belongs to Source and ResearchRun. Linked to Claims via ClaimEvidenceLink.

**Deletion.** Cascades with the run.

**Versioning.** None; immutable.

**V1 mapping.** LangGraph checkpoint `state["evidence"]`. This is the single largest
structural change in V2 (§3.7). Migration is possible for live checkpoints and impossible for
pruned ones.

---

### 2.6 Claim

**Purpose.** One assertion the research makes. First-class and persisted, not re-derived
from prose.

**Identity.** `id`; ordered within a Revision by `position`.

**Ownership.** Via revision → run → project.

**Lifecycle.** Created when a Revision is created. Immutable thereafter; a changed claim is a
new Claim in a new Revision.

| Field | Kind |
|---|---|
| `id`, `revision_id`, `position`, `created_at` | A, I |
| `text` | A, I | The sentence as it appears in the report. |
| `extraction_method` | A, I | `DERIVED_FROM_REPORT` \| `MODEL_STRUCTURED` \| `HUMAN_EDITED`. |
| `verification_state` | A, I | See below. |
| `verification_method` | A, I | `NUMERIC_GROUNDING` \| `MODEL_JUDGE` \| `NOT_RUN`. |

**`verification_state`** ∈ `SUPPORTED`, `UNSUPPORTED`, `INSUFFICIENT_EVIDENCE`, `UNCHECKED`.
Deliberately four values, not a score. `UNCHECKED` exists for the same reason `UNCHECKED`
exists for evidence, and `INSUFFICIENT_EVIDENCE` is distinct from `UNSUPPORTED`: "the
evidence contradicts this" and "there is not enough evidence to say" are different findings
and V1 conflated both into a stripped citation marker.

No confidence number. See §9.

**Relationships.** Belongs to Revision. Links to Evidence via ClaimEvidenceLink.

**Deletion.** Cascades with the revision.

**Versioning.** Via Revision. Claims are never edited in place.

**Provenance.** `extraction_method` records how the claim came to exist. In V2's first
implementation it will be `DERIVED_FROM_REPORT` for everything, because that is what the
pipeline does today — and recording that honestly is the point (§3.5).

**V1 mapping.** **Nothing to migrate.** V1 has no persisted claims. They can be *derived* for
historical runs by running `research_engine.claims.claim_lines` over a stored report, with
`extraction_method = DERIVED_FROM_REPORT` and `verification_state = UNCHECKED`.

---

### 2.7 ClaimEvidenceLink

**Purpose.** The relationship that makes the claim graph a graph. Connects one Claim to one
Evidence with a stance.

**Identity.** `id`; unique on `(claim_id, evidence_id)`.

| Field | Kind |
|---|---|
| `id`, `claim_id`, `evidence_id`, `created_at` | A, I |
| `stance` | A, I | `SUPPORTS` \| `CONTRADICTS` \| `CONTEXT`. |
| `origin` | A, I | `CITATION_MARKER` \| `MODEL_ASSERTED` \| `HUMAN_ASSERTED`. |

**Why `origin` matters.** In V1 the only link that exists is "this sentence carried `[3]`".
That is a *typographic* fact about the report, not a semantic one, and V2 must not let it
masquerade as a considered judgement. `CITATION_MARKER` says plainly where the link came
from.

**Deletion.** Cascades with the claim.

**V1 mapping.** Derivable from citation markers in a stored report plus the source list, with
`stance = SUPPORTS` and `origin = CITATION_MARKER`. Nothing stronger is honest —
`CONTRADICTS` links do not exist in V1 at all.

---

### 2.8 Contradiction

**Purpose.** A detected conflict between two pieces of evidence. Preserved, never resolved by
the system.

**Identity.** `id`.

| Field | Kind |
|---|---|
| `id`, `run_id`, `created_at` | A, I |
| `evidence_a_id`, `evidence_b_id` | A, I |
| `summary_a`, `summary_b` | A, I | The model's rendering of each side. |
| `dimension` | A, I, nullable | `TIMEFRAME` \| `METHODOLOGY` \| `POPULATION` \| `WORKLOAD` \| `SOURCE_QUALITY` \| `UNCLASSIFIED`. |
| `detection_state` | A, I | `DETECTED` \| `NOT_RUN` \| `DETECTOR_UNAVAILABLE`. |
| `review_state` | A, M | `UNREVIEWED` \| `ACKNOWLEDGED` \| `DISMISSED`. |

`detection_state` carries the same three-valued honesty as everything else: V1's detector
fails closed and surfaces nothing when unavailable, which is correct behaviour but currently
indistinguishable from "no conflicts found". A run where the detector never ran and a run
with a clean bill of health must not look identical.

`dimension` is deliberately a small closed list with `UNCLASSIFIED`, not free text.

**Deletion.** Cascades with the run.

**V1 mapping.** Checkpoint `state["contradictions"]`. Same fate as evidence (§3.7).

---

### 2.9 Revision

**Purpose.** One draft of the report, with its claims. The unit that gets reviewed.

**Identity.** `id`; `(run_id, version)` unique, `version` starting at 1.

**Lifecycle.** `DRAFT → UNDER_REVIEW → {APPROVED | REWORK_REQUESTED | SUPERSEDED}`.

| Field | Kind |
|---|---|
| `id`, `run_id`, `version`, `created_at` | A, I |
| `report_markdown` | A, I | **Immutable.** This is the byte sequence a human approves. |
| `report_hash` | **D**, I | `sha256(report_markdown)`. |
| `state` | A, M |
| `superseded_by_id` | A, M |

**Why this entity exists.** It is the missing piece in V1. `sessions.draft_report` is a
mutable column, overwritten on every rework loop. So V1 cannot show you what the second draft
said after the third exists, cannot show a reviewer what changed, and relies on
`audit_log.draft_hash` to prove *retrospectively* that a decision applied to a text that is
no longer stored anywhere. Revisions make the history real.

Each rework produces a new Revision. `rework_count` becomes `count(revisions) - 1` (§3.3).

**Deletion.** Cascades with the run.

**Provenance.** Model-authored prose. Human edits, when implemented, produce a new Revision
with an `origin` marker — deferred (§10).

**V1 mapping.** `sessions.draft_report` and `final_report` collapse into Revisions. A V1
session yields **one** Revision (the surviving draft), not `rework_count + 1` of them, because
the earlier drafts were overwritten and are genuinely gone (§8).

---

### 2.10 Review

**Purpose.** A human decision about a specific Revision. The product's trust boundary.

**Identity.** `id`.

| Field | Kind |
|---|---|
| `id`, `revision_id`, `reviewer_id`, `created_at` | A, I |
| `decision` | A, I | `APPROVED` \| `REWORK_REQUESTED` \| `REJECTED`. |
| `feedback` | A, I |
| `reviewed_hash` | A, I | `sha256` of the exact text reviewed. |
| `gate` | A, I | `PLAN` \| `REPORT`. |
| `plan_version_id` | A, I, nullable | Set iff `gate = PLAN`. |

**Immutability.** Total, and enforced. A Review is a record of something a person did; it is
never edited or deleted. See §3.1 for its relationship to AuditEvent, and §3.2 for why
`reviewed_hash` is not the overloaded `draft_hash`.

**Deletion.** **Does not cascade with the revision or the run.** A Review outlives its
subject deliberately — deleting a run must not silently erase the record that a human
approved something. It becomes an orphaned record retaining its hashes.

**V1 mapping.** `audit_log` rows with `action ∈ {approved, rework_requested}` → Reviews with
`gate = REPORT`. Rows with `action = plan_approved` → Reviews with `gate = PLAN`. Safe to
migrate; `reviewer_id` = `audit_log.user_id`.

---

### 2.11 ResearchArtifact

**Purpose.** The immutable, self-contained, verifiable record of an approved research result.
The thing you hand to someone who should not have to trust you.

**Identity.** `id`; `artifact_hash` is its content identity.

**Lifecycle.** Created once, on approval. **Never updated.** See §6.4.

| Field | Kind |
|---|---|
| `id`, `run_id`, `revision_id`, `review_id`, `created_at` | A, I |
| `format_version` | A, I | Currently 1. Not changed by this RFC. |
| `payload` | **S**, I | The complete frozen snapshot: question, plan, sources, evidence, claims, links, contradictions, review chain, report, model routing, cost, timings. |
| `artifact_hash` | **D**, I | Over the whole payload except itself. |
| `demo` | A, I | Hash-covered, as in V1. |

**C4 in practice.** The payload is a *copy*, not a set of foreign keys. Reading an artifact
never joins to `runs`, `sources` or `evidence`. If a source row is later deleted, the
artifact still verifies. This is the whole point of §3.9.

**Deletion.** An artifact is not deleted when its run is deleted. Deleting an artifact is an
explicit, separate, user-initiated act.

**Versioning.** `format_version` versions the *schema*. The artifact's content is immutable;
new research produces a new artifact, never an edit.

**V1 mapping.** This is the `.bundle.json` that already exists — see §3.8. V2 persists what
V1 assembled on demand.

---

### 2.12 AuditEvent

**Purpose.** An append-only log of consequential actions, for accountability. **Not** the
domain record of a decision — that is Review.

**Identity.** `id`, monotonically ordered.

| Field | Kind |
|---|---|
| `id`, `actor_id`, `occurred_at`, `action`, `subject_type`, `subject_id` | A, I |
| `metadata` | A, I | Small JSON. |

**Deletion.** Never. Does not cascade from anything. An audit log that disappears with its
subject is not an audit log.

**V1 mapping.** V1's `audit_log` is doing *both* jobs at once. It splits (§3.1): the decision
content becomes Review; the fact that an action occurred becomes AuditEvent. Migration writes
both from the same rows.

---

### 2.13 ProjectMemory

**Purpose.** Approved knowledge, retrievable in later research and chat within one project.

**Identity.** `id`; unique on `(artifact_id, chunk_index, embedding_model)`.

| Field | Kind |
|---|---|
| `id`, `project_id`, `artifact_id`, `chunk_index`, `created_at` | A, I |
| `text` | **D**, I | Chunked from the artifact's report. |
| `embedding`, `embedding_model` | **D**, I |

**The eligibility rule (§3.10).** A memory entry may only be created from a
**ResearchArtifact**. Not from a run, not from a revision, not from a draft, not from chat.
V1 gates on `session.status == COMPLETED`, which is a proxy for approval; V2 makes the
artifact itself the gate, so the rule is structural rather than conventional. There is no
code path that can write memory from an unapproved source, because the foreign key points at
a table that only approval can populate.

**Deletion.** Cascades from the artifact. Re-indexing with a new embedding model replaces
wholesale, as in V1.

**Provenance.** Wholly derived. Rebuildable from the artifact at any time, which is why the
embedding model is part of the identity.

**V1 mapping.** `memory_chunks`, re-pointed from `source_session_id` to `artifact_id` once
artifacts are backfilled.

---

## 3. Resolved ambiguities

### 3.1 AuditLog vs Review

**V1.** One table, two jobs. `audit_log` is simultaneously the domain record of a human
decision (read by the bundle to build `approval_chain`) and a general accountability log.

**Resolution.** Split.

- **Review** is the domain object: which revision, which decision, what feedback, what hash.
  It has meaning to the product and appears in artifacts.
- **AuditEvent** is the accountability log: who did what to which subject, when. It is
  append-only, never cascades, and includes actions with no domain object at all (key added,
  project deleted, artifact exported).

Both are written when a review happens. They answer different questions: Review answers "what
was decided about this report", AuditEvent answers "what has this account done".

**Rejected:** keeping one table with a discriminator. It is what V1 does, and it is why
`draft_hash` is overloaded — a single table forces one column to mean different things for
different rows.

### 3.2 The `draft_hash` overload

**V1.** `audit_log.draft_hash` holds `sha256(draft_report)` for report-gate rows, and
`sha256(json.dumps({tasks, outline}, sort_keys=True))` for plan-gate rows. One column, two
hashed objects, no discriminating field beyond `action`. Only the report meaning is ever
verified; the plan-gate hash is checked by nothing, anywhere.

**Resolution.** `Review.reviewed_hash` + `Review.gate`. The hash's meaning is determined by
`gate`: `REPORT` hashes `Revision.report_markdown`; `PLAN` hashes the canonical serialisation
of `ResearchPlan`. `plan_version_id` points at the exact plan version, so the plan-gate hash
becomes verifiable — which it currently is not.

**Rejected:** two nullable columns (`reviewed_report_hash`, `reviewed_plan_hash`). Same
information, more nulls, and it invites a row with both set.

### 3.3 `sessions.rework_count` vs audit history

**V1.** Two records of one fact. `rework_count` is an integer on the session, incremented by
the approve route and *also* written from `RunOutcome.rework_count`; the audit log
independently contains one `rework_requested` row per rework. Nothing reconciles them, and
the rework cap (3) reads the column while the bundle reads the log.

**Resolution.** `rework_count` is **derived**: `count(revisions) - 1`, equivalently
`count(reviews where decision = REWORK_REQUESTED)`. It stops being stored. The cap reads the
derived value.

**Rejected:** keeping the column as a cache. The numbers are small and the query is trivial;
a cache here buys nothing and can drift, which is exactly the failure being removed.

### 3.4 Checkpoint state vs durable domain state

**V1.** The LangGraph checkpoint is the *only* home for evidence and contradictions. The
bundle route reads them via `checkpoints.get_thread_state`. If checkpoints are pruned — which
is ordinary maintenance for a checkpointer — the evidence behind every historical report is
gone, and bundles for those runs become unbuildable.

**Resolution.** Checkpoints are **execution state only**: node position, retry counters,
in-flight message history. Everything the product asserts is written to domain tables as it
is produced. The rule (C5): *no product claim may be readable only from a checkpoint.*

Checkpoints become safely prunable, which they are not today.

**Rejected:** copying checkpoint state into domain tables lazily at export time. That is V1's
behaviour with extra steps, and it still fails once the checkpoint is gone.

### 3.5 Report-derived claims vs persisted claims

**V1.** Claims do not exist as data. `bundle.assemble` derives them by running a regex over
report prose at export time. M0A found two implementations of that regex that could disagree,
and unified them — but the deeper issue is that a claim is a *product concept* being
reconstructed from formatting.

**Resolution.** Claims are persisted at Revision creation. `extraction_method` records how
each was obtained, and — importantly — the first V2 implementation will honestly record
`DERIVED_FROM_REPORT`, because that is still how they are produced. Persisting them changes
*when* the derivation happens (once, at creation) and makes it *auditable*, without pretending
the synthesizer emits structured claims yet.

Having the synthesizer emit structured claims directly is the natural next step and is
deferred (§10). The schema is ready for it; the pipeline change is not part of M2.

**Rejected:** continuing to derive at read time. It makes claim identity unstable — the same
report can yield different claims as the extractor evolves — which breaks review state,
artifact hashes, and any longitudinal metric.

### 3.6 Session JSON sources vs persisted sources

**V1.** `sessions.sources` is a JSON array, assembled by `graph._number_sources` and written
once. It cannot be queried, joined, or constrained; the same URL across two runs is two
unrelated blobs.

**Resolution.** `Source` becomes a table. `citation_index` is stored per source per run, so
`[n]` remains stable and the numbering logic does not move.

**Rejected:** normalising sources *across* runs (one row per URL globally). Tempting, but the
same URL fetched at two different times is not the same document, and pretending otherwise
would let a later run's title silently rewrite an earlier artifact's citation. §9 forbids
modelling web content as stable.

### 3.7 Checkpoint evidence vs persisted evidence

**V1.** Evidence lives in the checkpoint (see §3.4). It also gets *mutated*:
`verify_evidence_snippets` blanks the snippet in place when verification fails.

**Resolution.** `Evidence` becomes an immutable table, written as gathering proceeds. Failed
verification sets `provenance_state = UNATTESTED` and **retains the text**. The presentation
layer refuses to render an unattested snippet as a quotation; storage keeps it, because the
fabricated text is itself the evidence that something went wrong, and V1 destroys it.

**Rejected:** keeping the blanking behaviour and adding a flag. It is strictly less
informative and makes the failure unauditable after the fact.

### 3.8 Bundle vs ResearchArtifact

**V1.** The `.bundle.json` is assembled on demand from four sources and never stored. Two
exports of the same session can differ if anything underneath changed.

**Resolution.** They are the **same concept**, and the bundle is the right foundation — the
Master Plan §9 says not to invent a second artifact system, and this RFC agrees. What changes:

- The artifact is **persisted at approval**, not assembled at download.
- Download serves stored bytes. Exports become byte-identical and repeatable.
- `bundle_version` / `format_version` stays at 1. **This RFC does not change the format.**

`research_engine/bundle.py` remains the assembler and `verify_bundle.py` remains the
verifier; they gain a caller that stores the result.

**Rejected:** a new artifact format alongside the bundle. Two formats, two verifiers, and the
existing one already carries the properties that matter.

### 3.9 Artifact snapshot vs live database state

**V1.** Everything is live. The bundle route reads the current session row, the current
checkpoint, the current audit rows.

**Resolution.** C4. The artifact payload is a frozen copy. It never joins to live tables at
read time. The live tables remain the working record; the artifact is the published one.

They *will* diverge — a project rename, a re-index, a deleted run — and that is correct.
Divergence is the property that makes an artifact worth handing to someone.

**Rejected:** artifacts as materialised views. A view that changes is not a record.

### 3.10 ProjectMemory eligibility

**V1.** `ingest_session` refuses anything whose status is not `COMPLETED`. This is correct
today and enforced in the right place — but it is a *convention*: `COMPLETED` implies approval
only because the graph happens to route approvals to the finalizer.

**Resolution.** Memory is created **from a ResearchArtifact only**, by foreign key. Approval
is the only thing that creates an artifact, so approval is structurally the only thing that
can create memory. The invariant stops depending on a status value's meaning.

Chat turns, drafts and rejected work remain ineligible, as in V1.

### 3.11 Cancellation state and lifecycle semantics

**V1.** Advisory on both hosts, and racy — see issue #54. Cancellation sets `status = FAILED`,
publishes `FAILED`, and writes a Redis key nothing reads. Outcome writers do not check the
current status, so a run that finishes afterwards overwrites the cancelled state.

**Resolution, at the model level** (the mechanism is #54's, not this RFC's):

- `CANCELLED` is a **distinct terminal status**, not `FAILED` with a message. A run the user
  stopped is not a run that failed, and evals must be able to tell them apart.
- Cancellation state is **durable and on the run** (`cancelled_at`, `cancel_requested_by`),
  not in a TTL'd cache key.
- `CANCELLED` is **terminal and absorbing**: no outcome write may move a run out of it. This
  is the guard that removes the race, independent of whether the run is stopped preemptively
  or cooperatively.
- Cost and tokens spent before the stop are still recorded. Cancellation must not make spend
  vanish.
- A cancelled run **cannot produce an artifact**, and therefore cannot reach memory.

Whether cancellation is preemptive or cooperative is deliberately left to #54; the model
above is correct under either.

### 3.12 ResearchRun vs current Session semantics

**V1.** `sessions` is four things: an execution record, the current draft, the final report,
and the run's metrics.

**Resolution.** Split by lifetime and mutability:

| V1 `sessions` responsibility | V2 home |
|---|---|
| Execution record, config, metrics | ResearchRun |
| Draft / final report text | Revision |
| The approved result | ResearchArtifact |
| Sources JSON | Source |
| Plan JSON | ResearchPlan |
| `rework_count` | derived |

The word "session" retires. It suggested a conversation, which is precisely the framing the
V2 product thesis rejects.

---

## 4. Provenance Model

Three states, from M0A. **Never collapse them.**

| State | Meaning | Produced when |
|---|---|---|
| `ATTESTED` | The snippet was found in text a tool actually returned. | Verification ran and matched. |
| `UNATTESTED` | Verification ran and the snippet was **not** found. | Verification ran and failed. |
| `UNCHECKED` | Verification did not run. Nothing is claimed either way. | Fake/demo mode, or a path with no attestation step. |

**Why the third state is mandatory.** `UNCHECKED` is not a weaker `UNATTESTED`. It is the
absence of a measurement. V1's in-graph check is skipped entirely in fake mode, and V1 has no
way to say so — a demo run's evidence is indistinguishable from verified evidence at the data
level. That is the same defect as a benchmark printing `0.0` for a metric it could not
compute, and AGENTS.md opens by calling that a P0.

**`attested_against` refines `ATTESTED`.** Matching against fetched body text is a stronger
attestation than matching against a search-result snippet, and both are recorded rather than
flattened.

**What attestation does and does not prove.**

- It proves: this text appeared in what the retrieval tool returned for this URL.
- It does **not** prove: the URL is real, the page is honest, the source is authoritative, or
  the snippet supports the claim citing it.

The last of these is `Claim.verification_state`, which is a separate axis. A claim can be
`UNSUPPORTED` while every piece of evidence under it is `ATTESTED`.

**Presentation rule.** `UNATTESTED` and `UNCHECKED` must never render as a verbatim
quotation. `UNCHECKED` must never render as verified. This is V1's ⚠-chip rule, generalised
and given a data model.

---

## 5. Authority Model

One authoritative representation per fact.

| Fact | Authoritative | Derived / cached | Snapshot |
|---|---|---|---|
| The question | `ResearchRun.question` | — | artifact payload |
| Run configuration | `ResearchRun` columns | — | artifact payload |
| What was planned | `ResearchPlan` (versioned) | — | artifact payload |
| What was retrieved | `Source` | — | artifact payload |
| Extracted evidence | `Evidence` | — | artifact payload |
| Whether a snippet is genuine | `Evidence.provenance_state` | ⚠ chips in the UI | artifact payload |
| Report text | `Revision.report_markdown` | — | artifact payload |
| Report integrity | `Revision.report_hash` | — | artifact payload |
| Claims | `Claim` rows | — | artifact payload |
| Claim↔evidence | `ClaimEvidenceLink` | `[n]` markers in prose | artifact payload |
| Conflicts | `Contradiction` | conflict block in prose | artifact payload |
| Human decisions | `Review` | — | artifact payload |
| That an action occurred | `AuditEvent` | — | *not* snapshotted |
| Rework count | **derived** from Revisions | `ResearchRun` list views | artifact payload |
| Citation resolution rate | **derived** from Revision + Sources | `ResearchRun` column | artifact payload |
| Cost / tokens | `ResearchRun` | — | artifact payload |
| Approved result | `ResearchArtifact` | — | — |
| Retrievable memory | `ProjectMemory` | wholly derived from artifact | — |
| Execution position | LangGraph checkpoint | — | *never* snapshotted |

Two rules fall out:

1. **The `[n]` markers in report prose are not authoritative.** They are a rendering of
   `ClaimEvidenceLink`. V1 has this backwards — the markers *are* the data.
2. **The checkpoint is authoritative for nothing the product asserts.** It is authoritative
   only for where execution is.

---

## 6. State Machines

### 6.1 ResearchRun

```
                    ┌──────────────────────── cancel ─────────────────────┐
                    │                                                     ▼
  PENDING ──────► RUNNING ──────► AWAITING_PLAN ──plan approved──► RUNNING ──► AWAITING_REVIEW
     │               │  ▲                                             │              │
     │               │  └───────────── rework requested ──────────────┼──────────────┘
     │               │                                                │
     │               ▼                                                ▼
     └──cancel──► CANCELLED                                       COMPLETED
                     ▲                                                │
                     │                                                │
  (any state) ──► FAILED ◄──── budget / guard breach ─────────────────┘
```

- `AWAITING_PLAN` is skipped when `skip_plan_gate` is set. All three of V1's differing
  defaults for that flag are preserved (AGENTS.md).
- `COMPLETED`, `FAILED`, `CANCELLED` are terminal.
- **`CANCELLED` is absorbing.** No outcome write may leave it. This is the §3.11 guard.
- A rework returns to `RUNNING`, not to a review state, and produces a new Revision.

**Race conditions, stated explicitly.**

| Race | Resolution |
|---|---|
| Cancel lands while the pipeline is mid-node | Run enters `CANCELLED`; the late outcome write is **rejected**, not applied. |
| Cancel lands after the outcome commits | Cancel is refused (`400`), as it is today for terminal states. |
| Two approvals for one revision | The second is refused: a Revision may have at most one `APPROVED` Review. |
| Approval lands while a rework is in flight | Reviews target a `revision_id`, so an approval for a superseded revision is refused rather than silently applied to the newest one. V1 cannot express this — it approves "the session". |
| Artifact creation races a second approval | `run_id` is unique in `ResearchArtifact`; the second insert fails. |

### 6.2 ResearchPlan

```
  PROPOSED ──human edits──► PROPOSED(v+1) ──approved──► APPROVED
     │                                                      │
     └──────────── gate skipped ────────────────────────────┘
                            (auto-approved, origin = MODEL_PROPOSED)
```

Only one plan version per run may be `APPROVED`. Earlier versions become `SUPERSEDED` and are
retained.

### 6.3 Review

```
  (none) ──► APPROVED           terminal, at most one per revision
         ──► REWORK_REQUESTED   creates a new Revision
         ──► REJECTED           terminal for the run
```

A Review is created in its terminal state. There is no draft review, and no edit.

### 6.4 ResearchArtifact

```
  (none) ──approval of revision R──► CREATED ──► (immutable forever)
```

No update transition exists. New research produces a new artifact. Deletion is explicit and
separate from run deletion.

---

## 7. Research Artifact Model

```
  ResearchRun
      │  1..n
      ▼
  Revision ────────────► Review        (0..n reviews per revision,
      │   1..n                          at most one APPROVED)
      │
      │  the APPROVED review of exactly one revision
      ▼
  ResearchArtifact       (0..1 per run — immutable snapshot)
      │
      │  chunked + embedded
      ▼
  ProjectMemory
```

Read as a sentence: **a run produces revisions; a revision is reviewed; an approved review
freezes that revision into an artifact; only an artifact can become memory.**

Each arrow is a boundary that was implicit or absent in V1:

- Run → Revision: V1 overwrites one column, so drafts have no history.
- Revision → Review: V1 reviews "the session", so a decision cannot be tied to a text except
  by after-the-fact hash comparison.
- Review → Artifact: V1 has no artifact object; the bundle is rebuilt on demand.
- Artifact → Memory: V1 gates on a status value that *implies* approval by convention.

**Entity relationship overview**

```
  Project 1─────n ResearchRun 1─────1 ResearchPlan (versioned)
     │                  │
     │                  ├─────n Source 1─────n Evidence
     │                  │                          │
     │                  ├─────n Contradiction ─────┤ (two evidence refs)
     │                  │                          │
     │                  └─────n Revision 1─────n Claim
     │                              │                 │
     │                              │                 └──n ClaimEvidenceLink n──┘
     │                              │
     │                              └─────n Review
     │                                        │
     │                  ResearchArtifact ◄─────┘ (approved review only)
     │                          │
     └─────n ProjectMemory ◄────┘

  AuditEvent — references any subject by (type, id); cascades from nothing
```

---

## 8. V1 → V2 Migration

Four classifications. **C6 governs all of them: never manufacture provenance V1 did not
preserve.**

### Safe to migrate

Present, unambiguous, directly mappable.

| V1 | V2 |
|---|---|
| `projects` | Project |
| `sessions` identity, question, config, metrics, status | ResearchRun |
| `sessions.final_report` / `draft_report` | one Revision |
| `sessions.sources` JSON | Source rows |
| `sessions.plan_json` + `outline_json` | one ResearchPlan version |
| `audit_log` | Review + AuditEvent (§3.1) |
| `memory_chunks` | ProjectMemory, re-pointed once artifacts exist |
| `agent_logs` | unchanged; referenced by artifacts as trace |

### Derivable

Not stored in V1, computable from what is.

| V2 | Derived from | Recorded as |
|---|---|---|
| Claim | `claims.claim_lines(report)` | `extraction_method = DERIVED_FROM_REPORT`, `verification_state = UNCHECKED` |
| ClaimEvidenceLink | `[n]` markers + source list | `origin = CITATION_MARKER`, `stance = SUPPORTS` |
| `rework_count` | `count(revisions) - 1` | derived, not stored |
| `citation_resolution_rate` | Revision + Sources | recomputed |
| ResearchArtifact | existing bundle assembly, for approved runs | `format_version = 1` |

**A caveat stated plainly:** claims derived during migration are derived by *today's*
extractor. Re-deriving later with a changed extractor would produce different claims for the
same report. This is exactly why V2 persists them (§3.5) — migration freezes one derivation,
and that derivation is a fact about the migration, not about the original run.

### Unverifiable

Present but not trustworthy at the fidelity V2 wants. Migrate the data; **do not migrate a
claim about it**.

| V1 data | Why unverifiable | V2 treatment |
|---|---|---|
| Evidence snippets | V1 blanks failed ones in place; the check is skipped entirely in fake mode; no per-item record of whether it ran | `provenance_state = UNCHECKED`, `attested_against = null`. **Never `ATTESTED`.** |
| A blanked snippet | Empty text could mean fabricated, or absent, or never populated | `UNCHECKED` with empty text; no inference |
| Source `retrieval_status` | Never recorded | `UNKNOWN` |
| Plan `origin` | V1 overwrites the proposal with the approved plan | `UNKNOWN` — we cannot tell a model proposal from a human edit |
| Contradiction `detection_state` | Detector-unavailable and none-found are indistinguishable | `NOT_RUN` unless pairs exist |
| Plan-gate `draft_hash` | Hashes a JSON serialisation nothing has ever verified | migrated as an opaque value, not treated as verified |

The evidence row is the important one. It would be easy, and wrong, to migrate a non-blank
V1 snippet as `ATTESTED` — the text is there, verification usually ran, it looks fine. But
"usually ran" is not "ran for this item", and marking it attested would put a verification
claim into the record that nobody made. `UNCHECKED` is the truthful state.

### Not migrated

| V1 | Why |
|---|---|
| Superseded draft reports | Overwritten in place; genuinely gone. A V1 run yields one Revision, not `rework_count + 1`. |
| Checkpoint evidence for pruned threads | Unrecoverable |
| Redis cancellation keys | Write-only, TTL'd, never read (#54) |
| `sessions.rework_count` as a stored value | Becomes derived (§3.3); kept transiently to reconcile, then dropped |
| Chat messages | Out of scope for this RFC; unchanged |

### Strategy, compatibility, rollback

**Strategy — additive, in four phases.** No V1 table is dropped in M2.

1. Create V2 tables alongside V1's. Nothing reads them.
2. Dual-write: new runs populate both. V1 remains authoritative and serves all reads.
3. Backfill historical runs with the classifications above. Verify: for every approved run, a
   bundle built from V2 tables must be **byte-identical** to one built from V1 — the same
   golden-diff technique that proved M0A behaviour-preserving.
4. Flip reads to V2. Only then deprecate V1 columns, in a later milestone.

**Backward compatibility.** `bundle_version` / `format_version` stays at 1 — existing bundles
verify unchanged, and `verify_bundle.py` is untouched. The API contract is unchanged in M2;
`test_host_parity.py` continues to pass throughout.

**Rollback.** Phases 1–3 are additive and reversible by ignoring the new tables; V1 stays
authoritative and correct. Phase 4 is the first irreversible step and needs its own gate: the
byte-identical bundle check across all historical approved runs must pass before it, and the
V1 columns stay in place for at least one release after, so a revert is a config change and
not a restore.

---

## 9. What V2 does NOT model

Named explicitly to prevent them arriving by increment.

- **A universal knowledge graph.** Claims and evidence are scoped to a run and a project.
  There is no cross-project entity resolution, no global claim identity, no ontology.
- **Epistemic scoring.** No truth values, no belief propagation, no Bayesian updating.
- **Fabricated confidence numbers.** No `confidence: 0.87`. `Claim.verification_state` is four
  discrete, defined values. A number implies a methodology; the Master Plan §12 requires that
  methodology to exist before the number does.
- **Universal source-quality scores.** No domain authority ranking, no journal impact
  weighting. `Source.kind` and `retrieval_status` are facts about retrieval, not judgements
  about worth.
- **Deterministic web replay.** Sources are not re-fetched to reproduce a run. The artifact
  preserves what was retrieved *then*. Reproducible ≠ re-runnable ≠ reconstructable (Master
  Plan §10), and only the first and third are offered.
- **A plugin framework.** Providers stay small interfaces with real implementations behind
  them. Abstract on the second real implementation, not before.
- **Unrestricted agent memory.** Memory comes from artifacts only. There is no ambient
  scratchpad an agent can write to and later read as fact.
- **Cross-user or cross-project sharing.** The ownership boundary is a hard edge in V2. Any
  sharing feature is a separate design with its own threat model.

---

## 10. Alternatives considered

**Keep evidence in the checkpoint; snapshot it into the artifact at approval.**
Cheaper — no evidence table, no dual-write. Rejected: unapproved runs would have no
inspectable evidence at all, which defeats the review experience the product is built around,
and it keeps checkpoints unprunable.

**Make Revision mutable and keep a separate diff log.**
Fewer rows. Rejected: the approved text must be recoverable byte-for-byte forever (C3), and a
mutable row plus a diff log is a reconstruction, not a record.

**One `documents` table for Source and corpus documents.**
They overlap. Rejected: a corpus document is a user-owned file with a lifecycle of its own; a
Source is an immutable record of one retrieval during one run. Merging them means a deleted
upload can invalidate a historical artifact.

**Model claims as a graph with typed edges between claims.**
Expressive. Rejected as premature (§9). The Master Plan §6 is explicit: get claim↔evidence
right before any claim↔claim machinery.

**Derive artifacts on read, and cache.**
Closest to V1. Rejected: a cache can be invalidated, and an artifact that can change is not an
artifact (C4, §3.9).

**Keep `sessions` and add columns.**
Least migration work. Rejected: it preserves the four-jobs-one-row problem (§3.12), which is
the root of most of what M0/M1 found.

**Reuse `FAILED` for cancellation with a flag.**
Smallest change. Rejected: evals and the UI both need to distinguish a run that broke from one
a human stopped, and a flag on a status is a status.

---

## 11. Deferred decisions

Left open deliberately. Each needs evidence this RFC does not have.

1. **Whether the synthesizer emits structured claims directly.** The schema supports it
   (`extraction_method = MODEL_STRUCTURED`). Whether it improves quality is an empirical
   question for the eval harness.
2. **Human editing of claims and reports.** `HUMAN_EDITED` exists in the enums; the workflow,
   and what it does to `report_hash` and artifact integrity, is unresolved.
3. **Preemptive vs cooperative cancellation.** Issue #54. The model here is correct either way.
4. **Contradiction `dimension` classification.** Whether a model can assign these reliably is
   unmeasured. `UNCLASSIFIED` is the honest default until it is.
5. **Cross-run source identity.** Whether the same URL in two runs should ever be linked.
   Deliberately not modelled now (§3.6).
6. **Artifact storage medium.** Database column vs object storage. An implementation
   decision, not a domain one.
7. **Artifact retention and deletion policy.** Artifacts outlive runs; how long, and who may
   delete one, is a product decision.
8. **Whether `ProjectMemory` should carry claim-level granularity** rather than text chunks.
9. **Multi-user projects.** The ownership boundary is single-owner. Collaboration is a
   separate design.
10. **Evidence deduplication within a run.** Identical snippets from one source are currently
    separate rows. Whether to collapse them affects citation numbering.

---

## 12. M2A acceptance criteria

A reviewer should be able to answer each of these from this document.

| Question | Answer | §|
|---|---|---|
| What is a research run? | One execution of research against one question. An execution record — not the result. | 2.2, 3.12 |
| What is evidence? | An immutable verbatim snippet extracted from a Source, with a provenance state. | 2.5 |
| What is a claim? | One persisted assertion belonging to a Revision, linked to evidence with a stance. | 2.6, 2.7 |
| What makes evidence verified? | It was found in text a tool actually returned → `ATTESTED`. Not found → `UNATTESTED`. Not checked → `UNCHECKED`. Never collapsed. | 4 |
| What is authoritative? | One representation per fact; the table in §5 names each. Checkpoints are authoritative for nothing the product asserts. | 5 |
| What gets persisted? | Plan, sources, evidence, revisions, claims, links, contradictions, reviews, artifacts, memory. Not just a report and a JSON blob. | 2, 3.4 |
| What is immutable? | Evidence, Source, Claim, ClaimEvidenceLink, Revision text, Review, AuditEvent, ResearchArtifact. | 2 |
| What is reviewed? | A specific Revision, identified by id and hash — not "the session". | 2.10, 3.2 |
| What exactly is approved? | The exact bytes of `Revision.report_markdown`, recorded in `Review.reviewed_hash`. | 2.9, 2.10, C3 |
| What is an artifact? | An immutable, self-contained, hash-verifiable snapshot created by an approving review. Format version 1 — the existing bundle. | 2.11, 3.8, 3.9 |
| What can become memory? | Only a ResearchArtifact, enforced by foreign key rather than by convention. | 2.13, 3.10 |
| How does V1 migrate? | Additively, in four phases, with data classified safe / derivable / unverifiable / not migrated. Provenance is never manufactured. | 8 |
| How does cancellation work? | `CANCELLED` is a distinct, durable, absorbing terminal state. No outcome write may leave it. A cancelled run produces no artifact and no memory. | 3.11, 6.1 |
| Where is audit history kept? | Split: `Review` holds the decision, `AuditEvent` holds the accountability record. Neither cascades away. | 3.1, 2.10, 2.12 |

---

## 13. Amendment 1 — resolutions requested at M2A review

Raised at review, resolved here. §§1–12 stand as written; where this amendment sharpens a
definition it says so, and §13.7 lists exactly which earlier statements are affected.

---

### 13.1 Revision semantics

**A Revision is a report version — not a research-state snapshot.**

The distinction matters because the two options put evidence in different places. A
research-state snapshot would freeze sources and evidence per revision, duplicating them on
every rework loop. A report version owns only what actually changes when the synthesizer
runs again.

What actually changes is settled by the pipeline: `graph.route_after_gate` sends a rejected
draft back to the **synthesizer**, not the executor. A rework re-writes the report from the
*same* evidence with the reviewer's feedback attached. Evidence and Sources are therefore
stable across the revisions of a run, and belong to the Run.

| Belongs to | Entities |
|---|---|
| **ResearchRun** | ResearchPlan, Source, Evidence, Contradiction |
| **Revision** | `report_markdown`, Claim, ClaimEvidenceLink |
| **Neither (points at a Revision)** | Review, ResearchArtifact |

**Immutable within a Revision:** `id`, `run_id`, `version`, `created_at`,
`report_markdown`, `report_hash`, `evidence_watermark`, and the full set of Claims and
ClaimEvidenceLinks belonging to it.
**Mutable:** `state`, `superseded_by_id` only.

**`evidence_watermark`.** A Revision records the last Evidence sequence visible when it was
synthesized. Evidence is append-only within a run and never deleted, so "all evidence with
sequence ≤ watermark" reconstructs exactly what the synthesizer saw. Today every revision of
a run shares the same watermark, because rework does not gather. The field exists so that
"request more evidence for a topic" — a review action the Master Plan §8 Phase G anticipates
and this RFC defers — becomes representable without a schema change, and so that a reader can
always tell which evidence a given draft was written against.

*Alternative rejected:* a `revision_evidence` join table. Exact, but redundant while evidence
is append-only, and it invites the belief that a revision can *exclude* evidence that exists.
If evidence ever stops being append-only, the join table becomes correct and the watermark
does not — recorded here so the trade is visible.

---

### 13.2 Review target

**There is exactly one approval decision in the system**, and adding a second is the failure
this section exists to prevent.

| Level | Object | Carries approval authority? |
|---|---|---|
| **Claim annotation** | a `Claim` (one revision's claim) | **No.** Advisory input to the reviewer. |
| **Revision review** | a `Revision` | **Yes — this is the only approval.** |
| **Artifact approval** | — | **Does not exist.** |

**Revision review is the approval.** A `Review` with `gate = REPORT` and
`decision = APPROVED` targets exactly one Revision by id and pins its `reviewed_hash`. At
most one approving Review may exist per Revision, and at most one per run.

**Claim-level review is annotation.** A reviewer marking a claim unsupported, or leaving a
comment on it, records a `ClaimAnnotation` — a note attached to a specific `Claim`. It never
approves or rejects anything; it exists so a reviewer can express *why* they are about to
approve or request rework, and so a rework prompt can carry specifics. Annotations are inputs
to the single decision, not decisions.

**Artifact approval does not exist.** The artifact is *created by* the approving Review. It is
an output of approval, never a subject of it. A separate "approve this artifact" step would be
a second approval system with its own state, and the two could disagree about the same
research — which is precisely the redundancy to avoid.

**The plan gate is not a second approval of the report.** `gate = PLAN` reviews a
`ResearchPlan` version. Different object, different decision, different point in the run. Both
live in `Review` because both are "a human decided something about a specific versioned
object", and `gate` plus the nullable `plan_version_id` keeps them unambiguous (§3.2).

So: **one approval, one artifact, one memory-eligibility gate**, and annotations that inform
the decision without competing with it.

---

### 13.3 Claim identity across revisions

Three options were considered: a new claim per revision; stable identity across revisions; or
stable logical identity with versioned representation.

**Resolution: a new Claim per Revision now, with logical identity reserved and unused.**

`Claim` rows are per-revision and immutable, as §2.6 states. A nullable `lineage_id` is
reserved on the entity and is **NULL in every row V2 initially writes**.

The reason is C6 applied to identity. Claims are currently `DERIVED_FROM_REPORT` — extracted
from prose by `claims.claim_lines`. Nothing in that process observes that a sentence in
revision 2 *is* the same assertion as a sentence in revision 1. Assigning lineage by fuzzy
text matching would manufacture a relationship the system never observed, which is the same
error as marking migrated evidence `ATTESTED` because it looks fine. When the synthesizer
emits structured claims (§11.1) it can emit stable lineage ids, and `lineage_id` starts being
populated **from that point forward**. It is never backfilled by matching.

**Implications, stated plainly:**

| Concern | Consequence |
|---|---|
| **Evidence links** | `ClaimEvidenceLink` points at a per-revision Claim, so links are rebuilt for each revision. Cheap: Evidence is stable at the Run level, so only the linking is redone, not the gathering. |
| **History** | Each revision has its own complete claim set. Nothing is lost. |
| **Diffs** | A revision-to-revision diff is **textual**, and must be presented as textual. The system cannot assert "claim 3 is unchanged" as a fact, and the UI must not imply it can. |
| **Review** | A `ClaimAnnotation` attaches to one revision's Claim and **does not carry forward** to the next revision. A reviewer's note on revision 2 is not automatically attached to revision 3. This is a real UX cost, accepted knowingly: carrying annotations forward requires exactly the claim identity we cannot honestly establish. |
| **Artifact generation** | Unaffected. An artifact snapshots one revision's claims; no lineage is needed. |

*Alternative rejected:* stable identity assigned by text similarity. It would make diffs and
annotation-carry-forward work immediately, and it would be wrong at an unknown rate, silently.
A wrong claim lineage is worse than no lineage: it attributes a reviewer's judgement to a
sentence they never read.

---

### 13.4 Artifact hash boundary

**Starting point: V1's bundle integrity model, unchanged.** `research_engine/bundle.py`
already implements this and `verify_bundle.py` already checks it. V2 persists the result
instead of recomputing it; the algorithm does not change and `format_version` stays 1.

**Canonicalization.** Exactly V1's `compute_bundle_hash`:

1. Serialise the payload to JSON.
2. Set the hash field to the **empty string** — blanked, not removed, so the key is present
   and the shape is stable.
3. `sort_keys=True`, `ensure_ascii=False`, `separators=(",", ":")`.
4. `sha256` of the UTF-8 encoding.

**Covered by `artifact_hash`:** every field of the payload. Question, run configuration, plan,
sources, evidence records with their per-snippet `content_hash`, claims, claim↔evidence links,
contradictions, the report, `report_hash`, the review chain, model routing, cost, token counts,
timings, `demo`, the trace and `trace_available`.

V1's rule that the hash covers the trace *and* `trace_available` is kept deliberately:
stripping a trace from an artifact that had one breaks the hash, which is correct, and an
absent trace is a truthful state the hash should cover rather than a hole in it.

**Excluded from `artifact_hash`:**

| Excluded | Why |
|---|---|
| `artifact_hash` itself | It cannot cover itself. |
| Storage bookkeeping — the artifact row's surrogate `id`, storage location, retention flags, download counters | Operational metadata, deliberately **outside the payload**. The payload is closed: it contains research facts, not the database's notes about where it put them. |

**The payload is closed.** This is the operative rule for "does artifact identity change if
metadata changes?" — **research metadata is inside the payload and does change the hash;
operational metadata is outside it and cannot.** If a field's value is part of what a third
party is being asked to trust, it belongs inside and is covered. If it is an artefact of this
deployment's storage, it belongs outside. There is no third category, and nothing may be added
to the payload that is not a research fact.

**Relationship to `report_hash`.** `report_hash` is inside the payload and therefore covered
by `artifact_hash`, and it *also* stands alone: a verifier can check the report text
independently without recomputing the whole payload, and can localise a failure to the report
rather than reporting a generic mismatch. The redundancy is the point.

**Relationship to per-evidence `content_hash`.** Identical reasoning one level down. Each
`sha256(snippet)` is inside the payload and covered, and independently checkable, so tampering
with one snippet is reported as *that snippet* rather than as a whole-artifact failure. V1's
verifier already does this and names the offending record.

**Relationship to approval.** Unchanged from V1 and load-bearing:
`Review.reviewed_hash == report_hash` for the approving review. That equality is what proves
the human approved *this* text. `Revision.report_markdown` being immutable (§13.1) is what
makes the equality permanent rather than a coincidence that survived until the next rework.

**One V1 wrinkle this fixes.** V1 assembles bundles on demand and stamps `created_at` into
each one, so two downloads of the same session produce two different `bundle_hash` values.
Nothing was wrong with either, but the artifact had no stable identity. Storing the artifact
once, at approval, gives it one: the same approved research has exactly one `artifact_hash`,
forever.

---

### 13.5 Memory provenance

**The invariant, unchanged and non-negotiable:**

> Every durable memory item must carry explicit provenance to approved
> ResearchArtifact(s).

**Cardinality is deliberately not fixed.** §2.13 named a single `artifact_id` foreign key;
this amendment replaces that with a **provenance relationship** capable of many, because the
justification for one-per-item is "that is what today's chunker does", which is a statement
about the current implementation and not about the domain.

Today every memory item derives from exactly one artifact — `chunk_report` splits one report.
Modelling provenance as a relationship rather than a column means a future synthesis across
several artifacts does not require a schema break or, worse, a nullable second column bolted
on later. The relationship is one-to-many *in the model* and one-to-one *in practice* until
something justifies otherwise.

**What may become memory:**

| Source | Allowed | Reason |
|---|---|---|
| One approved ResearchArtifact | **Yes** — this is today's only path | Approval is the trust boundary |
| Multiple approved ResearchArtifacts | **Permitted by the model, not implemented** | Cross-artifact synthesis is plausible; the model should not preclude it |
| A Revision | **No** | A revision may never have been approved, and an approved one already has an artifact |
| A rejected or unapproved run | **No, never** | The approval gate exists precisely to keep this out |
| Chat turns, agent scratch, tool output | **No** | §9, "unrestricted agent memory" |

**Default: approved-artifact provenance only.** Any future source requires its own amendment
and its own argument. The structural enforcement from §3.10 stands — memory provenance
resolves to artifacts, and only approval creates an artifact — so the invariant survives
without depending on a status value's meaning.

---

### 13.6 Run, Revision, Artifact — the distinction

| | **ResearchRun** | **Revision** | **ResearchArtifact** |
|---|---|---|---|
| **Is** | An execution | A draft of the report | The published, approved record |
| **Answers** | "What happened?" | "What did it say, this time round?" | "What may I rely on?" |
| **Cardinality** | 1 per question asked | 1..n per run | 0..1 per run |
| **Created by** | Starting research | The synthesizer | An approving Review |
| **Mutable?** | Yes — status, metrics | Text immutable; state mutable | **Never** |
| **Owns** | Plan, Sources, Evidence, Contradictions | `report_markdown`, Claims, Links | A frozen copy of all of it |
| **References live data?** | n/a | Yes | **No** — self-contained (C4) |
| **Deleted with the project?** | Yes | Yes | **No** |
| **Can become memory?** | No | No | **Yes — only this** |
| **Hashed?** | No | `report_hash` | `artifact_hash` over the whole payload |
| **V1 counterpart** | `sessions` (execution part) | `sessions.draft_report` (overwritten) | `.bundle.json` (assembled on demand) |

Read down the last two columns: V1's failure was that the middle one was a single overwritten
column and the right one did not exist as an object at all.

---

### 13.7 Effect on §§1–12

Amendment 1 is additive except where noted.

| Section | Change |
|---|---|
| §1 | **C7 added** — the report is a rendering, never a source of truth. |
| §2.6 Claim | `lineage_id` reserved, NULL in every row V2 initially writes (§13.3). |
| §2.9 Revision | `evidence_watermark` added; ownership boundary made explicit (§13.1). |
| §2.10 Review | Unchanged. §13.2 clarifies that it is the *only* approval and adds `ClaimAnnotation` as a non-approving annotation. |
| §2.11 ResearchArtifact | Unchanged. §13.4 specifies the hash boundary precisely. |
| §2.13 ProjectMemory | **Amended** — the single `artifact_id` foreign key becomes a provenance relationship of undetermined cardinality (§13.5). The eligibility invariant is unchanged. |
| §3.10 | Unchanged in substance; enforcement is now "provenance resolves to artifacts" rather than "one FK to one artifact". |
| §5 Authority Model | C7 makes explicit what the table already implied: report prose is a projection, authoritative for nothing. |
| §11 Deferred | §11.1 (structured claims) now additionally gates `lineage_id` becoming populated. §11.8 (claim-level memory granularity) is unaffected. |

Nothing in §§4, 6, 7, 8, 9, 10, 12 changes.

---

---

## 14. Out of scope for M2A

No migrations, no tables, no production code, no API change, no frontend change, no LangGraph
change, no `bundle_version` change, no `METRICS_VERSION` change, no service refactor. This
document is the input to M2B, which should be a **schema** proposal — DDL and migration
ordering — reviewed on its own before anything is created.
