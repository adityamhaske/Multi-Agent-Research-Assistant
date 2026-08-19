# Agent guidance — repository root

Read this first. Package-specific traps live in [`backend/AGENTS.md`](backend/AGENTS.md)
and [`frontend/AGENTS.md`](frontend/AGENTS.md); read the one you are about to touch.

**Keep this file current.** It describes traps, not features. When a change invalidates a
rule here, update it in the same commit — a stale rule is worse than no rule, because it
gets trusted. Add a rule only after something has actually bitten; this is not a style
guide.

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
one.** A citation that cannot be resolved must render its ⚠ unverified chip rather than
render clean. An eval or benchmark that could not measure something must say so — never
print `0.0`, never record a model id you did not actually call, never score a baseline
against placeholder text.

This has been violated before. In August 2026 a benchmark shipped that published all-zero
results as findings, recorded `claude-sonnet-4-6` in every trace while calling
`claude-3-5-sonnet-20241022`, and scored the competing baseline against the literal string
`"Content extracted by gpt-researcher"`. If you touch `backend/evals/`, re-read
`benchmark.py`'s `_build_judge` and `calc_support_rate` and preserve the distinction
between *unmeasured* and *zero*.

That fix landed in `benchmark.py` and **was never propagated to `harness.py`**, which is
what actually produces every committed `eval-*.json`. Until M18, its
`judge_citation_support` divided by *all* cited claims while a provider error, a partial
model reply, and an unparseable answer each silently contributed a miss — so an exhausted
quota was indistinguishable from a quality collapse. Both files now exclude unjudged
claims from the denominator and return `None` when nothing was judged. They remain two
homes for one rule: **change both.**

**A committed eval result is evidence, and evidence is write-once.** `cbde168` — a
frontend commit — overwrote `eval-2026-08-13.json`, destroying a real 10/10 `ollama` run
and leaving the README citing numbers whose proof no longer existed. Nothing failed and
nothing warned; the measurement was recoverable only from git history. Never modify a file
under `backend/evals/results/`; add a new one named `eval-<date>-<routing>-run<N>.json`,
because a date alone is not a run identity. CI enforces this (`ci.yml`, job
`eval-artifacts`).

## Docs are the build contract

`docs/` is authoritative — see [`docs/00_INDEX.md`](docs/00_INDEX.md). Code that
contradicts the docs is wrong; docs that contradict shipped code must be fixed **in the
same PR** that changed the behavior. Nothing aspirational: every statement describes what
is built, or is explicitly marked `[PLANNED]`.

Cite the doc section in code comments when encoding a decision from it (`docs/13 §6`), the
way the existing code does. That is how a reader knows a line is deliberate.

**Documents are cited by number, and the number is stable.** A file under `docs/` keeps its
numeric prefix as its identity — hundreds of source comments say `docs/04 §6` — while the
directory, the filename, and the published URL are free to change. Reading order comes from
`NAV_ORDER` in `frontend/lib/docs.ts`, keyed by the published slug, which is the filename
with the prefix stripped. Renumbering a document silently invalidates every comment that
cites it; renaming or moving one does not.

**`docs/` is the published tree.** The site walks all of it at build time, so anything filed
there gets a URL. Engineering notes, milestone plans and release checklists therefore live in
[`internal/`](internal/README.md) instead, which the site never walks at all — still the
strongest guarantee, because it does not depend on anyone maintaining a list.

Inside `docs/`, publication is decided **per directory** by `classifyDir` in
`frontend/lib/docs.ts`: `CATEGORY_ORDER` publishes, `UNPUBLISHED_DIRS` withholds
(`governance/`, `plans/`, `screenshots/`), and a directory in neither **fails the build**
with a message naming both remedies. Absence from `CATEGORY_ORDER` alone is *not* a
guarantee — it hides a directory from the sidebar while `generateStaticParams` still
generates its routes.

This was a per-*file* denylist naming two exact paths until M0B, so a second document
filed under `docs/plans/` was published at a URL nothing linked to. Verified, not assumed:
a planted note under `docs/plans/` exports at `/docs/plans/<name>/index.html` on the old
code and is absent on the new. `frontend/lib/docs.test.ts` is the regression guard, and
CI now runs `build:pages` and greps the export for governance and planning routes.

## Configuration has two paths, and they drift

The same `RunConfig` is built by two independent code paths. **Change one, change both**,
or the CLI and the server silently disagree:

| Path | Built by | Used by |
|---|---|---|
| Server | `app/runtime.py` ← `app/config.py` (pydantic-settings) | API, Celery worker |
| Local | `research_engine/local.py::run_config_from_env` ← `os.environ` | CLI, eval harness, benchmark, desktop sidecar |

This has drifted twice. The local path once knew only Google/Anthropic/OpenAI keys, so
OpenRouter was unreachable and a `custom:` route silently fell through to
`api.openai.com`. It also defaulted `enforce_ssrf_guards` to `True`, applying the
production guard to a laptop and rejecting every local model server.

**Local endpoints:** `research_engine.llm_factory.map_local_host()` is the single
implementation that rewrites `localhost` → `host.docker.internal` inside a container. Use
it; do not re-implement it. Three copies of this logic existed once and two were wrong.

## The recurring bug: two hosts, one contract

Server and desktop are **parallel implementations of the same contract**. Every shared
behaviour has two homes, and the second one gets forgotten. Not hypothetical — each of
these was found in shipped code, not imagined:

> **The frontend now has three build targets, not two.** `next.config.ts` branches on
> `NEXT_PUBLIC_PAGES` (static export for GitHub Pages, `basePath` set), then
> `NEXT_PUBLIC_DESKTOP` (static export for Tauri), then the standalone server image. A
> flag read at build time collapses to dead code in the other two, which is what keeps
> them isolated — but it also means **a branch is only exercised by the target that
> builds it**. `npm run build`, `build:desktop` and `build:pages` are three separate
> checks, and CI runs the first two. Anything touching `app/(site)/` or `app/layout.tsx`
> needs all three run locally.

| Behaviour | Copies | How many were wrong |
|---|---|---|
| `localhost` → `host.docker.internal` | 3 | 2 |
| Request fields reaching `Session(...)` (`corpus_mode`, `demo`) | 3 | 3 |
| Resolving `corpus_dir` | 2 | 2 — both relative, so upload and run disagreed |
| Validating a `provider:model` route | 2 | 1 — routing accepted what pricing refused |
| Where the bundled sidecar lives | 3 | 3 — see below |

**When you change any of these, grep for the other copy before you finish:**

- Config → `app/runtime.py` *and* `research_engine/local.py`
- Request → session → `app/api/v1/research.py` *and* `desktop/sidecar.py`
- Per-session run config → `app/workers/pipeline_runner.py` *and*
  `desktop/sidecar.py::_drive_session`
- A new `RunOutcome.status` → `pipeline_runner::_persist_outcome` *and* **both** dict
  literals in `sidecar::_apply_outcome` (status map and lifecycle-event map). A missing
  key there raises inside a background task, so the session sits on RUNNING forever with
  nothing in the log to say why
- A new pause event → the stream's stop-list in `app/api/v1/research.py` *and*
  `sidecar::_TERMINAL_EVENTS`; a stream left open on a suspended graph waits on no one
- Route validation → `app/services/model_routing.py::validate` *and*
  `research_engine/llm_factory.py::validate_pricing`
- Unmeasured-vs-zero in the support rate → `evals/harness.py::judge_citation_support`
  *and* `evals/benchmark.py::calc_support_rate`
- Embedder locality → every `Embeddings` adapter must expose `is_local`
  (`research_engine/embeddings.py`, `app/adapters.py`); the corpus airgap guard reads it
  and **defaults to remote** for anything that does not declare itself

**A test that stubs the thing it is testing proves nothing.** `test_corpus_egress.py`
asserted zero network calls in corpus mode while injecting a `FakeEmbeddings` — and the
query embedding was the only call that egressed, so the suite was green precisely because
it had replaced the defect. When writing a test for an *absence* (no egress, no writes, no
spend), check what the fixtures replaced: if the mechanism under test is the thing you
mocked, the test is decorative.

The second instance was worse, because the fake behaved *better* than the real thing.
`migration/checkpoint.py` exists to keep a missing checkpoint distinct from an empty one,
and its tests used a `FakeSaver` that raises on corruption. A real LangGraph saver does
not: a damaged blob still deserialises — to the integer `0` — so the reader returned
"read it, no evidence" for a checkpoint it had not read at all. The tri-state was
reintroduced one level below where it was fixed, and only running the migration against a
real `AsyncSqliteSaver` (M2E-2's dry run) found it. **A decode that does not raise is not
a decode that succeeded**: check the shape you got back, not just the absence of an
exception.
- Schema → an Alembic migration for Postgres *and* the ORM model, which is what the
  desktop's `create_all` plus startup column sync reads
- Report chat → `app/api/v1/chat.py` *and* `desktop/sidecar.py`. The sidecar had **no
  chat routes at all** for a whole release while the desktop build rendered
  `ChatPanel.tsx` and POSTed to one — a shipped control that 404'd. Three things differ
  between the copies and nothing else should: keys come from the keychain rather than a
  decrypted column, there is no rate-limit dependency (it needs `get_current_user` and
  Redis, and the desktop has neither), and the corpus is one `corpus.sqlite` for the
  whole app rather than one file per project. **Project chat (`/threads`) is desktop-
  absent by design** — project memory is pgvector-only
- Bundle export → `app/api/v1/research.py::export_bundle_json` *and*
  `desktop/sidecar.py::export_bundle_json`. Same failure shape as report chat, found by
  the V1→V2 audit and fixed in M0C: the endpoint shipped in v1.0.0, the desktop host
  served no route for it, and **no UI anywhere reached it on either host** while four
  surfaces advertised it. Four things differ between the copies and nothing else should:
  the checkpointer is SQLite rather than Postgres, there is no `crypto.decrypt` step, the
  report is read directly rather than through the server-only `_report_or_404` (its
  demo rule is reproduced inline), and `trace_available` is `True` on both.
  **A bundle route is only correct if what it emits verifies** — the sidecar wrote no
  `audit_log` row at either gate, so adding the route alone would have produced bundles
  that always fail `approval_chain`. `tests/test_bundle_export_routes.py` pins the whole
  chain, including that planted failure
- Sidecar location → `desktop/tauri.conf.json` (`bundle.resources`), `desktop/src/lib.rs`
  (`sidecar_command`), *and* `.github/workflows/desktop.yml` (the `shell` job must
  `needs: sidecar` and download the artifact)

That last row is the worst case so far, because all three copies were wrong at once and
nothing failed until someone ran the build: `tauri.conf.json` had no `resources` key, so
the sidecar was never copied in; `lib.rs` looked for it next to the executable, which is
not where `resources` puts it; and the CI `shell` job raced `sidecar` instead of depending
on it, so even a correct config would have bundled nothing. The result was a 5 MB `.app`
that passed CI, uploaded cleanly, and died on first launch. **A desktop bundle that has
not been launched is not verified** — check the artifact is ~180 MB, not ~5 MB.

The failure mode is always the same: the server path is exercised constantly, the desktop
path only at release time, so a divergence ships. Prefer extracting the shared logic into
one function over keeping two copies in step by discipline — `map_local_host` is the
worked example of doing that after the fact.

**`tests/test_host_parity.py` is now the enforcement.** Added in M1, before any extraction,
because a refactor without a contract test just moves the drift. It holds four tables and
fails if any of them rots:

| Table | Means |
|---|---|
| `INTENTIONAL_SERVER_ONLY` | The route legitimately has no desktop equivalent, with the reason |
| `INTENTIONAL_DESKTOP_ONLY` | The reverse |
| `DESKTOP_UI_CALLS` | Every path the desktop build actually calls — the sidecar must serve all of them |
| `KNOWN_DESKTOP_GAPS` | Paths the UI calls and the sidecar does **not** serve, i.e. controls that 404 today |

A route on one host and not the other must appear in one of them or the suite fails; an
entry that no longer describes reality also fails, so the lists cannot become a description
of the past.

**`KNOWN_DESKTOP_GAPS` is empty and must stay empty.** M1 found six live 404s — the Stop
button, four per-project `corpus` paths, and Settings' usage panel — and M1.5 closed all of
them plus a seventh M1 had misfiled (the corpus document *download* path, listed as an
intentional difference on the mistaken belief the UI did not call it; `documentUrl()` builds
it for both the Corpus page and the report preview). An entry in that table is a control
that ships broken.

The corpus fix is the pattern to copy. The desktop keeps one `corpus.sqlite` for the whole
app while the server scopes one per project — a real infrastructure difference that stays.
What was wrong is that it had leaked into the client, so the sidecar now serves the
**per-project path as the canonical contract** and resolves it to its own flat store. No
`isDesktop` branch was added. Prefer that shape: one product contract, different internals,
rather than teaching the frontend about a storage decision.

Two things this deliberately did *not* fix, both shared by the two hosts: cancel is
advisory (neither host's outcome writer checks status before persisting, and the server's
Redis `cancelled` key is read by nothing), and the desktop `.md` export still does not
demo-stamp while the server's does.

The suite also pins the two traps this table already warned about in prose: every
`RunOutcome.status` must appear in `sidecar::_apply_outcome`, and every event in
`sidecar::_TERMINAL_EVENTS` must appear in the server's stream stop-list.

## Provider and cost rules

- Routing is `"provider:model"`, split on the **first** colon only — `ollama:qwen2.5:7b`
  is provider `ollama`, model `qwen2.5:7b`.
- `validate_pricing()` skips `openrouter` and `custom`, so `estimate_cost()` returns `0.0`
  for them and **`MAX_COST_PER_SESSION_USD` is a no-op on those providers**. A `$0.00` in
  the UI does not mean a run was free. Cap spend at the provider.
- **Two human gates, one thread.** `plan_gate_node` and `hitl_gate_node` both call
  `interrupt()` on the same LangGraph thread, so which one fired must be *read* off
  `result["__interrupt__"][0].value["type"]`, never assumed — `runner._outcome` does
  this. `resume()` therefore takes exactly one of `approved=` or `plan=` and raises on
  both/neither: there is no safe default, since `approved=True` would approve a draft
  that does not exist yet and `False` would count a phantom rework.
- **`skip_plan_gate` has three defaults, and they disagree on purpose.**
  `RunConfig.skip_plan_gate` is `True` — the CLI and the eval harness cannot render or
  resume a second interrupt, so an unattended run must never stop at one.
  `ResearchStartRequest.skip_plan_gate` is also `True`, so a script POSTing an
  un-updated body keeps today's journey. `Session.skip_plan_gate`'s column default is
  `False`, but both start endpoints always set it explicitly, so it is only reached by a
  row created outside them. The gate is the product default via the *run form*, which
  sends `false`. If you "simplify" these to agree, you break one of the three
  populations.

**Every run limit is `0 = unlimited`, and `0` is the default** — cost, wallclock, and
  `max_input_tokens`. The token ceiling used to be a hardcoded `1_000_000` inside
  `graph._over_budget`, unreachable from any config; since the dollar cap is inert on
  `openrouter`/`custom`, it was the only guard that could fire, and a real run died at
  1,003,721 input tokens with no way to raise it. **The rule has two homes** —
  `graph._over_budget` *and* `graph._BudgetGuard.exceeded`; a zero limit reads as "already
  exceeded" to a naive `>=`, which skips every task at zero spend. Change both.
- A guard that fires must say which one, and by how much. `failer_node` reports the breach
  reason; a bare "budget or loop limit exceeded" made a user read the source to learn
  which of three numbers had been crossed.
- Router aliases (`auto/*`) are **not** pinned models: they resolve differently per call
  and the alias can disagree with what served the request. Never treat one as a disclosed
  model — record what actually answered.

## The V2 native runtime

New runs persist through `app/v2_runtime.py`; migrated runs go through `migration/engine.py`.
Both write the same tables, and the rules below hold for both — a native run must not be able
to record something a migrated one is refused.

- **The lifecycle is host-agnostic and lives in one file.** `app/v2_runtime.py` has no FastAPI,
  no auth and no Redis, because the server router *and* the desktop sidecar both call it. The
  V2 routes were added to both hosts in the same commit, and `test_host_parity` caught them
  before they landed — which is the third time that harness has paid for itself.
- **`app/v2_execution.py` is the only bridge from the engine to V2.** It calls
  `research_engine.runner.run`/`.resume` with the same ports and the same `RunConfig` the V1
  worker uses — nothing in `research_engine/` knows V2 exists, and it must stay that way.
  `persist_outcome` is the seam: pure over (db, run, outcome, state), so the integration test
  drives the real graph and then calls it directly.
- **Evidence comes from the checkpoint, not from `RunOutcome`.** The outcome carries the
  report, the numbered sources and the metrics; evidence and contradictions have always lived
  in the LangGraph state, which is why the V1 bundle route reads them there too. The adapter
  reads the final state once, through the tri-state reader, and after that the `evidence`
  table is authoritative.
- **`agent_logs.session_id` has no foreign key.** It is polymorphic across `sessions.id` and
  `research_runs.id`, because an FK can only point at one of them — and before `0018` a
  V2-native run could not write the trace its bundle's `trace_available` claims. Deletion is
  cascaded by the ORM relationship on `Session`, not by the database.
- **`app/v2_bundle.py` is the one bundle assembler.** `migration/bundle_equivalence` delegates
  to it. If they ever diverge, "the migration produces the same bundle the product does" stops
  being a measurement and becomes a coincidence.
- **Artifact authorization goes through `app/authorization.py`.** Never re-derive
  `gate == 'REPORT' and decision == 'APPROVED'` at a call site.
- **`migration_ledger` is a model, not a tool artifact.** It lives in `app/models/` because the
  product reads it: `v2_bundle` consults `evidence_outcome` before claiming a run gathered no
  evidence. `migration/ledger.py` re-exports the names.

**Never run a planted-failure sweep and a validation run at the same time.** The sweeps mutate
source files in place and restore them afterwards; a dry run executed in that window measures
planted code. Worse, a sweep killed by a timeout leaves the plant *active* — an F4 plant
(`sequence=1`) survived a killed background sweep and produced two convincing-looking
"dialect divergences" that were entirely fictional. Run sweeps in the foreground, one at a
time, and `grep -rn PLANT` before trusting any number.

## The V1 → V2 migration

`backend/migration/` is a tool, not a service. Three rules it has already cost something to
learn (`internal/V2_Migration_Validation_M2E3.md`):

- **Never read checkpoints through `app.services.checkpoints.get_thread_state`.** It returns
  `snapshot.values if snapshot else {}`, so "no checkpoint" and "empty checkpoint" are the
  same value. The migration has its own tri-state reader; the production helper stays as it
  is, because changing it would alter V1 semantics.
- **`EMPTY`, `CHECKPOINT_MISSING` and `READ_FAILURE` all produce a V2 run with zero
  evidence.** Nothing in the V2 domain tables distinguishes them — only `migration_ledger`
  does. That is why the ledger outlives the migration, and why "0 evidence" read from V2
  alone is not a measured fact.
- **Artifact authorization is enforced four times, and all four must move together.** Only
  an APPROVED **REPORT** review may authorize a `ResearchArtifact`. The database says so
  (`fk_artifact_review → reviews(id, decision, gate)` plus `ck_artifact_gate`), `app/authorization.py`
  says so, the bundle assembler says so, and `verify_bundle` says so. The serialization layer
  is the one that looks redundant and is not: the verifier's load-bearing check is
  `action == "approved"`, and it rejects `plan_approved` only because V1 uses a distinct
  string — so an assembler that mapped every APPROVED review to `"approved"` would authorize
  a plan approval in a JSON file no constraint reaches. Relaxing `reviews.revision_id`
  without the gate column would have opened exactly that hole.
- **The CLI never reads `DATABASE_URL`.** `--database-url` is required, writing additionally
  needs `--confirm-database NAME` matching the DSN, and the dry-run tool refuses any target
  whose `sessions` table is not empty. A tool that defaults to the operator's environment is
  one sourced shell away from migrating production.

Do not load a list of ORM rows and then roll back inside the loop: the rollback expires
*every* object in the identity map, including the ones not processed yet, so the next
iteration dies on attribute access outside the greenlet. Read ids, then re-read each row
inside its own attempt.

## Never fake, never swallow

- No `print` in application code — `structlog.get_logger()`, correlation bound to
  `session_id` (see `backend/AGENTS.md`).
- A caught provider error must surface its message. `graph.py::_structured` swallowing an
  exception into `None` once produced "planner: could not produce a valid task list" for
  what was actually an exhausted quota, sending debugging in the wrong direction for days.

## Comments explain intent, not syntax

Every file in this repository — `graph.py`, `v2_runtime.py`, `authorization.py`,
`dryrun.py`, `RunWorkspace.tsx`, the Dockerfiles, the regression tests — is held to the
same standard: a comment earns its place by telling a competent engineer something the
code cannot tell them by itself. That bar is deliberately high. Most lines need nothing;
the ones that encode a decision, an invariant, or a scar need real prose.

**A comment must explain at least one of:** what a non-obvious function/section is
responsible for; why it exists rather than a simpler alternative; an architectural
invariant it protects (a project-isolation boundary, a two-hosts-one-contract rule, an
unmeasured-vs-zero distinction); a failure-handling decision (why an error is swallowed,
retried, or propagated); a security or isolation constraint; a performance or
compatibility constraint; a domain-semantics distinction the type system doesn't carry
(retrieved ≠ cited, UNCHECKED ≠ ATTESTED); or an assumption the code relies on that isn't
visible at the call site.

**Forbidden:** narrating syntax (`# loop over users`, `# increment counter`); a comment
on every line to raise a coverage number; restating the function name in prose; an
invented historical justification ("fixes bug #123") that stops being useful the moment
the ticket closes — write the durable invariant instead, the way `map_local_host`
explains *why* the container/host rewrite is needed rather than which PR added it; and a
comment that describes behavior the code next to it no longer has. A stale comment is
worse than none, because it is trusted.

**When you change behavior, update the comment describing it in the same change.** A
comment is a claim about the code; if the code changes and the comment doesn't, the claim
becomes false and the next reader is misled with confidence. This applies to docstrings
and to the prose in this file and in `backend/AGENTS.md` / `frontend/AGENTS.md` equally —
see the standing instruction at the top of this file.

**Before adding a comment, ask whether the code already says it.** This repository's
existing density is high on purpose (`research_engine/graph.py` and `app/v2_runtime.py`
are the reference examples — read one before writing prose elsewhere in the codebase),
so the marginal comment usually needs to work harder to justify itself, not less. If a
review pass turns up a function that already explains itself through its name, its types,
and one clear surrounding comment, adding a second one restating the same thing is noise,
not thoroughness.

## What CI actually enforces

Green locally ≠ green in CI. Run what CI runs:

```bash
cd backend && ruff check app/ research_engine/ tests/ evals/ && ruff format --check app/ research_engine/ tests/ evals/ && python -m pytest
cd frontend && npm run lint && npm run typecheck && npm test && npm run build
```

Note the backend lint path **includes `evals/`** and excludes `desktop/`, `alembic/`, and
repo-root scripts. A lint-clean `app/` is not a green build.

The frontend job also runs four bespoke greps that fail the build (see
`.github/workflows/ci.yml`): no raw-HTML React escape hatches, no hardcoded hex colors,
no hardcoded backend URLs, and no web-storage access without an inline
`ci-allow-web-storage: <reason>` marker.

**Those greps are GNU grep, and your shell's `grep` may not be.** On a machine where
`grep` resolves to `ugrep` — a shell function, an alias, a Homebrew shim — it can report
*no match where CI finds one*. A whole session's worth of "all four greps clean" was
wrong for exactly this reason while `main` sat red. Verify with `/usr/bin/grep`, running
the commands from `ci.yml` verbatim.

**The guards cannot tell a use from a mention.** They are plain greps over source, so a
*comment* naming a banned token fails the build as surely as calling one. `main` was red
for a fortnight because `DocumentPreview.tsx` explained, in prose, which two APIs are
banned. Describe the rule without writing the names; that file now says so in place.

A raw control character in a source file compounds this: GNU grep prints
`Binary file … matches` instead of the offending line, so the failure names the file and
hides the reason. Prefer a `\u0000` escape sequence over an embedded NUL byte.

## A release is not finished until the website says so

The public site (`frontend/app/(site)/`, published to GitHub Pages) is **generated from
the app**, so it cannot drift about *how the product works* — the docs it renders are
`docs/`, the comparison is `lib/comparison.ts`. But three things on it are hand-written
and go stale silently, because nothing fails when they do:

| After tagging a release | Update | Why it rots |
|---|---|---|
| Always | `frontend/lib/releases.ts` | The releases page and its "what improved" list. The download button reads `latestRelease()` for its version, so a missing entry also means the button offers the *previous* installer. |
| Always | `README.md` download badge | Bump the version in **both** the badge label and the href; it once pointed at v1.0.1 while v1.0.2 was current. |
| When behaviour changed | `README.md` pipeline diagram, `lib/comparison.ts` | The diagram claimed one human gate for weeks after the design gate shipped. |

The predecessor of this site was one hand-maintained `site/index.html`. It described a
product that no longer existed, and nobody noticed, because updating it was a separate
act of memory from changing the code. That is the failure this section exists to prevent
— **the generated pages are safe; the hand-written data next to them is not.**

Check every page after a deploy, not just the one you changed: `/`, `/why`, `/docs`,
`/releases`, `/download`. They share a layout and a nav, so a change to either breaks all
five at once.

**Pages-specific traps, all of which have bitten:**

- The site is served from `/<repo>/`, not a domain root. `basePath` covers `<Link>` and
  Next's own assets but **not** `metadata.icons` — the favicon shipped pointing at the
  domain root and 404'd while the file itself served fine one level down.
- `build` and `deploy` are separate jobs in `pages.yml`. In one job, re-running after a
  failed deploy re-uploads the artifact and `deploy-pages` refuses with
  `Artifact count is 2` — so the retry for a transient outage is itself guaranteed to
  fail. Pages returned 503 for three deploys straight the day that was found.
- `.nojekyll` is mandatory. Pages runs Jekyll by default and silently drops every path
  beginning with an underscore, which is all of `_next/`.
- `build:pages` must **not** run `prepare-session-routes`: it recreates
  `app/(app)/session`, whose web variant has no `generateStaticParams` and fails the
  export outright.

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
  (`research_rate_limit_per_hour` / `chat_rate_limit_per_hour` in `app/config.py`). They
  were once a hardcoded 5/hour that applied even to a free local model; if you set a
  non-zero value, note it is enforced before model routing is consulted.

## Skills worth reaching for

All of these are already available in this environment — nothing to install. Listed
because a skill nobody remembers exists is the same as one that does not.

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

- `docs/plans/Multi-Agent-Research-Assistant-V2-Master-Plan.md`
- `docs/governance/Multi-Agent-Research-Assistant-Open-Source-Constitution.md`

These define the V2 product direction and open-source engineering/maintainer rules.

The current codebase is V1 heritage. V2 should evolve it rather than blindly preserve or blindly rewrite it.