# V1 → V2 Audit and Migration Map

**Status:** Phase 0 deliverable (V2 Master Plan §33). No code changed to produce it.
**Method:** read the repository, not the documentation. Every claim below cites a file and,
where it is a defect, was confirmed by grep or by reading the call path end to end.
**Scope:** 453 tracked files, ~43.5k lines of Python/TypeScript/Rust, 477 backend tests,
16 frontend test files, 2 Playwright specs, 4 GitHub workflows.

Filed in `internal/` rather than `docs/plans/` deliberately: `NEVER_PUBLISH` in
`frontend/lib/docs.ts` is a **per-file** denylist, not a per-directory one, so a new
document under `docs/plans/` is published to the site at a URL nothing links to. See
finding **W-3**.

---

# Part 1 — The audit

## 1. Current architecture

Four deployment targets share one engine.

```
                        ┌───────────────────────────────────────┐
                        │  research_engine/  (host-independent) │
                        │  graph · runner · tools · retrievers  │
                        │  corpus · embeddings · bundle · cli   │
                        │  ports: EventSink, Cache, Embeddings, │
                        │         Corpus                        │
                        └───────────────────────────────────────┘
                           ▲          ▲           ▲          ▲
              ┌────────────┘          │           │          └────────────┐
              │                       │           │                       │
    ┌─────────────────┐   ┌───────────────────┐  ┌──────────┐   ┌──────────────────┐
    │ app/ (FastAPI)  │   │ desktop/sidecar.py│  │ evals/   │   │ research_engine  │
    │ + Celery worker │   │ (1,947 lines)     │  │ harness  │   │ /cli.py          │
    │ Postgres+Redis  │   │ SQLite + keychain │  │ benchmark│   │                  │
    └─────────────────┘   └───────────────────┘  └──────────┘   └──────────────────┘
```

The engine boundary is real and **enforced by a test** (`tests/test_engine_boundary.py`
walks the AST of every engine module and fails on any `app.*` import; `KNOWN_EXCEPTIONS`
is empty). This is the single best structural decision in V1 and it must survive V2
untouched.

The pipeline is a compiled LangGraph `StateGraph` with two `interrupt()` gates on one
thread (`research_engine/graph.py:1268`):

```
START → planner ─┬─→ plan_gate ─→ executor ⇄ critic ─→ contradiction_detector
                 └─→ executor        ▲   (retries remain)
                                     └── round loop, capped at max_critic_loops
     → synthesizer → hitl_gate ─┬─→ finalizer → END
                                └─→ synthesizer (rework)
     any budget/time breach → failer → END
```

**Stack:** FastAPI + Celery + Postgres 16 (pgvector) + Redis 7; Next.js 16 App Router,
Tailwind v4, TanStack Query; Tauri 2 shell wrapping a PyInstaller sidecar.

## 2. Current product surfaces

| Surface | Where | State |
|---|---|---|
| Web app (authenticated) | `frontend/app/(app)/` | Working, exercised by CI E2E |
| Public site | `frontend/app/(site)/` → GitHub Pages | Working, 5 pages |
| Desktop app | `desktop/` + `backend/desktop/sidecar.py` | Working, **feature-divergent** |
| CLI | `research_engine/cli.py` (222 lines) | Working, undocumented on the site |
| Eval harness / benchmark | `backend/evals/` | Working, honest, under-run |
| Offline verifier | `research_engine/verify_bundle.py` | Working, **unreachable from any UI** |

## 3. Current UI structure

App navigation (`components/SideNav.tsx`) is already **project-first**, which the V2 plan
assumes it is not:

```
[Workspace: ProjectSwitcher]
[+ New Research]  → /dashboard
Overview          → /project      (runs · corpus · memory · routing)
Corpus            → /corpus
History           → /history      (filters: status, depth, citation band, model)
Chat              → /chat         (web only — desktop hides it)
[AccountMenu]     → /profile, /settings/[section]
```

Session view (`components/session/`) switches on status: `PlanGate` → `LiveFeed` +
`PipelineRail` → `ApprovalGate` → `ReportView` (+ `ChatPanel`) / `FailedState`.

**What is genuinely good:** the design gate (`PlanGate.tsx`, 338 lines) is a real editing
surface — drop a task, reword a query, pick an outline — and it is the strongest existing
expression of the V2 thesis. History's citation-rate bands treat `null` as its own band
rather than folding it into "low". `EmptyState` is a shared component and the project page
states each panel's emptiness separately.

**What is missing entirely:** there is no Evidence surface, no Claims surface, no
Artifacts surface, and no contradiction surface. `lib/types.ts` (422 lines) has no
`Claim`, `Evidence`, `Contradiction`, or `Artifact` type at all.

## 4. Current website structure

`frontend/app/(site)/` builds to GitHub Pages via a third build target
(`NEXT_PUBLIC_PAGES`, `basePath` set, `.nojekyll`, split build/deploy jobs).

```
/           landing — "Cited research you can actually verify"
/why        comparison table, generated from lib/comparison.ts (307 lines)
/docs       generated from docs/ at build time via lib/docs.ts
/releases   hand-written lib/releases.ts
/download   hand-written, reads latestRelease()
```

The **generated** pages (`/docs`, `/why`) cannot drift. The **hand-written** data
(`lib/releases.ts`, the README badge, the README pipeline diagram) can and has. There is
no Tutorials section, no Roadmap page on the site (the roadmap is a doc), no Changelog
page (same), no Community/Contributing page, and no Trust page.

## 5. Existing domain models

This is the central finding of the audit.

**Persisted (Postgres, 16 Alembic migrations):**

`users`, `refresh_tokens`, `projects`, `sessions`, `agent_logs`, `audit_logs`,
`chat_threads`, `chat_messages`, `memory_chunks`.

**Not persisted anywhere as a domain object:**

| V2 entity | Where it actually lives today |
|---|---|
| `Source` | A **JSON blob** on `sessions.sources`. No table, no id, no dedup, no reuse across runs. |
| `Evidence` | **LangGraph checkpoint tables only.** No FK to `sessions`, no schema we own, no query path. Read back by `checkpoints.get_thread_state()` — a full graph rebuild — solely to assemble a bundle. |
| `Claim` | **Derived by regex at export time** (`bundle.py` → `evals.metrics.claim_lines`). Never stored. Two runs of the same regex on the same report are the only thing that makes a claim identity. |
| `ClaimEvidenceLink` | The integer inside `[n]`. That is the entire linkage. |
| `Contradiction` | Checkpoint state + a **rendered Markdown block** inside the report string. |
| `Review` | `audit_logs` rows (`approved` / `rework_requested` / `plan_approved` + `draft_hash`). This one is genuinely good. |
| `ResearchArtifact` | Assembled on demand by `research_engine/bundle.py`. **Never stored.** |
| `ProjectMemory` | `memory_chunks` with pgvector. Correctly approval-gated. |

**Consequence:** the product's own thesis objects are the ones with no schema. Evidence
integrity depends on LangGraph's checkpoint tables surviving — a Postgres restore that
misses them, or a future checkpoint-pruning policy, silently destroys the ability to
produce or verify an artifact for every historical run. Nothing warns.

## 6. Existing research workflow

Question → planner → **design gate** (`AWAITING_PLAN`) → executor ⇄ critic rounds →
contradiction detector → synthesizer (draft → citation-repair pass → citation-fidelity
pass → conflict block) → **review gate** (`AWAITING_APPROVAL`) → finalizer → COMPLETED →
memory ingestion.

Both gates are durable `interrupt()` checkpoints; the worker exits and a resume continues
rather than re-running. `runner.resume()` requires exactly one of `approved=` or `plan=`
and raises on both/neither — a deliberate refusal to have a default. This is correct and
should be preserved verbatim.

`skip_plan_gate` has three intentionally disagreeing defaults (`RunConfig` True,
`ResearchStartRequest` True, `Session` column False) documented at each site. Confusing,
but each is right for its population. Leave it; document it once in V2.

## 7. Evidence / citation pipeline

The pipeline, and where each link is strong or weak:

```
web_search / read_webpage
        ↓  record_tool_output()            ← STRONG: the only record of what tools returned
   seen_text{url → text}
        ↓  submit_evidence (model-authored: url, title, snippet, key_fact)
        ↓  verify_evidence_snippets()      ← STRONG: normalised containment check
   snippet blanked if not found            ← WEAK: signal destroyed, not recorded
        ↓  _number_sources()               ← empty snippets skipped
   sources[] JSON on the session
        ↓  synthesizer (shown snippet ONLY, never key_fact)  ← STRONG, deliberate
   draft
        ↓  citation-repair pass
        ↓  _verify_citation_fidelity()     ← STRONG: deterministic number-grounding +
                                              deictic/label stripping + LLM verifier
   markers stripped, "(citation could not be verified)" note
        ↓  citation_rate.resolution_rate() ← STRONG: returns None, never 0, when unmeasured
   sessions.citation_resolution_rate
```

**E-1 (P0). The fabrication signal is destroyed rather than recorded.**
`graph.py:329` sets `chunk["snippet_unverified"] = True` on a chunk whose quote was not
found in fetched text. That key is **not on the `EvidenceChunk` schema** and is read
**nowhere** outside `tests/test_evidence_snippet_verification.py` — confirmed by grep
across `backend/` and `frontend/`. The snippet is blanked, so downstream:

- `_number_sources` skips it → `Source.snippet=""`, `snippets=[]`
- the bundle records `SnippetRecord(snippet="", content_hash=sha256(b""))`
- `verify_bundle._check_evidence_integrity` passes it
- the UI shows a source with no quote

A source whose quote we **caught being fabricated** is now indistinguishable from a source
that simply contributed no quote. That is the unmeasured-vs-zero failure applied to
provenance — in the one place the product exists to get right.

**E-2 (P1). Provenance verification does not run where CI runs.**
`graph.py:492` gates `verify_evidence_snippets` on `llm_mode != "fake"`, documented
honestly as a limitation: scripted fakes submit evidence without calling a tool, so every
fixture snippet would blank. The result is that the product's most important guard has
**no regression coverage in CI**. The unit test covers the function; nothing covers its
wiring.

**E-3 (P2). Model-authored URL and title are never validated.**
`record_tool_output` keys on URL, so a snippet is checked against *the text at the URL the
model claimed*. If the model invents a plausible URL it never fetched, `seen` has no entry,
`haystack` is `""`, and the snippet blanks — correct outcome, wrong reason, and no record
that the *source itself* was unattested. `source_title` is never checked at all.

## 8. Existing artifact / bundle implementation

`research_engine/bundle.py` (255 lines) is the closest thing V1 has to a `ResearchArtifact`
and it is a **valid foundation** — do not replace it.

It carries: manifest version, session id, query, depth, `demo` flag, report + report hash,
claims with citation indices, evidence with per-snippet SHA-256, sources, contradictions,
model routing, cost/tokens/elapsed, the full approval chain with per-decision draft hashes,
the agent trace, `trace_available` (three states, not two), and a `bundle_hash` covering
every field except itself.

`verify_bundle.py` (325 lines) checks six things offline with no AI and no network: bundle
hash, report hash, evidence hashes, citation resolution, claim↔evidence linkage, approval
chain. It prints the `demo` flag above the verdict so a PASS on scripted output cannot be
misread.

**A-1 (P0). The artifact is unreachable from the product.**
`GET /research/{id}/export.bundle.json` exists on the server. Confirmed by grep:

- `components/session/ReportView.tsx` offers **`md` and `pdf` only** (`useState<null | "md" | "pdf">`); there is no bundle button, link, or fetch anywhere in `frontend/`.
- The desktop sidecar has **no bundle route at all** (its export surface is `export.md` and an `export.pdf` that returns 501).
- `README.md:25` describes exports as "`.md` / `.pdf`" and omits the bundle.

Meanwhile the landing page ("The part nobody else has"), the login page, the settings copy
and `lib/comparison.ts` all sell it. **The single strongest differentiator ships as an
undocumented API endpoint.**

**A-2 (P1). Artifacts are ephemeral and recomputed.** Nothing is stored. Exporting the
same session twice re-derives claims by regex and re-reads the checkpoint. There is no
artifact id, no version, no immutability, and no way to hand someone "artifact #3 of this
project".

## 9. Existing project memory

`app/services/memory.py` is well-built and needs the least work of any subsystem.

- Ingestion is approval-gated at two levels: only `_persist_outcome`'s COMPLETED branch calls it, and `ingest_session` re-checks `status != COMPLETED` because "it is the property the whole feature rests on".
- Isolation is a SQL predicate (`WHERE project_id`), explicitly *not* a prompt instruction.
- Retrieval filters on `embedding_model` — vectors from different models are never mixed.
- Idempotent, with `force=` for a provider switch; replaces wholesale to avoid orphan tails.
- `MemoryStatus` derives `pending_reports` rather than storing it, and reports `stale_models`, so a failed ingest is visible and self-heals.
- Ingestion never fails a completed run (documented, deliberate).

**M-1 (P2).** `MAX_COSINE_DISTANCE = 1.0` is explicitly a placeholder pending measurement —
correctly refused as an invented number. V2 should measure it, not guess it.
**M-2 (P2).** Project memory is Postgres/pgvector-only, so the desktop build has no
cross-report memory. Documented as a known gap in `lib/releases.ts` for v1.0.0.

## 10. Existing provider architecture

Four ports (`research_engine/ports.py`): `EventSink`, `Cache`, `Embeddings`, `Corpus`. The
module documents the two candidates it **rejected** (`KeyProvider`, `RunLock`) with reasons
— exactly the "abstract when a second implementation exists" discipline the Constitution
§6 asks for. This is model work.

Routing is `"provider:model"` split on the first colon. `catalog.py` (376 lines) is the
declared fact source for pricing, context windows, and capability flags;
`validate_pricing()` runs at startup. Five roles: planner, executor, critic, synthesizer,
chat. Per-run routing is a `ContextVar` override, so concurrent runs in one worker stay
isolated — and the same mechanism carries per-user BYOK keys.

**P-1 (P1). Route validation has two homes.** `app/services/model_routing.py::validate`
and `research_engine/llm_factory.py::validate_pricing`. AGENTS.md records that these
disagreed once (routing accepted what pricing refused).
**P-2 (P1). `MAX_COST_PER_SESSION_USD` is inert on `openrouter` and `custom`** because
`validate_pricing` skips them and `estimate_cost` returns `0.0`. Documented in three
places, which is the right response to a limitation that cannot be fixed without a price
feed — but it means a `$0.00` in the UI is not a claim that a run was free.
**P-3 (P2).** Search providers (Tavily → Brave → DuckDuckGo) are a hardcoded chain in
`retrievers.py`, not a port. Correct today by the "second implementation" rule — three
implementations of one contract already exist, so this is the *next* port to extract, not
a speculative one.

## 11. Existing deployment modes

| Mode | Entry | Verified by |
|---|---|---|
| Docker Compose (full) | `./start.sh`, `docker-compose.full.yml` | CI E2E runs the same services natively |
| Native dev | `Makefile` (21 targets) | Documented, not CI-verified |
| Single-host production | `deploy/` — Caddyfile, Oracle Cloud bootstrap, pg_dump backup | Not CI-verified |
| Desktop | `.github/workflows/desktop.yml` — sidecar job → shell job → release | Smoke-tested (handshake, token gate, watchdog); **not launched** |
| GHCR images | `release.yml` — multi-arch amd64+arm64, digest-then-manifest, verifies both arches present | CI-verified |
| Pages | `pages.yml` — split build/deploy, empty-export check, `.nojekyll` | CI-verified |

The release infrastructure is genuinely good and hard-won: the multi-arch manifest job
verifies both architectures landed; the Pages build fails if the export is empty; the
desktop `shell` job `needs: sidecar` because racing it once shipped a 5 MB app that passed
CI and died on launch. Keep all of it.

**D-1 (P1).** `deploy/`'s production path has no automated verification. `start.sh` (8.8 KB)
is the only first-run experience and is not exercised by CI.

## 12. Existing evaluation

`evals/` is the most philosophically disciplined part of the repository, and it is
under-used.

- `harness.py::judge_citation_support` and `benchmark.py::calc_support_rate` both exclude **unjudged** claims from the denominator and return `None` when nothing was judged. Two homes for one rule, flagged as such in both files and in AGENTS.md.
- `metrics.py` carries `METRICS_VERSION = 4` with a changelog of what each bump redefined, so two runs are never silently compared.
- `_result_path()` refuses to overwrite: `eval-<date>-<routing>-run<N>.json`.
- CI job `eval-artifacts` fails the build if a committed result file is *modified* (diff-filter=M).
- `citation_rate.resolution_rate` returns `float | None`, shared by the app and the harness so the published number and the displayed number cannot drift.

**V-1 (P1). The headline number is a v3 measurement quoted under a v4 regime.**
`README.md:176` cites 90% citation support from `eval-2026-08-13-ollama-run7.json`, whose
`method.metrics_version` is **3**. The current version is 4 (conflicting-evidence block
excluded from claims). The README states the number is interim, self-judged, and misses
the 0.95 threshold — all honest — but does not disclose the version gap, which the
Constitution §14 lists as a rule ("record metric versions", "disclose limitations").

**V-2 (P1). The only clean 10/10 real-model run is a local 7B self-judging its own output.**
`eval-2026-08-13-gemini.json` has `completion_rate: 0.0` and every aggregate `null` —
honestly recorded as unmeasured, not zero. The 2026-08-12 Gemini run completed 2/10.
There is no independent-judge run at all.

**V-3 (P2).** No metric exists for the two V2 asks: **evidence provenance rate** and
**human correction rate**. Both are computable from data the system already produces
(`snippet_unverified` counts; `audit_logs` rework/approve ratio + report diffs).

## 13. Existing tests

477 backend test functions across 49 files; 16 frontend test files; 2 Playwright specs.

**Invariant tests that already exist and must survive:** `test_engine_boundary.py` (AST
import contract, with a guard against a stale allowlist), `test_corpus_egress.py`,
`test_critic_failclosed.py`, `test_evidence_snippet_verification.py`,
`test_evals_support_rate.py`, `test_evals_result_paths.py`, `test_citation_verification.py`,
`test_ssrf_guard.py`, `test_project_memory.py`, `test_desktop_chat.py`,
`test_worker_preload.py`, `test_sidecar_import_tree_excludes_weasyprint`.

The conftest runs against a **real Postgres with pgvector** for memory tests and skips
loudly with a reason when one is absent — the docstring explains that asserting isolation
against a mock "would prove the mock behaves". That is the Constitution §13 rule already
implemented.

**T-1 (P1). No test asserts that the approval boundary holds end to end** — i.e. that an
unapproved report is absent from `memory_chunks`. `test_project_memory.py` covers
ingestion rules; the property needs a black-box assertion.
**T-2 (P1). No test pins server↔desktop contract parity.** AGENTS.md lists eight
behaviours with two homes and records that each was wrong at least once. Only two
(`test_desktop_chat.py`, `test_local_host.py`) have parity coverage.
**T-3 (P2).** Only two E2E journeys. Neither covers export, the bundle, or the verifier.

## 14. Existing security controls

Strong, and mostly architectural rather than advisory:

- httpOnly cookie auth, rotating refresh tokens with reuse detection (`auth_service.py`, `tokens.py`).
- BYOK keys Fernet-encrypted at rest, key derived via HKDF from `ENCRYPTION_KEY` (falling back to `JWT_SECRET_KEY`, documented with the rotation trap); never returned by any endpoint; last-4 hint only.
- Per-run key isolation via `ContextVar`, so concurrent runs in one worker cannot see each other's key.
- SSRF guard re-validated **on every redirect hop** (`tools.py:91`), content-type allowlist, 2 MB body cap, 3-redirect cap.
- Untrusted-content framing: everything the web returns is wrapped in `<untrusted_web_content>` before it reaches a model.
- Strict CSP + security headers middleware; `/docs` disabled in production.
- Startup validation refuses placeholder or short `JWT_SECRET_KEY`, and refuses a production boot whose routing names a provider with no key.
- Corpus airgap: `Embeddings.is_local` must be declared and **defaults to remote**; `pipeline_runner` refuses corpus mode with a non-local embedder before the run starts.
- Four CI greps: no raw-HTML escape hatches, no hardcoded hex, no hardcoded backend URLs, no web storage without an inline justification. **Verified passing** with `/usr/bin/grep` at audit time.

**S-1 (P2).** `research_rate_limit_per_hour` and `chat_rate_limit_per_hour` default to `0`
(unlimited) with a documented rationale (single-tenant self-host). Correct default, but a
public demo that forgets to set them has no throttle.
**S-2 (P2).** No RFC or threat-model entry for what a *shared* deployment implies; the
model is single-tenant and says so, which is fine — it just needs to stay said.

## 15. Current duplication

AGENTS.md already maintains the canonical list. Confirmed still live:

| Behaviour | Homes | Status |
|---|---|---|
| Route validation | `model_routing.validate` + `llm_factory.validate_pricing` | Both present |
| Unmeasured-vs-zero support rate | `evals/harness.py` + `evals/benchmark.py` | Both present, both correct |
| Budget "0 = unlimited" | `graph._over_budget` + `graph._BudgetGuard.exceeded` | Both present, both correct |
| RunConfig construction | `app/runtime.py` + `research_engine/local.py` | Both present |
| Request → Session fields | `api/v1/research.py` + `desktop/sidecar.py` | Both present |
| Per-session run config | `workers/pipeline_runner.py` + `sidecar._drive_session` | Both present |
| Sentence splitting / claim extraction | `evals/metrics.py` + `graph._cited_claims` + `verify_bundle` | **Three copies** |
| Citation regex | `citation_rate._CITE_RE` + `metrics.CITE_RE` + `verify_bundle` | **Three copies** |
| Sources-heading regex | `citation_rate` + `metrics` + `graph` + `verify_bundle` | **Four copies** |

**C-1 (P1). The engine→evals boundary is claimed but not enforced.**
`graph.py:740` states "the engine imports nothing from evals". `research_engine/bundle.py:40`
does `from evals.metrics import CITE_RE, claim_lines`, and `evals/metrics.py:83` imports
back into `research_engine.citation_rate`. `test_engine_boundary.py` only forbids
`FORBIDDEN_ROOTS = ("app",)`, so it cannot catch this. The practical consequence: the
"standalone" engine package cannot be shipped without `evals/`.

**C-2 (P1). Claim extraction has three implementations that must agree.** `graph._cited_claims`
carries a comment saying it "MUST mirror `evals.metrics.split_sentences`/`claim_lines`
exactly". Nothing tests that they do. When they drift, the in-graph fidelity pass and the
eval judge rule on different claims, and the measurement stops measuring the guard.

## 16. Current accidental complexity

1. **`desktop/sidecar.py` is 1,947 lines** — the largest file in the repo — and is a second implementation of the API layer: auth stub, projects, research, plan gate, approve, chat, models, routing, keys, corpus. Roughly 40 routes hand-mirrored.
2. **Three build targets in one Next.js app**, branching on `NEXT_PUBLIC_PAGES` then `NEXT_PUBLIC_DESKTOP`. Each branch is dead code in the other two, so each is only exercised by the target that builds it — three separate local builds required for any change to `app/(site)/` or `app/layout.tsx`.
3. **Generated route directory.** `app/(app)/session/` is gitignored and copied from `app-routes/session/{web,desktop}/` by a prepare script that must *not* run for the Pages build.
4. **Evidence read path goes through a graph rebuild.** `checkpoints.get_thread_state()` constructs a full `StateGraph` to read a dict.
5. **`sessions` is accumulating run-configuration columns** — `corpus_mode`, `demo`, `skip_plan_gate`, `topic_seeds`, `outline_template`, `model_routing`, `plan_json`, `outline_json`. Eight columns that are really one `RunConfig` snapshot.
6. **Four regex families duplicated across three-to-four modules** (see §15).

## 17. Potential dead code / features

Genuinely dead or near-dead:

- **`ExecutorOutput`** (`schemas.py:88`) — superseded by the inline `submit_evidence` model in `graph.py`. Grep shows no production use.
- **`snippet_unverified`** — written, never read (finding E-1). Dead *as written*; the fix is to make it live, not to delete it.
- **`contradiction_count`** — computed in `graph.py:1175`, dropped at the host boundary. `RunOutcome` has no field for it, `HITL_READY` does not carry it, and no frontend file mentions contradictions. Confirmed by grep across `backend/` and `frontend/`.
- **`evals/queries_scholarly_pending.json`** and `queries_scholarly_rubric.json` — a query set with no runner that consumes them.
- **Root `CONTRIBUTING.md`** — 74 lines, superseded by `docs/developers/33-contributing.md` (89 lines), which links *back* to it as "the full policy". The root file omits ruff, the four CI greps, the eval write-once rule, and AGENTS.md. Circular and stale.
- **`.qoder/`** — tool directory, gitignored, present in the working tree.
- **`internal/Launch_Go_No_Go.md`** — a point-in-time checklist, self-described as inaccurate.

Not dead but unreachable: **the bundle export** and **`verify_bundle.py`** (finding A-1).

## 18. Components that should definitely survive

Ranked by how much would be lost by rewriting them:

1. `research_engine/ports.py` + `test_engine_boundary.py` — the boundary and its enforcement.
2. `research_engine/runner.py` — host-independent orchestration, with `resume()`'s deliberate no-default.
3. `graph.verify_evidence_snippets` + `record_tool_output` — the provenance mechanism.
4. `graph._verify_citation_fidelity` — deterministic number-grounding, deictic/label stripping, batched verifier; every regex carries the measured failure that motivated it.
5. `research_engine/bundle.py` + `verify_bundle.py` — the artifact foundation.
6. `citation_rate.py` — one implementation of one measurement, `float | None`.
7. `evals/` unmeasured-vs-zero discipline, `METRICS_VERSION`, `_result_path`, the `eval-artifacts` CI job.
8. `app/services/memory.py` — approval gate + SQL isolation.
9. All security controls in §14, unchanged.
10. `release.yml`, `desktop.yml`, `pages.yml` — every guard in them was bought with a real failure.
11. `PlanGate.tsx` — the best existing V2-shaped surface.
12. `contradictions.py` — validated pairs, deterministic rendering, LLM never authors the block.
13. `AGENTS.md` itself — the highest-value artifact in the repo for a new maintainer.

## 19. Components that should be rewritten

| Component | Why | Shape of the rewrite |
|---|---|---|
| Evidence/claim/source persistence | Does not exist (§5) | New tables + repository layer; checkpoint stops being the system of record |
| `ApprovalGate.tsx` | Draft + three metrics + a green button — exactly what Constitution §12 forbids | Claim-by-claim review console |
| `desktop/sidecar.py` | 1,947 lines duplicating the API layer | Extract a shared application-service layer both hosts call |
| Bundle assembly | Recomputes claims by regex from prose | Serialize stored claim/evidence rows; regex becomes an ingest-time step, not an export-time one |
| Root `CONTRIBUTING.md` | Stale and circular (§17) | One canonical file; the docs page becomes a pointer |
| `sessions` run-config columns | Eight columns for one concept | A `run_config` JSONB snapshot, versioned |
| Claim/citation regex families | 3–4 copies each | One module in `research_engine`, imported by evals — reversing today's direction |

## 20. Components that should be removed

- `ExecutorOutput` (unused).
- `evals/queries_scholarly_pending.json`, `queries_scholarly_rubric.json` (no runner) — or give them one.
- `internal/Launch_Go_No_Go.md` (point-in-time, self-described inaccurate).
- Root `CONTRIBUTING.md` **as a second policy** — keep one file, make the other a link.
- `.qoder/` from the working tree.

Nothing else. In particular: **do not remove the desktop build** — remove its *duplication*.

## 21. Migration risks

| # | Risk | Likelihood | Mitigation |
|---|---|---|---|
| R1 | Backfilling evidence/claims for existing sessions requires reading LangGraph checkpoints, which may already be pruned or absent | High | Backfill best-effort; record `evidence_source: 'checkpoint' \| 'unavailable'`. **Never synthesize.** A session with no recoverable evidence is `unmeasured`, not empty. |
| R2 | Persisting claims changes what the eval judge rules on, breaking comparability | Certain | Bump `METRICS_VERSION` to 5 in the same PR. Never compare across the bump. |
| R3 | Desktop divergence widens while the shared layer is being extracted | High | Write the contract-parity test suite (T-2) **first**, as Milestone 1, before extraction. |
| R4 | The UI rewrite ships before the domain model can feed it, and the new screens are re-skinned prose | High | Strict phase order. No Review UI until claims are queryable. |
| R5 | Three build targets — a change lands green in CI (which runs 2 of 3) and breaks Pages | Medium | Add `build:pages` to CI. It is one job and closes a documented gap. |
| R6 | Evidence tables grow without bound (a comprehensive run gathers ~10 sources × 8 tool rounds) | Medium | Size it before shipping; snippets are capped at 500 chars, so the ceiling is knowable. |
| R7 | Adding governance docs under `docs/plans/` silently publishes them (W-3) | Certain if unaddressed | Make `NEVER_PUBLISH` directory-aware, with a test. |
| R8 | Turning the design gate on by default for API clients breaks scripts | Medium | Already handled by the three-way `skip_plan_gate` default. **Do not "simplify" it.** |

## 22. Website-specific findings

**W-1 (P1). No tutorials exist.** The Master Plan §22 asks for seven. Grep finds the word
"tutorial" only inside the two planning documents. The docs are excellent *reference* and
thin on *task-driven walkthroughs*.

**W-2 (P1). Release metadata has three hand-maintained homes**: `lib/releases.ts`, the
README badge label, the README badge href. AGENTS.md records that these have already
diverged (badge pointed at v1.0.1 while v1.0.2 was current). The Master Plan §22 asks for
one source of truth.

**W-3 (P1). `NEVER_PUBLISH` is per-file, not per-directory.** `frontend/lib/docs.ts:45`
lists two exact slugs. `CATEGORY_ORDER` omission hides a directory from the sidebar but
does **not** stop `generateStaticParams` generating its routes — the comment in the file
says so explicitly. Any new file under `docs/plans/` or `docs/governance/` is published at
an unlinked URL. This audit is filed in `internal/` for that reason.

**W-4 (P2). No Trust page** (Master Plan §23) — "what we verify / what we do not
guarantee". The material for it already exists, scattered across the README's "Stated
plainly" paragraph, `docs/research/16`, and `lib/comparison.ts`.

**W-5 (P2). Roadmap and changelog are docs pages, not site sections.** They render under
`/docs`, so a visitor looking for "what's next" has to know to look in Docs.

## 23. Community infrastructure findings

| Item | State |
|---|---|
| `CONTRIBUTING.md` | Two versions, stale root one is canonical by its own link (§17) |
| `CODE_OF_CONDUCT.md` | Present, 41 lines |
| `SECURITY.md` | Present, 22 lines, points at GitHub Security Advisories |
| Issue templates | 2 (`bug_report.md`, `feature_request.md`), plain Markdown, no forms |
| PR template | 18 lines — does not ask for the Constitution §23 fields (trade-offs, limitations, scope) |
| RFC template | **Absent** (Constitution §22 requires one) |
| ADRs | **Absent** (Constitution §29 requires them; the reasoning exists, in code comments) |
| Good-first-issue labelling | **No evidence** in the repo |
| Contribution ladder | **Absent** |
| Discussions | Not configured in the repo |

The reasoning that *would* fill the ADRs already exists — it is written into code comments
at extraordinary density (why LangGraph rounds, why two gates, why snippets not key_fact,
why ports were rejected). V2's ADR work is largely **extraction**, not authorship.

---

# Part 2 — V1 → V2 migration map

| V1 subsystem | Current purpose | V2 status | Action |
|---|---|---|---|
| `research_engine/ports.py` | Host-independent interfaces | **CORE** | Preserve. Add `SearchProvider` only (3 impls exist) |
| `test_engine_boundary.py` | AST import contract | **CORE** | Preserve; extend `FORBIDDEN_ROOTS` to `evals` (C-1) |
| `graph.py` pipeline | Planner/executor/critic/synth + 2 gates | **CORE** | Preserve topology; emit claims/evidence as records |
| `verify_evidence_snippets` | Provenance check | **CORE** | Preserve; **record** the verdict instead of blanking (E-1) |
| `_verify_citation_fidelity` | Per-claim fidelity | **CORE** | Preserve; write verdicts to claim rows |
| `runner.py` / `RunOutcome` | Host-independent orchestration | **CORE** | Preserve; add contradiction count + provenance stats |
| `bundle.py` + `verify_bundle.py` | Auditable export | **CORE** | Preserve format; source it from stored rows; **surface it in the UI** |
| `citation_rate.py` | One measurement, `float\|None` | **CORE** | Preserve verbatim |
| `memory.py` | Approval-gated project memory | **CORE** | Preserve; measure the distance threshold |
| Auth / BYOK / crypto / SSRF / CSP | Security | **CORE** | Preserve unchanged |
| `audit_logs` | Approval chain | **CORE** | Extend to per-claim review actions |
| `evals/` honesty machinery | Unmeasured ≠ zero | **CORE** | Preserve; add provenance + correction-rate metrics |
| `release.yml` / `desktop.yml` / `pages.yml` | Release | **CORE** | Preserve; add `build:pages` to CI |
| `PlanGate.tsx` | Design gate UI | **CORE** | Preserve; it is the V2 pattern |
| `sessions.sources` JSON | Numbered citations | **VALUABLE** | Migrate to a `sources` table; keep the column as a read-through cache during transition |
| Evidence in checkpoint state | Only evidence store | **VALUABLE** | Promote to `evidence` table; checkpoint becomes resume-only |
| `contradictions.py` | Validated conflict pairs | **VALUABLE** | Promote to a `contradictions` table; surface in UI and at the gate |
| `chat.py` / `threads.py` / `chat_scope.py` | Grounded follow-up | **VALUABLE** | Keep; demote from primary nav; it is a *reading* mode over artifacts |
| `corpus.py` + airgap guard | Private sources | **VALUABLE** | Keep; generalize toward a `SourceProvider` when a second private source lands |
| `catalog.py` + routing | Provider facts | **VALUABLE** | Keep; unify the two validators (P-1) |
| `desktop/sidecar.py` | Second host | **VALUABLE** | **Simplify**: extract shared application services; sidecar becomes transport only |
| `cli.py` | Local runs | **VALUABLE** | Keep; document on the site |
| Three Next.js build targets | Web / desktop / pages | **VALUABLE** | Keep; add the third to CI |
| `ApprovalGate.tsx` | Review UI | **EXPERIMENTAL** | **Rewrite** as a claim-review console |
| `contradiction_detector_node` | Conflict detection | **EXPERIMENTAL** | Keep, isolate, label; its count does not even reach the client today |
| `outlines.py` + template picker | Report structure | **EXPERIMENTAL** | Keep, low cost, real user control |
| `demo_fixtures.py` + `demo` flag | Keyless demo | **EXPERIMENTAL** | Keep — the stamping discipline is exemplary |
| `evals/contradiction_eval.py` | Fixture eval | **EXPERIMENTAL** | Keep, isolated |
| Scholarly query sets | Unrun fixtures | **SPECULATIVE** | Defer or delete |
| Cross-project chat (roadmap) | — | **SPECULATIVE** | Defer past V2 core |
| Scheduled research + diffs (roadmap) | — | **SPECULATIVE** | Defer to Phase 9; needs versioning first |
| Prometheus metrics (roadmap) | — | **SPECULATIVE** | Defer |
| `ExecutorOutput` | Superseded schema | **REMOVE** | Delete |
| `snippet_unverified` as written | Set, never read | **REMOVE (as-is)** | Replace with a persisted provenance state |
| Root `CONTRIBUTING.md` as second policy | Duplicate | **REMOVE** | Collapse to one canonical file |
| `Launch_Go_No_Go.md` | Point-in-time | **REMOVE** | Delete |
| `queries_scholarly_pending/rubric.json` | No runner | **REMOVE** | Delete or give a runner |
| `.qoder/` | Tool dir | **REMOVE** | Untrack |

---

# Part 3 — Proposed V2 architecture

## 3.1 Layering

```
┌──────────────────────────────────────────────────────────────────────┐
│ PRESENTATION                                                          │
│  frontend/app/(app)   frontend/app/(site)   desktop shell   cli       │
└──────────────────────────────────────────────────────────────────────┘
            │ HTTP / IPC — thin transport, no business rules
┌──────────────────────────────────────────────────────────────────────┐
│ APPLICATION SERVICES          ← NEW: the fix for two-host duplication │
│  start_run · submit_plan · submit_review · assemble_artifact          │
│  ingest_memory · list_claims · answer_followup                        │
│  Depends on repository protocols, never on FastAPI/Celery/SQLAlchemy  │
└──────────────────────────────────────────────────────────────────────┘
            │
┌──────────────────────────────────────────────────────────────────────┐
│ DOMAIN (research_engine/domain/)                                      │
│  ResearchProject · ResearchRun · ResearchPlan · Source · Evidence     │
│  Claim · ClaimEvidenceLink · Contradiction · Review · Artifact        │
│  Provenance rules · claim extraction · citation resolution            │
│  Pure. No I/O. Fully unit-testable.                                   │
└──────────────────────────────────────────────────────────────────────┘
            │
┌──────────────────────────────────────────────────────────────────────┐
│ ORCHESTRATION (research_engine/graph.py, runner.py)                   │
│  The LangGraph pipeline, unchanged in topology                        │
└──────────────────────────────────────────────────────────────────────┘
            │ ports
┌──────────────────────────────────────────────────────────────────────┐
│ INFRASTRUCTURE                                                        │
│  Postgres repos │ SQLite repos │ Redis │ provider adapters │ HTTP     │
└──────────────────────────────────────────────────────────────────────┘
```

The one genuinely new layer is **Application Services**. It is what makes
`desktop/sidecar.py` shrink from 1,947 lines to a transport shim, and it is the direct
answer to the recurring bug AGENTS.md has been tracking for the whole of V1.

## 3.2 Domain model and persistence

```
research_projects
      │
      └── research_runs ──────────────── run_config (JSONB snapshot, versioned)
              │
              ├── research_plans          tasks, outline, edited-at-gate decision
              │
              ├── sources                 url, title, first_seen_at, fetch_status
              │       │
              │       └── evidence        snippet, content_hash, key_fact,
              │                           provenance_state, verified_against,
              │                           retrieved_at, task_id
              │
              ├── claims                  text, ordinal, section,
              │       │                   verification_state, review_state
              │       │
              │       └── claim_evidence  claim_id, evidence_id, stance
              │                           (SUPPORTS | CONTRADICTS)
              │
              ├── contradictions          claim_a, claim_b, evidence_a, evidence_b,
              │                           nature, dimension, resolution_state
              │
              ├── reviews                 actor, action, target (run|claim),
              │                           target_id, comment, decided_at, hash
              │
              └── research_artifacts      version, manifest JSONB, bundle_hash,
                                          created_at, superseded_by
                          │
                          └── memory_chunks   (only from approved artifacts)
```

### The one new enum that does the most work

```python
class ProvenanceState(StrEnum):
    ATTESTED   = "attested"    # snippet found verbatim in tool-returned text
    UNATTESTED = "unattested"  # checked, not found — a caught fabrication
    UNCHECKED  = "unchecked"   # verification did not run (fake mode, verifier down)
```

Three states, never two, and `UNCHECKED` is never rendered as `UNATTESTED`. This is
finding E-1's fix and it is the same rule the codebase already applies to
`citation_resolution_rate`, `trace_available`, and `ConnectionState` — V2 applies it to
the object the product is actually about.

### Claim states

Deliberately fewer than the Master Plan §6 sketch, per its own "avoid premature state
explosion":

```
verification_state : UNVERIFIED | SUPPORTED | UNSUPPORTED | CONTESTED
review_state       : PENDING | APPROVED | REJECTED | EDITED
```

`CONTESTED` is set only when a contradiction row references the claim.
`INSUFFICIENT_EVIDENCE` is not a separate state — it is `UNSUPPORTED` with zero links, and
the UI can say so without the model needing a fourth value.

### What the checkpoint is for after V2

Resume only. Today it is the system of record for evidence and contradictions; after
Milestone 2 it holds transient graph state and nothing a bundle depends on.

## 3.3 The evidence pipeline, V2

```
tool call ──→ tool_observations (url → text, hashed)         [recorded, not just held]
                    │
model submits evidence ─→ attest(snippet, observations)
                    │
        ┌───────────┴───────────┐
   found                    not found
        │                        │
  ATTESTED                  UNATTESTED          (verification skipped → UNCHECKED)
        │                        │                        │
        └────────────┬───────────┴────────────────────────┘
                     ▼
              evidence row (state persisted, snippet KEPT)
                     │
        synthesizer sees ATTESTED snippets only
                     │
              claims + claim_evidence links
                     │
        fidelity pass writes verification_state per claim
                     │
        artifact serializes rows; verifier re-checks offline
```

The key change from V1: an `UNATTESTED` snippet is **kept and labelled**, not blanked. The
report never quotes it, the UI shows it as a caught fabrication, and the artifact records
that the system found and rejected it. Today that finding is thrown away.

## 3.4 Review, V2

The review screen becomes the product's centre:

```
┌────────────────────────────────────────────────────────────┐
│ Run · question · 14 claims · 9 sources · 1 conflict        │
│ [Approve all] [Approve remaining] [Send back]              │
├────────────────────────────────────────────────────────────┤
│ ▸ Claim 3   SUPPORTED    2 sources                  ✓ ✗ ⟳ │
│     "Postgres logical replication adds ~8% write …"        │
│     ├ [4] pgsql.org  ATTESTED   "…measured 8.1% …"        │
│     └ [7] blog.x     ATTESTED   "…between 7 and 9 …"      │
│                                                            │
│ ▸ Claim 7   CONTESTED    2 for · 1 against         ✓ ✗ ⟳ │
│     ├ supports  [2] …                                      │
│     └ conflicts [9] …   timeframe: 2021 vs 2025           │
│                                                            │
│ ▸ Claim 11  UNSUPPORTED  0 attested sources        ✓ ✗ ⟳ │
│     ⚠ one snippet was rejected: not found in the fetched   │
│       page (source [5])                                    │
└────────────────────────────────────────────────────────────┘
```

Per-claim actions (`approve`, `reject`, `request more evidence`, `edit`, `comment`) each
write a `reviews` row. That is what makes **human correction rate** (Master Plan §28)
measurable rather than aspirational — it falls out of the data instead of needing a new
instrument.

## 3.5 Provider architecture

Extract exactly one new port in V2: **`SearchProvider`** (Tavily, Brave, DuckDuckGo — three
implementations already exist, so the "second implementation" test is long since passed).

Do **not** create `ArtifactStorageProvider` or a plugin framework. One storage
implementation exists; abstracting it would be the speculative abstraction the
Constitution §6 forbids.

---

# Part 4 — Proposed V2 milestones

Nine milestones, each independently shippable and verifiable. Order follows the Master
Plan §33 with two repository-driven changes: **M1 is contract-parity tests before any
extraction** (risk R3), and the artifact surfacing (M5a) is pulled early because it is a
one-day fix to a P0 product gap that needs no schema work.

---

### M0 — Executable invariants and boundary repair

**Goal.** Make today's invariants fail loudly before anything is refactored on top of them.

**Scope.** Extend `FORBIDDEN_ROOTS` to `("app", "evals")` and break the
`bundle.py → evals.metrics` import by moving `CITE_RE`/`claim_lines` into
`research_engine/claims.py`, with `evals.metrics` importing *from* it. Add a test pinning
`graph._cited_claims` and `claims.claim_lines` to identical output over a fixture corpus.
Add `build:pages` to CI. Make `NEVER_PUBLISH` directory-aware with a test.

**Files.** `research_engine/claims.py` (new), `research_engine/bundle.py`,
`research_engine/graph.py`, `research_engine/verify_bundle.py`, `evals/metrics.py`,
`evals/harness.py`, `tests/test_engine_boundary.py`, `tests/test_claim_extraction_parity.py`
(new), `frontend/lib/docs.ts`, `.github/workflows/ci.yml`.

**Acceptance.** `test_engine_boundary` fails on a deliberate `from evals import x` in an
engine module. Claim-parity test fails when either splitter is changed alone. A new file
under `docs/plans/` does not appear in the export.

**Tests.** Boundary, claim parity, docs denylist.
**Docs.** `AGENTS.md` duplication table updated (four regex families collapse to one).
**Migration.** None — pure refactor. `METRICS_VERSION` unchanged (behaviour identical).

---

### M1 — Server ↔ desktop contract parity harness

**Goal.** Close risk R3 before the shared layer is extracted.

**Scope.** A parametrized suite that drives the *same* journey against the FastAPI app and
the sidecar app and asserts identical status transitions, event sequences, and response
shapes. Cover every row of AGENTS.md's two-homes table. Where a divergence is intentional
(no auth, no rate limit, one corpus file, project chat absent), assert the divergence
explicitly so it cannot widen silently.

**Files.** `tests/test_host_parity.py` (new), `tests/conftest.py`.

**Acceptance.** Deleting a sidecar route that the server has fails the suite. Adding a
`RunOutcome.status` value without updating both `sidecar._apply_outcome` dicts fails.

**Tests.** This milestone is the test.
**Docs.** `backend/AGENTS.md` gains a "parity is enforced" section.
**Migration.** None. **Expect this to find live divergences** — `/cancel`, the bundle route,
and `/threads` are already known.

---

### M2 — Domain model and persistence

**Goal.** Sources, evidence, claims, links, and contradictions become rows.

**Scope.** `research_engine/domain/` (pure dataclasses + rules). Alembic migrations 0016–0020.
Repository protocols in `ports.py`; Postgres implementations in `app/`, SQLite in
`desktop/`. The graph writes through the repositories at node boundaries. The checkpoint
stops being the evidence store. Best-effort backfill command for existing sessions,
dry-run by default, following `app/maintenance.py`'s pattern exactly — recording
`evidence_source: checkpoint | unavailable`, **never synthesizing**.

**Files.** `research_engine/domain/*` (new), `research_engine/ports.py`,
`app/models/{source,evidence,claim,claim_evidence,contradiction}.py` (new),
`backend/alembic/versions/0016..0020_*`, `app/repositories/` (new),
`desktop/repositories.py` (new), `research_engine/graph.py`, `app/maintenance.py`.

**Acceptance.** A completed run has queryable evidence and claims. Every `[n]` in a stored
report resolves to a `sources` row via `claim_evidence`. A session whose checkpoint is gone
backfills as `unavailable`, not as zero evidence. `alembic downgrade` is clean.

**Tests.** Round-trip persistence; a graph run producing rows; backfill purity (the planner
function is pure and unit-tested, as `plan_backfill` already is); an invariant test that
every claim's citation indices resolve.

**Docs.** `docs/architecture/05-data-model.md` (same PR, per the docs contract).
**Migration.** Reversible. `sessions.sources` retained and dual-written for one release.

---

### M3 — Evidence provenance as a first-class state

**Goal.** Fix E-1, E-2, E-3. **This is the P0 milestone.**

**Scope.** `ProvenanceState` on every evidence row. `verify_evidence_snippets` records the
verdict instead of blanking the snippet. Tool observations recorded with content hashes, so
"did this come from the source" is answerable after the fact. Self-consistent fake fixtures
so the check runs in fake mode and CI covers the wiring (E-2). Source attestation: a
`source_url` never returned by a tool is marked `UNATTESTED` at the *source* level (E-3).
Provenance state flows into `Source`, the bundle (`SnippetRecord.provenance_state`,
bundle version 2), the verifier, and the UI chip.

**Files.** `research_engine/graph.py`, `research_engine/schemas.py`,
`research_engine/fakes.py`, `research_engine/bundle.py`, `research_engine/verify_bundle.py`,
`frontend/lib/citations.tsx`, `frontend/lib/types.ts`.

**Acceptance.** A fabricated snippet is stored as `UNATTESTED` and visible as such in the
UI and the bundle — not blanked. Fake mode exercises the check; a regression in
`verify_evidence_snippets` turns CI red. `UNCHECKED` never renders as `UNATTESTED`.

**Tests.** Fabrication end-to-end in fake mode; bundle carries state; verifier reports it;
a test asserting the three states are never collapsed.

**Docs.** `docs/user-guide/27-citations.md`, `docs/reference/15-bundle-format.md`
(bundle_version 2 + compatibility note).
**Migration.** Bundle v1 readers must still verify. Backfilled rows are `UNCHECKED`.

---

### M4 — Claims, links, and contradictions as products

**Goal.** Structured claims replace regex-at-export.

**Scope.** The synthesizer emits claims with citation indices as data; the fidelity pass
writes `verification_state` per claim; `claim_evidence.stance` distinguishes supporting from
contradicting. Contradictions become rows referencing claims and evidence, with a `dimension`
field (timeframe / methodology / population / workload / source-quality). `RunOutcome` gains
`contradiction_count`, `HITL_READY` carries it, and the gate shows it — closing the dead
path found in §17.

**Files.** `research_engine/graph.py`, `research_engine/runner.py`,
`research_engine/contradictions.py`, `app/workers/pipeline_runner.py`,
`desktop/sidecar.py`, `app/api/v1/research.py`, `frontend/lib/types.ts`.

**Acceptance.** `GET /runs/{id}/claims` returns claims with stance-labelled evidence.
A run with contradictions shows the count at the review gate on **both** hosts.
The rendered conflict block is generated from the same rows the API serves.

**Tests.** Claim/evidence linkage invariants; contradiction validation (a pair citing a
source not in evidence is dropped — preserve today's behaviour); host parity for the count.

**Docs.** `docs/architecture/04-agent-architecture.md`, `docs/user-guide/27-citations.md`.
**Migration.** `METRICS_VERSION` → 5. Disclose in `docs/research/16` and the README.

---

### M5a — Surface the artifact *(small, urgent, independent)*

**Goal.** Fix A-1. Can ship any time after M1; does not wait for M2.

**Scope.** A bundle download control in `ReportView.tsx` beside `.md`/`.pdf`. A bundle route
on the sidecar. README export sentence corrected. A short "verify this yourself" doc page
with the exact `verify_bundle.py` invocation.

**Files.** `frontend/components/session/ReportView.tsx`, `backend/desktop/sidecar.py`,
`README.md`, `docs/user-guide/29-exports.md`.

**Acceptance.** A user can download and verify a bundle from the web app and the desktop
app without reading the source. Host-parity suite covers the route.

**Tests.** Parity test; an E2E journey that downloads a bundle and runs the verifier on it.
**Docs.** Exports page; README.
**Migration.** None.

---

### M5b — ResearchArtifact as a stored object

**Goal.** Artifacts get identity, immutability, and versions.

**Scope.** `research_artifacts` table. Assembled at approval, not at download. `version`,
`bundle_hash`, `superseded_by`. Serialized from stored rows rather than recomputed. Memory
ingestion keys off the artifact, not the session. `GET /artifacts/{id}` and an Artifact
screen (report · claims · evidence · sources · provenance · approval history · integrity ·
exports).

**Files.** `app/models/research_artifact.py` (new), migration 0021,
`app/api/v1/artifacts.py` (new), `research_engine/bundle.py`, `app/services/memory.py`,
`frontend/app/(app)/artifact/[id]/page.tsx` (new).

**Acceptance.** Approving produces exactly one artifact row. Re-export is byte-identical.
Re-running a question produces v2 with `superseded_by` set on v1. Memory contains only
artifact-derived chunks.

**Tests.** Byte-identical re-export; approval-boundary invariant (T-1) as a black-box
assertion: **an unapproved run's text appears in no `memory_chunks` row**; version chaining.

**Docs.** `docs/reference/15-bundle-format.md`, `docs/user-guide/29-exports.md`,
`docs/architecture/05-data-model.md`.
**Migration.** Backfill artifacts for completed sessions where evidence is recoverable;
mark the rest `evidence: unavailable`.

---

### M6 — Review console

**Goal.** Human review becomes the product's strongest surface.

**Scope.** Rewrite `ApprovalGate.tsx` as a claim-review console (§3.4). Per-claim
approve / reject / request-evidence / edit / comment, each writing a `reviews` row.
"Request more evidence" resumes the graph scoped to one task. Run-level approve requires
an explicit acknowledgement when unsupported or contested claims remain — the button stops
being blind. Keyboard navigation and screen-reader semantics from the start.

**Files.** `frontend/components/review/*` (new), `frontend/app/(app)/session/*`,
`app/api/v1/reviews.py` (new), `research_engine/graph.py` (scoped re-run),
`desktop/sidecar.py`.

**Acceptance.** A reviewer can traverse claim → evidence → source without leaving the page.
Rejecting a claim is recorded and visible in the artifact's approval history. Approving a
run with unsupported claims requires acknowledging them.

**Tests.** Component tests for each action; an E2E journey that rejects a claim, requests
evidence, and approves; an a11y assertion pass.

**Docs.** `docs/user-guide/26-review-and-approval.md`.
**Migration.** Run-level approval still works; per-claim review is additive.

---

### M7 — Application-service extraction and desktop convergence

**Goal.** One implementation of every business rule; `sidecar.py` becomes transport.

**Scope.** Move `start_run`, `submit_plan`, `submit_review`, `assemble_artifact`,
`ingest_memory`, `answer_followup` into `app_services/`, depending only on repository and
engine ports. FastAPI routes and sidecar routes both become thin adapters. Target: sidecar
under 600 lines. Unify the two route validators (P-1). Unify the two `RunConfig` builders.

**Files.** `backend/app_services/*` (new), `app/api/v1/*`, `desktop/sidecar.py`,
`app/workers/pipeline_runner.py`, `app/runtime.py`, `research_engine/local.py`,
`app/services/model_routing.py`, `research_engine/llm_factory.py`.

**Acceptance.** The parity suite passes unchanged. `sidecar.py` shrinks by >60%. AGENTS.md's
two-homes table loses at least five rows. A desktop bundle is **launched and verified**
(~180 MB, not ~5 MB).

**Tests.** Parity suite (unchanged); service-layer unit tests with fake repositories.
**Docs.** `docs/architecture/13-local-and-self-hosted.md`, `AGENTS.md`.
**Migration.** Pure refactor. No schema change.

---

### M8 — Website, tutorials, release metadata

**Goal.** Close W-1 through W-5.

**Scope.** One release source of truth (`releases.json` at the repo root, consumed by
`lib/releases.ts` at build time and by a README-badge check in CI, so a drifted badge fails
the build). Seven tutorials, each **verified by running its commands**, none for unbuilt
features. A Trust page. Roadmap and Changelog as site sections. Homepage reframed around
Question → Research → Evidence → Review → Verified Artifact, leading with the thesis rather
than the pipeline.

**Files.** `releases.json` (new), `frontend/lib/releases.ts`, `frontend/app/(site)/*`,
`docs/tutorials/*` (new), `README.md`, `.github/workflows/ci.yml`.

**Acceptance.** Bumping `releases.json` updates the site, the download button, and the
README badge; a stale badge fails CI. Every tutorial's commands were executed by their
author, and the PR says so. All five existing site pages still render after the change (they
share a layout — check all of them, not the one you edited).

**Tests.** A CI check asserting README badge ↔ `releases.json` agreement; a link checker.
**Docs.** The tutorials are the docs.
**Migration.** None.

---

### M9 — Community infrastructure and measurement

**Goal.** The project becomes maintainable by a stranger.

**Scope.** One canonical `CONTRIBUTING.md`. RFC template (Constitution §22 fields). PR
template carrying the §23 fields. Issue forms. ADRs extracted from existing code comments —
why LangGraph, why two gates, why approval gates memory, why snippets not key_fact, why
those four ports and not six. A contribution ladder (5 min / 30 min / 2 h / 1 day /
architecture) with real labelled issues at each level. Two new eval metrics: **evidence
provenance rate** (`ATTESTED / (ATTESTED + UNATTESTED)`, `None` when nothing was checked)
and **human correction rate** (from `reviews`). An independent-judge eval run, disclosed as
such, replacing the self-judged headline.

**Files.** `CONTRIBUTING.md`, `.github/ISSUE_TEMPLATE/*`, `.github/PULL_REQUEST_TEMPLATE.md`,
`docs/adr/*` (new), `evals/metrics.py`, `evals/harness.py`, `README.md`.

**Acceptance.** A contributor with no prior context can find a task, run the checks, and
open a PR from the repository alone. The provenance metric distinguishes unmeasured from
zero — assert it. The published headline number states its judge and its metrics version.

**Tests.** Metric unit tests, including the `None` case for both new metrics.
**Docs.** ADRs, contributing, benchmark methodology.
**Migration.** `METRICS_VERSION` → 6 if definitions change; disclose.

---

## Sequencing

```
M0 ─→ M1 ─→ M2 ─→ M3 ─→ M4 ─→ M5b ─→ M6 ─→ M7 ─→ M8 ─→ M9
              │                                                    
       M5a ───┘  (independent after M1 — ship it first; it is a one-day P0 fix)
```

M8 and M9 can run in parallel with M6/M7 if a second contributor exists; they touch
disjoint files.

## What is explicitly NOT in V2 scope

Per Master Plan §34 and the existing roadmap's "not planned": mobile, voice, billing,
teams/roles, SSO, Kubernetes, microservices, a plugin marketplace, `ArtifactStorageProvider`,
research replay of external web content, and any confidence *score*. Contradiction
handling ships (M4) but only as detection and presentation — never resolution.

## Definition of done, per milestone

Master Plan §37, applied literally. A milestone is done when it has: design, implementation,
tests, documentation updated **in the same PR**, UX verification, self-host verification
(`./start.sh` from a clean clone), and — where it touches a release surface — release
verification, meaning **a desktop bundle that has actually been launched**.
