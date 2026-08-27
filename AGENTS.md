# Agent guidance — repository root

Read this first. Package-specific traps live in [`backend/AGENTS.md`](backend/AGENTS.md)
and [`frontend/AGENTS.md`](frontend/AGENTS.md); read the one you are about to touch.

**Keep this file current.** It describes traps, not features. Update a rule in the same
commit that invalidates it — a stale rule is worse than no rule, because it gets trusted.
Add a rule only after something has actually bitten; this is not a style guide.

---

## What this project is

A self-hostable, bring-your-own-key research assistant. A LangGraph pipeline
(Planner → Executor ⇄ Critic → Synthesizer → **human gate** → Finalizer) searches, gathers
cited evidence, and pauses at a durable checkpoint for human approval before finalizing.

**Input:** a research question + depth (`fast` | `balanced` | `comprehensive`), optionally
scoped to a project and an uploaded corpus.
**Output:** a cited Markdown report where every `[n]` resolves to a real source and a
verbatim supporting snippet, exportable to `.md`/`.pdf`, plus grounded follow-up chat over
approved reports.

## The invariant everything else serves

**The product claim is verifiability, so a false measurement is a P0 bug, not a cosmetic
one.** A citation that cannot be resolved renders its ⚠ unverified chip rather than clean.
An eval that could not measure something must say so — never print `0.0`, never record a
model id you did not call, never score a baseline against placeholder text.

`evals/benchmark.py::_build_judge`/`calc_support_rate` and
`evals/harness.py::judge_citation_support` are two homes for this rule — **change both**.
Both exclude unjudged claims from the denominator and return `None` when nothing was
judged, so an exhausted quota can't masquerade as a quality collapse.

**A committed eval result is evidence, and evidence is write-once.** Never modify a file
under `backend/evals/results/`; add a new one named `eval-<date>-<routing>-run<N>.json` — a
date alone is not a run identity (a past commit once overwrote and destroyed a real run's
only record). CI enforces this (`ci.yml`, job `eval-artifacts`).

## Docs are the build contract

`docs/` is authoritative — see [`docs/00_INDEX.md`](docs/00_INDEX.md). Code that
contradicts the docs is wrong; docs that contradict shipped code must be fixed **in the
same PR**. Cite the doc section in code comments when encoding a decision from it
(`docs/13 §6`) — that's how a reader knows a line is deliberate.

**Documents are cited by number, and the number is stable** — hundreds of comments say
`docs/04 §6`. Directory, filename and published URL (from `NAV_ORDER` in
`frontend/lib/docs.ts`, keyed by slug) are free to change; renumbering is not.

**`docs/` is the published tree** — anything filed there gets a URL at build time.
Engineering notes, milestone plans and release checklists live in
[`internal/`](internal/README.md), which the site never walks.

Publication is decided **per directory** by `classifyDir` in `frontend/lib/docs.ts`:
`CATEGORY_ORDER` publishes, `UNPUBLISHED_DIRS` withholds (`governance/`, `plans/`,
`screenshots/`), and a directory in neither **fails the build**. Absence from
`CATEGORY_ORDER` alone only hides a directory from the sidebar — `generateStaticParams`
still generates its routes (a note once filed under `docs/plans/` published at a URL
nothing linked to). `frontend/lib/docs.test.ts` guards it; CI greps the `build:pages`
export for governance/planning routes.

## Configuration has two paths, and they drift

The same `RunConfig` is built by two independent code paths. **Change one, change both**:

| Path | Built by | Used by |
|---|---|---|
| Server | `app/runtime.py` ← `app/config.py` (pydantic-settings) | API, Celery worker |
| Local | `research_engine/local.py::run_config_from_env` ← `os.environ` | CLI, eval harness, benchmark, desktop sidecar |

Has drifted twice: the local path once knew only Google/Anthropic/OpenAI keys (OpenRouter
unreachable, `custom:` silently fell through to `api.openai.com`), and once defaulted
`enforce_ssrf_guards` to `True`, rejecting every local model server on a laptop.

**Local endpoints:** `research_engine.llm_factory.map_local_host()` is the single
implementation that rewrites `localhost` → `host.docker.internal` inside a container. Use
it — three copies of this logic existed once and two were wrong.

## The recurring bug: two hosts, one contract

Server and desktop are **parallel implementations of the same contract**. Every shared
behaviour has two homes, and the second one gets forgotten. Every row below shipped, not
imagined.

The frontend has **three build targets**: `next.config.ts` branches on `NEXT_PUBLIC_PAGES`
(static export, GitHub Pages), then `NEXT_PUBLIC_DESKTOP` (static export, Tauri), then the
standalone server image. A branch is only exercised by the target that builds it —
`npm run build`, `build:desktop` and `build:pages` are three separate checks; CI runs only
the first two. Anything touching `app/(site)/` or `app/layout.tsx` needs all three run
locally.

| Behaviour | Copies | How many were wrong |
|---|---|---|
| `localhost` → `host.docker.internal` | 3 | 2 |
| Request fields reaching `Session(...)` (`corpus_mode`, `demo`) | 3 | 3 |
| Resolving `corpus_dir` | 2 | 2 — both relative, so upload and run disagreed |
| Validating a `provider:model` route | 2 | 1 — routing accepted what pricing refused |
| Where the bundled sidecar lives | 3 | 3 |

**When you change any of these, grep for the other copy before you finish:**

- Config → `app/runtime.py` *and* `research_engine/local.py`
- Request → session → `app/api/v1/research.py` *and* `desktop/sidecar.py`
- Per-session run config → `app/workers/pipeline_runner.py` *and*
  `desktop/sidecar.py::_drive_session`
- A new `RunOutcome.status` → `pipeline_runner::_persist_outcome` *and* **both** dict
  literals in `sidecar::_apply_outcome` (status map, lifecycle-event map) — a missing key
  raises inside a background task, so the session sits on RUNNING forever with nothing in
  the log to say why
- A new pause event → the stream's stop-list in `app/api/v1/research.py` *and*
  `sidecar::_TERMINAL_EVENTS` — a stream left open on a suspended graph waits on no one
- Route validation → `app/services/model_routing.py::validate` *and*
  `research_engine/llm_factory.py::validate_pricing`
- Unmeasured-vs-zero in the support rate → `evals/harness.py::judge_citation_support`
  *and* `evals/benchmark.py::calc_support_rate`
- Embedder locality → every `Embeddings` adapter must expose `is_local`
  (`research_engine/embeddings.py`, `app/adapters.py`); the corpus airgap guard **defaults
  to remote** for anything that does not declare itself
- Schema → an Alembic migration for Postgres *and* the ORM model, which the desktop's
  `create_all` plus startup column sync reads
- Report chat → `app/api/v1/chat.py` *and* `desktop/sidecar.py` (the sidecar had no chat
  routes at all for a whole release — a shipped control that 404'd). Three things
  legitimately differ: keys come from the keychain not a decrypted column, no rate-limit
  dependency (desktop has no Redis), one `corpus.sqlite` for the whole app not one per
  project. **Project chat (`/threads`) is desktop-absent by design** — project memory is
  pgvector-only
- Bundle export → `app/api/v1/research.py::export_bundle_json` *and*
  `desktop/sidecar.py::export_bundle_json` — shipped in v1.0.0 with no desktop route, and
  no UI anywhere reached it on either host despite four surfaces advertising it. Four
  things legitimately differ: SQLite not Postgres, no `crypto.decrypt` step, the report is
  read directly not through the server-only `_report_or_404`, `trace_available` is `True`
  on both. **A bundle route is only correct if what it emits verifies** — the sidecar
  wrote no `audit_log` row at either gate, so the route alone would have produced bundles
  that always fail `approval_chain`; `tests/workflow/test_bundle_export_routes.py` pins the whole
  chain
- Sidecar location → `desktop/tauri.conf.json` (`bundle.resources`), `desktop/src/lib.rs`
  (`sidecar_command`), *and* `.github/workflows/desktop.yml` (the `shell` job must
  `needs: sidecar`). All three were wrong at once: no `resources` key so nothing was
  copied in, `lib.rs` looked next to the executable instead, CI raced the two jobs — a
  5 MB `.app` passed CI and died on first launch. **A desktop bundle that has not been
  launched is not verified** — check the artifact is ~180 MB, not ~5 MB
- Corpus document/status/upload response shape → `app/api/v1/corpus.py`'s
  `DocumentResponse`/`CorpusStatusResponse` *and* the four matching routes in
  `desktop/sidecar.py`. The desktop routes 200'd and `test_desktop_contract_gaps.py`
  called them, but the body was `CorpusStore.documents()`'s own raw shape
  (`chunk_count`/`ingested_at`, a `{"documents": [...]}` wrapper on the list route) instead
  of the server's field names (`chunks`/`created_at`, a bare array) — and the status route
  never summed `chunks` at all. `hooks/queries.ts::useCorpusDocuments` types the response
  as a bare `CorpusDocument[]`, so `.length` on the wrapper read as `undefined` — falsy —
  and the Corpus page rendered "no documents" for a corpus that was never empty. No
  crash, no failing test, just silently wrong on desktop only. **Registration is not
  behaviour**: the existing parity test called the route and asserted equality between
  the two desktop response shapes, which only proves the bug was consistent, not correct —
  it had to be checked against the *server's* contract, not against itself.
  `desktop/sidecar.py::_document_response`/`_corpus_status_response` are the one shaping
  function each, called from both the flat and per-project routes

Prefer extracting shared logic into one function over keeping two copies in step by
discipline — `map_local_host` is the worked example of doing that after the fact.

**The invariant that replaces the discipline:**

> A new product feature must be implementable **once** in the canonical
> application/domain layer and exposed by both hosts through thin adapters.

`tests/workflow/test_layer_boundaries.py` enforces the direction that makes it possible —
transport → application → domain → ports → infrastructure, downward only. `app/handlers/`
is the application layer: plain `async` functions taking their collaborators as arguments,
with **no** FastAPI, no `app.config`/`app.db`/`app.dependencies`/`app.adapters`/
`app.workers`, no Celery, Redis or keyring, and nothing from `desktop/`. `app/ports.py`
holds the interfaces whose implementations genuinely differ per host.

The rule exists because `Depends(...)` is the coupling vector: a route written the ordinary
FastAPI way binds `get_db`, `get_current_user`, `get_redis` and `settings` into the same
function as the product rule, so the desktop *cannot* reuse it and restates it instead.
`app/api/v1/runs.py` is what avoiding that looks like — handlers as plain functions with
`Depends` only as defaults — and nothing enforced it, so every other module drifted back.

`KNOWN_EXCEPTIONS` there is one entry per real violation, each naming the phase that
removes it. Adding one should take an argument; an entry that stops being true fails the
suite.

**A route that exists on both hosts can still be desktop-only broken, and parity won't see
it.** The sidecar's run routes import their handlers from `app.api.v1.runs` rather than
restating them, so registration matched on both hosts while every run route on the packaged
app 500'd, in three layers that only bite the desktop:

| Layer | Why it only bit the desktop |
|---|---|
| `app.config` builds `Settings` at import, requiring `database_url`/`jwt_secret_key` | An installed app exports neither |
| `app.db.redis` imports `redis` at module scope | `research-sidecar.spec` excludes `redis` — `ModuleNotFoundError` in the bundle only |
| `create_run` imports `app.workers.tasks` when `dispatch` is set | `celery` is excluded too, and this host has no broker either way |

**Anything the desktop imports at request time must also fit in the bundle** —
`test_sidecar_startup.py` asserts the run import tree touches none of the spec's excludes,
built the way the launcher does (its prior assertions covered startup only, which is why
they stayed green). **Execution differs by mechanism, not by contract**: the server hands a
run to a Celery worker, the desktop drives it as an `asyncio` task against its own SQLite
checkpointer, and `app/run_dispatch.py` is the seam — it refused with a 501 until the
in-process driver existed, which is why that seam is three named operations rather than one
`enqueue`. The same packaged-app run found the behavioural twin:
`POST /projects` on a duplicate name threw an unhandled `IntegrityError` on desktop where
the server returned 409 — **parity checks registration; only a test that calls the route
checks behaviour.**

**`tests/workflow/test_host_parity.py` is the enforcement**, holding four tables:

| Table | Means |
|---|---|
| `INTENTIONAL_SERVER_ONLY` | The route legitimately has no desktop equivalent, with the reason |
| `INTENTIONAL_DESKTOP_ONLY` | The reverse |
| `DESKTOP_UI_CALLS` | Every path the desktop build actually calls — the sidecar must serve all of them |
| `KNOWN_DESKTOP_GAPS` | Paths the UI calls and the sidecar does **not** serve, i.e. controls that 404 today |

A route on one host and not the other must appear in one of the four or the suite fails;
an entry that no longer describes reality also fails.

**`KNOWN_DESKTOP_GAPS` is empty and must stay empty** — an entry there is a control that
ships broken. The corpus fix is the pattern to copy: desktop's one `corpus.sqlite` for the
whole app vs. the server's one-per-project is a real infra difference that stays, but it
had leaked into the client — the sidecar now serves the **per-project path as the
canonical contract** and resolves it to its own flat store internally, with no `isDesktop`
branch in the frontend. Prefer that shape: one product contract, different internals.

**The row records what actually ran, not what was requested.** "Scripted"/`demo` must be
decided from the request flag *or* the resolved `llm_mode`, in one branch, in all three
homes: `pipeline_runner::_run_config_for`, `run_execution::run_config_for_run`,
`sidecar::_drive_session`. (`--fake` is a process flag, `demo` a request flag; a run that
silently fell back to `LLM_MODE=fake` — the common first-run-with-no-key case — used to
record `demo=false`, so its bundle named models nothing had called and its `.md` came out
unstamped with no warning. That's the P0 honesty class, not cosmetic.)
`tests/workflow/test_scripted_runs_are_recorded_as_demo.py` pins all three.

**A cancelled run stays cancelled** (issue #54) — durable state
(`sessions.cancelled_at`/`research_runs.cancelled_at`), and all three outcome writers
refuse to move a cancelled row out of its terminal state: `pipeline_runner::_persist_outcome`,
`sidecar::_apply_outcome`, `run_execution::persist_outcome`. Change all three.
`tests/workflow/test_cancellation_is_authoritative.py` pins the ordered t0→t1→t2 race. **The run
itself still does not stop** — nothing interrupts the Celery task or the sidecar's
`asyncio.Task`, so it spends tokens to its next checkpoint, and that spend is recorded, not
dropped. Preemption is unbuilt on purpose (a killed task risks a half-written checkpoint,
and the mechanism differs per host).

**A test that stubs the thing it is testing proves nothing.** `test_corpus_egress.py`
asserted zero network calls in corpus mode while injecting a `FakeEmbeddings` — the query
embedding was the only call that egressed, so the suite was green because it had replaced
the defect. **A decode that does not raise is not a decode that succeeded**:
`research_engine/checkpoint_read.py` exists to keep a missing checkpoint distinct from an
empty one, but a `FakeSaver` that raises on corruption is not the real thing: a LangGraph
saver's damaged blob deserialises to the integer `0`, which reads as "opened it, no
evidence" for a checkpoint never actually read. When testing an *absence* (no egress, no writes, no spend), check what the fixtures
replaced; check the shape you got back, not just the absence of an exception.

## Provider and cost rules

- Routing is `"provider:model"`, split on the **first** colon only — `ollama:qwen2.5:7b`
  is provider `ollama`, model `qwen2.5:7b`.
- `validate_pricing()` skips `openrouter` and `custom`, so `estimate_cost()` returns `0.0`
  for them and **`MAX_COST_PER_SESSION_USD` is a no-op on those providers**. A `$0.00` in
  the UI does not mean a run was free. Cap spend at the provider.
- **Two human gates, one thread.** `plan_gate_node` and `hitl_gate_node` both call
  `interrupt()` on the same LangGraph thread, so which one fired must be *read* off
  `result["__interrupt__"][0].value["type"]`, never assumed — `runner._outcome` does this.
  `resume()` takes exactly one of `approved=` or `plan=` and raises on both/neither: there
  is no safe default, since `approved=True` would approve a draft that does not exist yet.
- **`skip_plan_gate` has three defaults, and they disagree on purpose.**
  `RunConfig.skip_plan_gate` and `ResearchStartRequest.skip_plan_gate` are both `True` —
  the CLI/eval harness can't render a second interrupt, and an un-updated script should
  keep today's journey. `Session.skip_plan_gate`'s column default is `False`, reached only
  by a row created outside the start endpoints, which always set it explicitly. The gate is
  the product default via the run form, which sends `false`. Do not "simplify" these to
  agree — each default serves a different population.
- **Every run limit is `0 = unlimited`, and `0` is the default** — cost, wallclock, and
  `max_input_tokens`. **The rule has two homes** — `graph._over_budget` *and*
  `graph._BudgetGuard.exceeded`; a zero limit reads as "already exceeded" to a naive `>=`,
  which skips every task at zero spend. Change both.
- A guard that fires must say which one, and by how much — `failer_node` reports the
  breach reason; a bare "budget or loop limit exceeded" forces a source read to learn
  which of three numbers was crossed.
- Router aliases (`auto/*`) are **not** pinned models — they resolve differently per call.
  Never treat one as a disclosed model; record what actually answered.

## The research runtime

Runs persist through `app/run_lifecycle.py`.

- **The lifecycle is host-agnostic and lives in one file.** `app/run_lifecycle.py` has no
  FastAPI, no auth and no Redis, because the server router *and* the desktop sidecar both
  call it. `test_host_parity` caught the run routes before they landed on only one host.
- **`app/run_execution.py` is the only bridge from the engine to the domain.** It calls
  `research_engine.runner.run`/`.resume` with the same ports and `RunConfig` the session
  worker uses — nothing in `research_engine/` knows the domain exists. `persist_outcome` is
  the seam: pure over (db, run, outcome, state).
- **Evidence comes from the checkpoint, not from `RunOutcome`.** Evidence and
  contradictions live in the LangGraph state, which is why the session bundle route reads
  them there too. The adapter reads the final state once, through the tri-state reader
  (`research_engine/checkpoint_read.py`); after that the `evidence` table is authoritative.
- **Never read a checkpoint through `app.services.checkpoints.get_thread_state`** — it
  returns `snapshot.values if snapshot else {}`, so "no checkpoint" and "empty checkpoint"
  collapse to one value. The tri-state reader exists to keep them apart; the production
  helper stays as-is, since changing it would alter session semantics.
- **Whether the evidence was read is stored, not inferred.** `research_runs.evidence_outcome`
  is `READ`, `CHECKPOINT_MISSING`, `CHECKPOINT_UNREADABLE` or `NOT_READ`, and `run_bundle`
  refuses to assemble on either failure state. Without it, "0 evidence" read from the tables
  alone is not a measured fact — an unreadable checkpoint and a run that genuinely found
  nothing look identical, and only one of them may be exported as a bundle.
- **Two tables carry a polymorphic reference and therefore no foreign key**:
  `agent_logs.session_id` and `memory_chunks.source_report_id`, each of which can name a
  `sessions.id` or a `research_runs.id`, and an FK can only point at one. Deletion is the
  ORM's job — a relationship on `Session`, and an explicit delete in
  `run_lifecycle.delete_run`. Add a third such column and it needs both.
- **`app/run_bundle.py` is the one bundle assembler**, and `research_engine/verify_bundle.py`
  is the one checker. A private copy of the checks would verify a bundle against the
  assembler's own idea of validity.
- **Artifact authorization goes through `app/authorization.py`.** Never re-derive
  `gate == 'REPORT' and decision == 'APPROVED'` at a call site. It is enforced four times
  and all four must move together: the database (`fk_artifact_review` + `ck_artifact_gate`),
  that module, the bundle assembler, and `verify_bundle`. The serialization layer looks
  redundant and isn't — the verifier's load-bearing check is `action == "approved"`, and it
  rejects `plan_approved` only because the two serialize differently, so an assembler
  mapping every APPROVED review to `"approved"` would authorize a plan approval that no
  constraint reaches.
- **Project memory is pgvector-only**, so it exists on the server and not on the desktop.
  `memory.is_available(db)` is the one home for that check; a caller writing its own dialect
  test is a caller that will disagree with it.

**Never run a planted-failure sweep and a validation run at the same time** — sweeps mutate
source files in place and restore them after; one killed by a timeout leaves the plant
*active* and can produce entirely fictional findings. Run sweeps in the foreground, one at
a time, and `grep -rn PLANT` before trusting any number.

## Working with the ORM

Do not load a list of ORM rows and then roll back inside the loop — the rollback expires
*every* object in the identity map, including ones not yet processed, so the next
iteration dies on attribute access outside the greenlet. Read ids, then re-read each row
inside its own attempt.

The same expiry bites a *request* handler that rolls back after committing: anything read
off an ORM row afterwards reloads lazily, outside the greenlet, and turns a best-effort
failure into a 500 on work that already succeeded. Build the response before the
best-effort step, not after it — `runs.submit_report_review` is the worked example.

## Never fake, never swallow

- No `print` in application code — `structlog.get_logger()`, correlation bound to
  `session_id` (see `backend/AGENTS.md`).
- A caught provider error must surface its message. `graph.py::_structured` once swallowed
  an exception into `None`, producing "planner: could not produce a valid task list" for
  what was actually an exhausted quota.

## Comments explain intent, not syntax

Every file here is held to the same standard: a comment earns its place by telling a
competent engineer something the code cannot tell them by itself. Most lines need nothing.

**A comment must explain at least one of:** what a non-obvious function/section is
responsible for; why it exists rather than a simpler alternative; an architectural
invariant it protects; a failure-handling decision; a security or isolation constraint; a
performance/compatibility constraint; a domain-semantics distinction the type system
doesn't carry (retrieved ≠ cited, UNCHECKED ≠ ATTESTED); or an assumption the code relies
on that isn't visible at the call site.

**Forbidden:** narrating syntax; a comment on every line to raise a coverage number;
restating the function name in prose; an invented historical justification ("fixes bug
#123") that stops being useful the moment the ticket closes — write the durable invariant
instead; a comment describing behavior the code next to it no longer has. A stale comment
is worse than none, because it is trusted.

**When you change behavior, update the comment in the same change** — a comment is a claim
about the code, and an unupdated one misleads the next reader with confidence. This applies
equally to this file and `backend/AGENTS.md`/`frontend/AGENTS.md`.

**Before adding a comment, ask whether the code already says it.** This repository's
density is high on purpose (`research_engine/graph.py`, `app/run_lifecycle.py` are the
reference examples), so a marginal comment needs to work harder to justify itself. A
function that already explains itself through its name, types, and one clear surrounding
comment needs no second one.

## What CI actually enforces

Green locally ≠ green in CI. Run what CI runs:

```bash
cd backend && ruff check app/ research_engine/ tests/ evals/ && ruff format --check app/ research_engine/ tests/ evals/ && python -m pytest
cd frontend && npm run lint && npm run typecheck && npm test && npm run build
```

Backend lint **includes `evals/`** and excludes `desktop/`, `alembic/`, and repo-root
scripts. A lint-clean `app/` is not a green build.

Frontend CI also runs four bespoke greps (`.github/workflows/ci.yml`): no raw-HTML React
escape hatches, no hardcoded hex colors, no hardcoded backend URLs, no web-storage access
without an inline `ci-allow-web-storage: <reason>` marker.

- **Those greps are GNU grep, and your shell's `grep` may not be.** On a machine where
  `grep` resolves to `ugrep` — alias, shim, shell function — it can report *no match where
  CI finds one*. Verify with `/usr/bin/grep`, running the `ci.yml` commands verbatim.
- **The guards cannot tell a use from a mention** — a *comment* naming a banned token fails
  the build as surely as calling one (`main` was red for a fortnight over prose explaining
  which APIs are banned). Describe the rule without writing the names.
- A raw control character in a source file compounds this: GNU grep prints
  `Binary file … matches` instead of the offending line, hiding which line was wrong.
  Encode it as an escaped four-character sequence in source, not as a literal embedded byte.
- **Not every red `main` is a red commit.** `backend/requirements.txt` floats C extensions
  (`lxml>=5.2`) with no system `libxml2` on Windows; if pip picks a version with no Windows
  wheel yet, the source build dies naming a missing compiler header — that reads like a
  toolchain break but is a packaging race that resolves itself once the wheel lands.
  **Before believing a Windows-only dependency failure, check whether the same job passed
  on the PR head** — a pass there and a failure here is the environment, not the diff. That
  is the one case worth a single re-run; a second failure is real.

**Every apt install goes through `.github/actions/apt-install`.** A raw `apt-get`
reintroduces the hang it exists to bound — the same install once sat in three workflow
files and wedged five jobs simultaneously (one for 90 minutes) while others ran it in
seconds; a stalled mirror connection never returns, and the job burns its whole timeout
naming nothing. The action tries, in order: skip if `dpkg -s` says the packages are already
there (measured: true for the WeasyPrint pair on `ubuntu-latest`, clearing in under a
second with no network touched); install from the image's existing index; only then
refresh, bounded and retried, repointed at `archive.ubuntu.com`. It never changes *which*
packages are installed.

**The Playwright browser is the other unbounded fetch, and it is cached now** — ~184 MB of
Chrome from `cdn.playwright.dev` once wedged a runner for 3h40m against a normal 17s.
`golden-e2e` restores `~/.cache/ms-playwright` keyed on the resolved `@playwright/test`
version, and the install step carries a `timeout-minutes`. **`--with-deps` was hiding a raw
`apt-get` inside that same step** — it shells out to apt internally, so the fetch's budget
was covering a CDN download *and* an unbounded package install. `golden-e2e` now installs
libraries through the composite action and runs `playwright install chromium` without the
flag, so each bound guards one thing; the package list comes from
`npx playwright install-deps --dry-run chromium`.

**Size a bound against what it guards, not against the happy path.** The apt action's
per-attempt timeout is now **900s** — a full index refresh legitimately runs minutes, and
the WebKitGTK/GTK dev chain (~150 packages) can die mid-download well past 180–300s of
steady progress. The step's own `timeout-minutes` must be sized from `attempts ×
(update + install)`, not guessed — a 12-minute cap once burned attempt 1 plus the start of
attempt 2 and reported only "step timed out," naming neither stage and making the retry
dead code. Both ceilings are **35 minutes** now. A bound meant to catch a dead connection
must sit above the slowest *working* case; there is an order of magnitude of headroom
between a working install and the 90-minute stalls it guards against.

**The tell that a bound is too tight rather than a mirror being dead:** the job passes on
the commit before and fails on this one with no relevant diff. A real hang is reproducible
and names nothing; a bound straddling the working case alternates. Neither is a flake to
re-run away — the first is an outage, the second is a number to fix.

## A release is not finished until the website says so

The public site (`frontend/app/(site)/`, GitHub Pages) is **generated from the app** — the
docs it renders are `docs/`, the comparison is `lib/comparison.ts` — so it cannot drift
about *how the product works*. Three things are hand-written and go stale silently:

| After tagging a release | Update | Why it rots |
|---|---|---|
| Always | `frontend/lib/releases.ts` | The releases page and "what improved" list. The download button reads `latestRelease()`, so a missing entry offers the *previous* installer. |
| Always | `README.md` download badge | Bump **both** the badge label and the href; it once pointed at v1.0.1 while v1.0.2 was current. |
| When behaviour changed | `README.md` pipeline diagram, `lib/comparison.ts` | The diagram claimed one human gate for weeks after the design gate shipped. |

**The generated pages are safe; the hand-written data next to them is not.** Check every
page after a deploy, not just the one you changed: `/`, `/why`, `/docs`, `/releases`,
`/download` — they share a layout and nav, so a change to either breaks all five.

**Pages-specific traps, all of which have bitten:**

- The site is served from `/<repo>/`, not a domain root. `basePath` covers `<Link>` and
  Next's own assets but **not** `metadata.icons` — the favicon 404'd at the domain root
  while the file served fine one level down.
- `build` and `deploy` are separate jobs in `pages.yml`. Re-running after a failed deploy
  re-uploads the artifact and `deploy-pages` refuses with `Artifact count is 2` — the retry
  for a transient outage is itself guaranteed to fail.
- `.nojekyll` is mandatory — Pages runs Jekyll by default and silently drops every path
  starting with an underscore, which is all of `_next/`.
- `build:pages` must **not** run `prepare-session-routes` — it recreates
  `app/(app)/session`, whose web variant has no `generateStaticParams` and fails the export
  outright.

## Local development

- Whole stack: `./start.sh` (Docker; `--fake` for a keyless demo, `--stop`, `--reset`).
- Frontend dev port is **3031**, not 3000. `FRONTEND_URL` in `.env` is the CORS allow-list
  and must match, or the API rejects the browser.
- The frontend container is a **static `next build` image**, not a bind-mounted dev
  server: source edits need `docker compose -f docker-compose.full.yml build frontend`,
  not a page reload.
- Postgres must be a **pgvector** image — migration 0006 enables the extension and 0007
  creates a vector column, so stock Postgres fails `alembic upgrade head` outright.
- Research and chat rate limits default to **0, which means unlimited**
  (`research_rate_limit_per_hour` / `chat_rate_limit_per_hour` in `app/config.py`). If you
  set a non-zero value, it is enforced before model routing is consulted.

## Skills worth reaching for

All of these are already available in this environment — nothing to install.

| Working on | Skill |
|---|---|
| Anything, before debugging | `superpowers:systematic-debugging` |
| New feature or bugfix | `superpowers:test-driven-development`, `ecc:tdd-workflow` |
| `app/api/`, routes, dependencies | `ecc:fastapi-patterns`, `/ecc:fastapi-review` |
| `research_engine/`, engine internals | `ecc:python-patterns`, `/ecc:python-review` |
| Retrieval, chunking, memory | `ecc:iterative-retrieval`, `ecc:rag-pipeline` |
| `evals/`, measurement claims | `ecc:eval-harness`, `ecc:benchmark-methodology` |
| Model routing, spend | `ecc:cost-aware-llm-pipeline`, `ecc:token-budget-advisor` |
| Alembic, schema changes | `ecc:database-migrations`, `ecc:postgres-patterns` |
| Celery, queues, caching | `ecc:redis-patterns` |
| `frontend/` components | `ecc:react-patterns`, `/ecc:react-review` |
| Frontend tests | `ecc:react-testing`, `ecc:e2e-testing` |
| Contrast, keyboard, ARIA | `ecc:frontend-a11y`, `ecc:accessibility` |
| Auth, SSRF, secrets | `ecc:security-review`, `/ecc:security-scan` |
| Compose, images, deploy | `ecc:docker-patterns`, `ecc:deployment-patterns` |

## Housekeeping

Runtime artifacts must not be committed. `data/corpus/*.sqlite`, `__pycache__`, `.venv`,
`.next`, and tool directories (`.qoder/`) are ignored — but an ignore rule does not
untrack a file that is already tracked. `corpus_dir` defaults to the **relative** path
`data/corpus`, so running from the repo root and from `backend/` creates two different
corpus roots.

## Project Governance

Before making substantial changes, read:

- `docs/governance/Multi-Agent-Research-Assistant-Open-Source-Constitution.md`

This defines the open-source engineering and maintainer rules.

**Two research pipelines exist in the backend, and the product has one.** Runs are the
product; research recorded earlier as sessions stays readable, chattable and exportable, and
nothing in the interface offers a second way to start research. Consolidating the two is a
milestone, not a patch — the session tables hold users' history, and follow-up chat scoped
to a single report only exists there. Do not deepen the session path; do not delete it
either.
