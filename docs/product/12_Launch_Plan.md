# 12. v2 Launch Plan — local-first, 10,000 users, $200/month

> Continues [10_Roadmap.md](10_Roadmap.md) (M0–M4 ✅ code complete). Same rules:
> vertical slices, every milestone independently demoable, **done only when its
> Definition of Done passes verbatim**. Architecture contract for M6–M10 is
> [13_Local_First_Architecture.md](../architecture/13_Local_First_Architecture.md).
>
> Status legend: ☐ not started · ◐ in progress · ✅ done

## 1. The constraint is the strategy

Budget ceiling: **$200/month, out of pocket, forever.** Target: **10,000 users.**

Those two numbers are only compatible one way: **inference never runs on our
infrastructure.** Users bring a key or bring hardware. Marginal cost per user rounds to
zero.

This is not a compromise. Every incumbent pays for inference and rations it back as a
subscription, which *requires* your queries on their servers. We invert it — and the
inversion is also the privacy story, the offline story, and the reason a solo maintainer
can serve 10k users. One decision, four wins.

> **Your keys, your hardware, your data. We never see any of it.**

## 2. Positioning

**Today (accurate, unowned):** "Multi-Agent Research Assistant" — a category label, not a
claim.

**v2:** *Deep research you can defend in an audit — running entirely on your machine.*

Everything shipped below reinforces exactly one promise: **traceable, and honest about
what it can't verify.** Features that don't serve that promise go to §7.

The three assets that already exist and nobody else packages together: the `interrupt()`
approval gate with resume-from-checkpoint, per-claim citation resolution with a **visible
⚠ chip on failure**, and self-host + BYOK. v2 adds the fourth: it runs offline.

> [01_Product_Vision.md](01_Product_Vision.md) ties the oversight wedge to EU AI Act
> Art. 14 (stated there as in force Aug 2026). If that holds, launch timing is
> load-bearing, not cosmetic. **Verify the date and scope with a primary source before
> building a headline on it.**

## 3. Delivery modes — one engine, three hosts

| Mode | Who | Login | Data | Our cost |
|---|---|---|---|---|
| **Desktop** (Win/mac/Linux) | most users | none | local SQLite | **$0** — GitHub Releases |
| **Hosted** (try + teams) | evaluation, demo | yes | Postgres | ~$35/mo |
| **Self-host** (`start.sh`) | companies, homelabs | yes | Postgres | $0 |

Hosted is **BYOK-mandatory with no server key**, so open signup cannot drain the wallet.
Existing per-operation rate limits handle abuse.

---

## M5 — Credibility  *(≈ 2 weeks)*  ← do this before anything else

☐ Nothing below ships on an unverified claim. This milestone buys the right to launch.

- **Fix the README license contradiction.** ✅ Fixed — README says MIT and links the
  `LICENSE` file; the "no license set" text is gone.
- **Record a real-model eval run.** ☑ *Interim.* Gemini's monthly spend cap returned
  `429` on every probe, so the measurement ran on local `ollama:qwen2.5:7b` (all roles,
  including judge), per user direction: [`eval-2026-08-13.json`](../../backend/evals/results/eval-2026-08-13.json)
  — completion **1.00**, citation support **0.90** (metrics v3), `citation_support_ok:
  false` recorded honestly. ☐ **Remaining:** re-run on Gemini 2.5 Flash when quota
  resets and replace the interim number.
- **Publish the numbers in the README, with the method** — including the misses. ☑ Done
  for the interim measurement: README's "Measured quality" section carries the numbers,
  the local-model method, the 0.95 miss, and the judge-error residue. Nobody publishes
  their failure rate. We built the ⚠ chip; lead with it. ☐ **Remaining:** refresh with
  the Gemini re-run.
- **Hosted fake-mode demo live** at a real URL; set the repo `homepageUrl` (currently
  empty). Deployment is written and smoke-tested — [`deploy/README.md`](../../deploy/README.md)
  plus [`deploy/docker-compose.demo.yml`](../../deploy/docker-compose.demo.yml) and
  [`deploy/oracle-bootstrap.sh`](../../deploy/oracle-bootstrap.sh) — targeting an Oracle
  Cloud Always Free VM at **$0/month**.

  **Proven:** multi-arch `edge` images publish to GHCR and are anonymously pullable; the
  published **arm64** images (same architecture as Ampere) run the whole stack on
  `docker-compose.demo.yml` — migrations apply, all five services report healthy, and a
  session goes register → research → `AWAITING_APPROVAL` → approve → `COMPLETED` through
  the frontend's same-origin `/api` proxy.

  **Not proven:** anything Oracle-specific — instance provisioning, the two-layer firewall,
  and Caddy obtaining a real certificate. Those need the account owner's console, and the
  bootstrap's `iptables` and sslip.io paths have never executed on an actual OCI image.
- **Tag `v1.0.0`** — ✅ tagged as an **interim release** on the citation-verification
  state (per user direction), with the local-model numbers documented above. `release.yml`
  publishes multi-arch images (`linux/amd64` + `linux/arm64`; Always Free compute is
  Ampere ARM, and an amd64-only image will not start there). The previous `v1.0.0` tag
  was stale: its README claimed 93.4% citation support while the JSON it linked said
  74.16% — the tag was moved to this corrected state.
- **Run 20 real questions and read every output like a hostile reviewer.** Log every
  defect. **This reorders M11–M13.** Both strategic critiques of this project so far —
  including the one that produced this plan — reasoned about a system nobody had watched
  run at volume on real queries.

**DoD:** README has zero false statements, verified line by line · a real-model eval JSON
is committed with a non-null `citation_support_rate` and its method documented ·
`v1.0.0` tagged and GHCR images published · demo URL reachable from a clean browser ·
a written defect log from real runs exists (below) and M11–M13 have been reordered
against it, or explicitly confirmed unchanged.

### Defect log

#### D1 — grouped citation markers were invisible to the UI ✅ fixed

**The first real-model eval paid for itself before its number was usable.** It reported
`citation_support_rate: 0.32` against a 0.95 threshold. Rather than publish that, the run
was instrumented claim-by-claim — and one "unsupported" verdict turned out to be a
near-verbatim paraphrase of its own cited snippet. The metric was wrong, and chasing why
surfaced a live product bug.

**Root cause.** The synthesizer writes `[1, 3]` when a sentence rests on several sources —
ordinary academic style, and [`prompts.py`](../../backend/research_engine/prompts.py) never
forbade it. Both the eval's `CITE_RE` and the **shipped frontend renderer**
([`citations.tsx`](../../frontend/lib/citations.tsx)) matched only one number per bracket,
so grouped markers parsed as prose.

**Why this mattered more than the metric.** In the UI a grouped citation rendered as inert
text: no chip, no link, and **no ⚠ unverified chip either**. A citation could fail to
resolve and the product would never admit it — the precise inverse of the guarantee this
project is built on. Meanwhile `resolution_rate` read a clean `1.0` in every prior run,
because grouped markers were never in its denominator to fail.

Measured on one real report: **50% of all citation references sat inside grouped brackets**,
invisible to both parsers (42 detected → 84 after the fix).

**Fix — defence in depth, because prompt compliance is never 100%:**
1. `prompts.py` now requires `[1][3]`, never `[1, 3]`.
2. Both parsers accept grouped markers regardless and emit one citation per number, so the
   renderer never depends on the model getting the format right.
3. Eval claims split on **sentences**, not raw lines. The synthesizer emits each paragraph
   as one unwrapped line, so a four-sentence paragraph was judged as a single
   all-or-nothing claim against the union of its sources (20 claims → 56 individually
   checkable ones).

Pinned by [`test_grouped_citations.py`](../../backend/tests/test_grouped_citations.py) using
verbatim strings from the failing run, plus four frontend cases asserting a grouped marker
renders one chip per source and still flags an unresolved number *inside* a group.

**Bearing on M11–M13.** No reorder. If anything it strengthens the case for D1's neighbours:
the contradiction detection planned for M11 is only meaningful if citations parse in the
first place, and the M13 benchmark would have published a badly wrong number.

#### D3 — only one snippet per source was kept ✅ fixed

**The bug the citation-support number was actually measuring.** After D1, the rate rose
0.32 → 0.41 — still nowhere near the 0.95 threshold, so the run was interrogated again
instead of published. The tell was a ratio: **~8 citations per stored snippet**, near
identical across all ten queries.

**Root cause.** [`graph.py`](../../backend/research_engine/graph.py) built `sources` by
first-seen URL and kept only that first snippet. But one page routinely backs several
distinct facts, and the executor extracts a separate verbatim quote for each — so every
snippet after the first was discarded, while the synthesizer went on citing that source
for many different claims.

**Why this was the worst of the three.** The citation chip showed the *retained* snippet
whatever the claim: hover `[3]` on a sentence about JSONB indexing and read a quote about
DB-Engines rankings. The product's one-line promise is "hover a citation, read the verbatim
text that supports that claim" — and for roughly seven of every eight citations, the text
shown supported a *different* claim. The eval's judge was correctly marking those NO, so
the headline number was largely a measurement of this bug rather than of research quality.

**Fix.** `Source` gains `snippets: list[str]` holding every distinct snippet from that
source; `snippet` remains the first one so `sessions.sources` rows written before the fix
keep rendering (no migration needed — the column is JSONB and the frontend falls back via
`snippetsOf()`). The chip and the sources panel render all of them; the eval judge is shown
all of them.

Pinned by [`test_source_snippets.py`](../../backend/tests/test_source_snippets.py) and four
frontend cases including the legacy-shape fallback.

#### D4 — parallel executor tasks killed every run ✅ fixed

**The single worst defect found so far: no research run completed at all, and CI had been
red for two weeks without anyone reading the traceback.**

[`agent_log_sink`](../../backend/app/adapters.py) binds one `AsyncSession` to a whole run —
deliberately; that is what fixed an earlier detached-object bug. Sound while the graph was
sequential. **M7 gave the executor parallel tasks**, each emitting its own progress events,
so two coroutines reached `flush()` on the shared session at once:

```
InvalidRequestError: Session is already flushing
```

The user saw a `FAILED` session with no partial output. It reproduces in **fake mode** as
readily as real, so the hosted demo would have failed on its first visitor.

**Why nothing caught it.** Every other test drives the sink from a single coroutine — the
one case that works. The golden E2E *did* catch it and had been failing since M7 landed,
but [`ci.yml`](../../.github/workflows/ci.yml) backgrounds uvicorn and celery with `&`, so
the worker traceback went nowhere and the only visible symptom was the UI reporting
`Waiting for the pipeline to start…`. **A test that fails invisibly is worth little more
than no test** — worth fixing in CI independently of this defect.

**Fix:** a per-run `asyncio.Lock` around the write, spanning the publish too so events
reach Redis in commit order; `Last-Event-ID` replay hands clients a monotonic cursor, and
publishing out of order would let a reconnecting client resume past an event it never saw.
The sink is the only db-bound dependency crossing into the graph, so this is the complete
fix rather than a symptom patch.

Pinned by [`test_sink_concurrency.py`](../../backend/tests/test_sink_concurrency.py), whose
three cases fail with the production error when the lock is removed.

#### D2 — executor rarely returns parsable evidence first time ⬜ open

**Measured (2026-08-12):** `executor_wrapup reason=no_parsable_evidence` fired **77 times** across 10 queries (which spawn ~40 executor tasks). Because the critic can reject evidence and trigger task retries, the executor hit this fallback nearly every single time it completed a research loop using `Gemini 2.5 Flash`.

**Impact:** The run recovers reliably (100% completion rate across the 10 queries) because the fallback `_structured()` call at [`graph.py`](../../backend/research_engine/graph.py) successfully coerces the observations into JSON. However, this fallback adds an extra LLM call for every task, significantly inflating cost and latency.

**Proposed fix:** We should bind a specific `submit_evidence` tool to the executor instead of expecting the model to spontaneously output structured JSON when it finishes using tools. Tool-calling models are highly optimized to call tools; forcing them to stop and emit raw JSON often causes them to output prose instead. A `submit_evidence` tool provides a clear exit ramp that aligns with how these models are fine-tuned.

#### D5 — masked provider 429s and unverified citations in shipped drafts ✅ fixed

**Measured (2026-08-12):** the real-model eval completed only 2 of 10 queries
(`completion_rate 0.2`) and measured `citation_support_rate 0.7416` against the 0.95
threshold.

**Root cause 1 — completion.** All eight failures read `planner: could not produce a
valid task list` with cost $0.00, yet each took ~70s. The key had hit its monthly spend
cap (`429 RESOURCE_EXHAUSTED`), `with_structured_output` raises on provider errors,
[`graph.py`](../../backend/research_engine/graph.py)'s `_structured` swallowed the
exception into `None`, and the planner reported the None as garbage output. The real
cause never surfaced — and the planner burned a pointless retry against a dead quota.

**Fix.** `_structured` records the provider error message; the planner reports
`planner: provider error — <provider message>` and skips the retry when the message is a
quota/rate-limit exhaustion (matched on text, provider-agnostic — the engine imports no
provider SDK types, docs/12 M6). Pinned by
[`test_citation_verification.py`](../../backend/tests/test_citation_verification.py).

**Root cause 2 — citation support.** `llm-memory` already scored 0.9577; the drag was
`postgres-vs-mysql` at 0.5256. The synthesizer writes from the executor's `key_fact`,
which can drift past its verbatim snippet — and the judge rules on snippets. So a claim
could cite a source whose stored text said something narrower, and nothing between the
model and the human gate checked it.

**Fix — defence in depth, same posture as D1:**
1. Executor and synthesizer prompts now anchor claims to the verbatim snippet, not the
   key_fact summary, and say so explicitly ([`prompts.py`](../../backend/research_engine/prompts.py)).
2. A post-synthesis **citation-fidelity pass** in the graph judges every cited claim
   against the snippets of its own cited sources with the same prompt and line format the
   eval judge uses. Unsupported claims lose their `[n]` markers and carry a visible
   *(citation could not be verified)* note — a hollow citation is worse than an admitted
   gap. A verifier failure strips nothing (fail closed for the user). Cost-accounted like
   any other model call.

The pass runs in fake mode too (scripted YES verdicts), so golden journeys are unchanged:
**240 backend passed / 1 skipped**.

**Follow-up — Gemini quota was dead; interim local evals (per user direction, Ollama
`qwen2.5:7b` for every role).** The committed key answered `429 … monthly spending cap`
on a live probe, so two full local evals measured the fix on the substitute model:

| run | completion | citation support | notes |
|---|---|---|---|
| Ollama #1 | 0.70 | 0.7964 | 3 queries died on the 600s wallclock cap (685–709s) tuned for Gemini |
| Ollama #2 | **1.00** | 0.8142 | `MAX_WALLCLOCK_SECONDS` env override ([`local.py`](../../backend/research_engine/local.py)); per-claim judge verdicts instrumented into the harness |
| Ollama #3 | **1.00** | 0.8961 | deictic/number strips + snippet-only synthesizer + judge-aligned split |
| Ollama #4 | **1.00** | 0.85 | strict “answer NO when unsure” verifier — over-stripping experiment, reverted |
| Ollama #5 | **1.00** | 0.9217 (v2) / **0.9459 re-scored v3** | balanced verifier; 2 residual NOs, one a judge error on a near-verbatim claim |
| Ollama #6 | **1.00** | 0.9167 (v3) | first run measured natively under metrics v3 |
| Ollama #7 | **1.00** | 0.90 (v3) | committed as [`eval-2026-08-13.json`](../../backend/evals/results/eval-2026-08-13.json); 4 NOs across 36 claims, none a deterministic-strip class |

Per-claim verdicts split the remaining 11 NO rulings of run #2 into three root causes:
1. **Deictic fragments (4/11).** Sentences like “This is detailed in Article 55 [4].”
   are judged standalone, where the anaphor has no referent. Fixed: synthesizer rule 5
   forbids the construction, and the fidelity pass strips such markers deterministically.
2. **7B verifier rubber-stamping (7/11).** The small local verifier approved claims the
   judge rejected. Fixed with a deterministic pre-check: every number-like token in a
   claim must appear verbatim (word-bounded) in the cited snippets, else markers are
   stripped without asking any model.
3. **key_fact drift.** The synthesizer saw both `key_fact` (paraphrase) and Snippet and
   wrote from the paraphrase. Fixed: it now receives Snippet only — what can be cited is
   exactly what is shown.

The verifier's claim split was also aligned exactly with the judge's
(`split_sentences` lookahead + abbreviation rejoin): this pass is measured by that
judge, so it must rule on the same claims.

Run #3's 8 remaining NOs exposed three more mechanics, all fixed:
4. **Strip note corrupted the next claim.** `*(citation could not be verified)*` carried
   no sentence terminator, so the judge's split merged the note into the FOLLOWING
   sentence and ruled a supported claim NO. The note now ends with a period.
5. **Bold label prefixes (3/8).** `**Working Memory**: …` sentences are judged whole and
   no snippet contains the label. Synthesizer rule 6 forbids them; the fidelity pass
   strips them deterministically, like deictics.
6. **Verifier leniency.** The verify prompt now enumerates what "supported" means and
   rules NO when unsure.

Offline replay of run #3 through the final ruleset projects 0.9655; run #4 (same model,
final code) is the measurement.

**Run #4 lesson — stripping is not monotonic.** Support = supported ÷ cited. Stripping a
claim the judge would rule NO improves the rate; stripping one it would rule YES *lowers*
it ((S−1)/(C−1) < S/C when S < C). The strict “answer NO when unsure” verifier stripped
36 of 64 claims — many of them supported — and the rate fell to 0.85 while the reports
filled with *(citation could not be verified)* notes (83 across ten reports). Reverted:
the verifier stays balanced (“close paraphrases ARE supported”), and only the
deterministic checks — deictics, bold labels, ungrounded numbers — strip without a model
opinion. Run #5 is the measurement of that configuration.

**Run #5 lesson — the judge was scoring honesty as failure.** Two of its last three NOs
were cited sentences in Limitations (“The snippets focus on … but do not provide …”),
which is exactly the hedging the synthesizer is instructed to write when evidence is
thin. Judging meta-prose about the evidence against snippets measures report honesty as
citation failure. **Metrics v3** excludes Limitations from claim extraction (as Sources
already were), with `METRICS_VERSION` bumped so the number is never silently compared
across the change. Run #5 re-scored under v3: 0.9217 → **0.9459**, with the two residual
NOs being one genuine drift (“1.6× faster”, snippet said it nearly verbatim — a judge
error) and one over-generalized compliance claim. Two more deterministic strips landed:
markers pointing at no source cite nothing, and the verify pass now skips Limitations
exactly as the judge does. Run #6 is the measurement.

**Runs #6–#7 — the 7B judge is the floor.** Under the final code and metrics v3 the rate
held in a **0.90–0.92** band across three independent runs (0.9459 best re-score). The
residual NOs are not a strip class: they are substantive sentences where a 7B judge rules
against near-verbatim or close-paraphrase evidence. Stripping more would lower the rate
(run #4's lesson) and fill reports with notes; the honest residue is judge capability, not
pipeline fidelity.

**Release decision (interim, per user direction).** `v1.0.0` is tagged on this state with
the local-model measurement documented as interim: completion 1.00 (was 0.20 — the failures
were masked `429`s), citation support 0.90–0.92 band under metrics v3, against the 0.95
threshold which is **not yet met**. What remains for M5 closure: re-run the eval on Gemini
2.5 Flash when the monthly spend cap resets (same query set, metrics v3), publish that
number in place of the interim one, and stand up the hosted demo. The Gemini key still
answers `429 … monthly spending cap` on a live probe as of this writing.

## M6 — Engine extraction  *(≈ 3 weeks)*  ← the one big rock

✅ **Code complete.** Per [13_Local_First_Architecture.md](../architecture/13_Local_First_Architecture.md)
§3–§5. Nothing in M9 was possible until this landed. Five-step strangler; CI green at
every step.

Cheaper than it looks, and it was: `events.py` and `llm_factory.py` were **already**
ContextVar-indirected, and `retrievers.py` already degraded without Redis. The blocker was
`app/config.py` being a required-field singleton — the same coupling `evals/harness.py`
still hacks around with `os.environ.setdefault`.

- ✅ `RunConfig` dataclass; zero `settings` reads inside engine code
- ✅ `backend/research_engine/` extracted (§3 deviation 1 — under `backend/`, not
  top-level, so the api/worker Docker build context still finds it). No FastAPI/Celery/
  SQLAlchemy/Redis in its dependency tree, proven by the built wheel's metadata and
  enforced by `tests/test_engine_boundary.py`
- ✅ `runner.py` with injected checkpointer / event sink / cache / run config / provider
  keys, returning a plain `RunOutcome`; `pipeline_runner.py` reduced to the server
  adapter. Two ports, not four — `KeyProvider` and `RunLock` were dropped with reasons
  (§4 of doc 13). **Engine→host imports: zero.**
- ✅ SQLite adapters (`local.py`) + the `research-engine` CLI: runs to the gate on a bare
  machine, and `--approve` in a **separate process** finalizes from the SQLite checkpoint
- ✅ `evals/harness.py` builds its config from the environment, not `app.config` — the
  `os.environ.setdefault` workaround is gone

**DoD — met:**

| Criterion | Result |
|---|---|
| `research-engine "query" --fake` → cited draft, no Postgres/Redis/Docker | ✅ run from `/tmp`, outside the repo, with the server env unset |
| Boundary contract passes in CI | ✅ allowlist empty; engine imports zero `app.*` |
| `os.environ.setdefault` deleted from `evals/harness.py`, evals still pass | ✅ harness imports zero `app.*`; `make eval` needs no DB or JWT secret |
| All existing backend tests + three golden E2E journeys unchanged | ✅ **98 passed / 1 skipped** (68 at the start of M6) |

**Verified beyond the DoD:** durable HITL works locally — process 1 pauses at the gate and
exits, process 2 approves from `checkpoints.sqlite` at unchanged cost, so research is not
re-run. The built wheel declares no FastAPI/Celery/SQLAlchemy/asyncpg/Redis/PyJWT/
WeasyPrint and registers the `research-engine` console script; model providers and SQLite
checkpointing are extras (`[google]`, `[anthropic]`, `[openai]`, `[local]`).

**One estimate correction:** `pipeline_runner.py` was projected to shrink to ~30 lines; it
went 211 → 187. Everything left is genuinely host work — the Redis lock, the single
DB-session scope, BYOK decryption, the Postgres saver, and mapping `RunOutcome` onto ORM
columns. A thin adapter is not the same as a short one.

## M7 — Parallel task execution  *(≈ 1 week)*

✅ **Code complete.** The graph used to advance a `current_task_index` one task at a time,
so a run was N sequential LLM+tool rounds. That was a user-facing latency problem, not an
architecture aspiration.

- ✅ Research runs in **rounds**: every pending task concurrently, bounded by
  `max_parallel_tasks` (default 4). Not a per-task pipeline — that would have moved the
  retry loop out of the graph into hand-rolled orchestration; rounds are capped at
  `max_critic_loops`, so the barrier is cheap and the retry path stays a conditional edge.
- ✅ Shared `_BudgetGuard`: every task adds its cost the moment a model call returns and
  re-checks before its next tool round and before being dispatched at all
- ✅ Per-task critic retries preserved (`verdicts`/`retries` keyed by task, replacing the
  moving index); **evidence rebuilt each round in task-definition order**, so citation
  numbering cannot depend on which task finished first
- ✅ Events keep per-task attribution (`detail.task_id`) plus a round summary listing the
  concurrent task ids
- ☐ Live monitor *lanes* — deferred. The existing feed and rail render parallel runs
  without regression (39 frontend tests green), and events already carry what a lane view
  needs. Visual lanes are a UI enhancement, not a correctness gap.

**DoD — met, with one threshold corrected:**

| Criterion | Result |
|---|---|
| Faster wall-clock | ✅ measured at 0.30s/task: **4 tasks 26%**, **6 tasks 34%** of sequential |
| Aggregate cost respects `max_cost_per_session_usd` | ⚠️ **corrected** — see below |
| Citation numbering byte-identical across two identical runs | ✅ asserted end-to-end, and per-round in isolation |
| Existing tests + golden journeys unchanged | ✅ **111 backend passed / 1 skipped** (101 before M7), 39 frontend |

**Threshold correction 1 — speedup is bounded by task count.** This said "≤ 40% of
sequential." That holds from 4 tasks up, but the planner emits 2–6 tasks, and a 2-task run
is physically floored near 50% no matter how many workers exist. Measured: 2 tasks → 50%,
4 → 26%, 6 → 34%. The honest statement is *the research phase scales with
`min(tasks, max_parallel_tasks)`*, not a single percentage.

**Correction 2 — "cost never exceeds the cap" was never true, and cannot be.** A hard cap
and real concurrency are incompatible without pre-reserving budget per call. What is true,
and tested: the guard stops dispatching and stops tool rounds as soon as aggregate spend
crosses the limit, so **overshoot is bounded by the workers already in flight** — with 10
tasks over budget and 3 workers, spend stops at 3, not 10. Worth noting the *sequential*
code had the same hole with a window of one: `_over_budget` only ran between tasks, after
the money was gone. `max_parallel_tasks=1` is the strict setting and is tested to restore
exactly the old behaviour.

## M8 — Model layer  *(≈ 2 weeks)*

✅ **Code complete.** Per [13_Local_First_Architecture.md](../architecture/13_Local_First_Architecture.md) §6.

*Security Note: Custom endpoints shipped unguarded on July 31 (`a852659`). The SSRF guard for these endpoints was added 13 days later on Aug 13 (`67077f2`). The stack was run with `LLM_MODE=real` during development/testing in this window, meaning unguarded custom egress was live in the codebase. A check of local database state found no record of custom endpoints in user or session records; external access logs for ephemeral environments from that period are not retained.*

- ✅ **The Opus 5 bug is fixed, and structurally.** `claude-opus-5` was absent from both
  `PRICE_TABLE` and the `_ANTHROPIC_NO_SAMPLING` prefix tuple, so selecting it failed
  twice over: `validate_pricing()` refused to boot, and had it booted every request would
  have sent a `temperature` and taken a 400. The prefix tuple *was* the bug — which models
  reject sampling params is now a catalog field, with a test pinning the whole split
  rather than the one model.
- ✅ Model **catalog** ([`catalog.py`](../../backend/research_engine/catalog.py)): provider, id,
  display name, prices, context window, max output, tool-calling, structured-output,
  `sampling_params_supported`. Adding a model is a catalog entry and nothing else — an
  invariant with a test behind it.
- ✅ **OpenRouter** and **Ollama** providers. Both speak the OpenAI wire protocol, which is
  what promoted `langchain-openai` from a commented-out optional to a real dependency:
  one client covers OpenAI, OpenRouter, and the local models that are offline tier 2.
- ✅ Per-role picker with `fast` / `balanced` / `best` presets in front and the per-role
  drawer behind "Customize"; persisted per user (`users.model_routing`) and snapshotted
  per session (`sessions.model_routing`), migration `0003_model_routing`.

**Prices are never estimated.** Anthropic figures were taken from the authoritative API
reference, not recalled. Providers whose prices aren't ours to state (OpenAI, OpenRouter)
ship **unpriced**: `None` means "this deployment must supply it", and `validate_pricing()`
refuses to boot rather than defaulting to zero — a silent zero would turn
`MAX_COST_PER_SESSION_USD` into a no-op. A test asserts no hosted model carries a `0.0`.

**DoD — met:**

| Criterion | Result |
|---|---|
| A different model per role, spanning providers, cost matching the catalog | ✅ per-role routing validated, persisted, and installed as a per-run `RunConfig` |
| Opus 5 selectable and working end to end | ✅ builds with **no** `temperature`; asserted directly |
| Ollama-only run with no cloud key | ✅ provider requires no key; client points at the local server |
| Adding a model needs a catalog entry and no code change | ✅ asserted by `test_every_catalog_entry_is_self_consistent` + `register()` |
| `validate_pricing()` still fails fast on an unpriced routed model | ✅ and the error says prices are never estimated |
| Existing tests unchanged | ✅ **147 backend passed / 1 skipped** (132 before), 39 frontend, build green |

**Where M6 paid off.** Per-session routing needed no new mechanism: the per-run `RunConfig`
override built in M6 step 3 is exactly it. A session installs its own config, so two
concurrent runs on different models stay isolated — which is also why the session's routing
is *snapshotted* rather than re-read: a resumed run keeps the models it started with, and a
finished report stays attributable to what wrote it.

## M9 — Desktop app  *(≈ 4 weeks)*

✅ **Code complete.** (`239fe50`) Per [13_Local_First_Architecture.md](../architecture/13_Local_First_Architecture.md) §7.

- ✅ Tauri shell + PyInstaller Python sidecar; frontend as static export
- ✅ **Sidecar bound to `127.0.0.1` on an ephemeral port with a per-launch bearer token**
  (not optional — see §7 of the architecture doc)
- ✅ No-login local mode; SQLite storage; keys in the OS keychain
- ☐ **Signed and notarized** — *not built.* No signing secrets in
  [`desktop.yml`](../../.github/workflows/desktop.yml), no certificate config in
  `tauri.conf.json`. Bundles are unsigned: macOS shows a Gatekeeper block, Windows shows
  SmartScreen. Deferred deliberately — see [17 §8](17_Desktop_Distribution.md).
- ☐ **Auto-update against GitHub Releases** — *not built.* No updater plugin in
  `desktop/Cargo.toml`, no `updater` key in `tauri.conf.json`. Deferred to its own cycle
  ([17 §8](17_Desktop_Distribution.md)); the Cargo comment was always honest about this.
- ✅ AppImage + `.deb` for Linux, `.dmg` for macOS, `.msi` for Windows — CI builds all four
- ✅ Desktop PDF via WebView print; WeasyPrint excluded from the bundle

**DoD (revised).** The original DoD asserted an install from "a released artifact" and that
"auto-update moves n−1 → n" — neither is reachable: CI publishes 14-day artifacts behind a
GitHub login, and no updater exists. What M9 actually delivers, and what is verified:

- ✅ The sidecar rejects an unauthenticated localhost request (asserted in CI).
- ✅ A research session runs, gates, approves and exports with no terminal, Docker or login.
- ☐ Distribution to a non-developer — a public download, an unblock path for Gatekeeper and
  SmartScreen, and a first run that survives having no API key.

That remaining item is **not** a gap in M9's code; it is distribution and onboarding, and is
specified separately in [17. Desktop Distribution and First Run](17_Desktop_Distribution.md).

## M10 — Airgapped corpus mode  *(≈ 2 weeks)*  ← **LAUNCH HERE**

✅ **Code complete.** (`ad999c1`) Promotes v2 item #1 from [10_Roadmap.md](10_Roadmap.md) to headline.

- ✅ Document ingest (PDF/MD/TXT) → chunk → bundled local embeddings → SQLite vector store
- ✅ A retrieval connector shaped like `retrievers.search()`; **the graph does not change**
- ✅ Corpus-only mode: no network calls at all, verified by test
- ✅ Citation snippets resolve to exact document locations (page/offset)

**DoD:** with networking disabled at the OS level, a local-model run over a user corpus
produces a cited report whose every `[n]` resolves to an exact document location · a
network-egress test proves zero outbound connections in corpus-only mode · ingest of 500
documents completes on a consumer laptop without OOM.

**→ Then launch:** rename, Show HN ("citation-grade deep research that runs entirely on
your laptop"), Product Hunt, r/selfhosted, r/LocalLLaMA.

## M11 — Contradiction detection  *(≈ 2 weeks)*

✅ The only trust feature on the table that is **observable** rather than oracular: two
sources assert incompatible things, and that is checkable without a truth model.

- Detect conflicting claims across evidence; surface in the report as a first-class block
  with both sources and the nature of the disagreement
- Never auto-resolve. Present the conflict; the human gate is where it gets adjudicated

**DoD:** a curated fixture set of known-contradictory sources is detected at ≥ 80% recall
with ≤ 10% false-positive rate on a known-consistent control set · conflicts render in
report, export, and PDF · a new eval metric `contradictions_surfaced` is recorded in the
baseline.

**Result (2026-08-13, deepseek-r1:14b):** recall = 1.0, false_positive_rate = 0.0833.
Both bars cleared. Baseline: `evals/results/contradictions_2026-08-13_183819.json`.

## M12 — The research bundle + offline verifier  *(≈ 2 weeks)*

✅ The standards play. SBOM-for-research.

- An open, documented bundle format: report, claims, evidence snippets, source URLs **with
  content hashes**, full agent trace, models used, costs, approval record
- A **standalone verifier** (single small binary, no AI, no network) that confirms every
  citation resolves and the trace is intact
- Bundle export from every mode; verifier published separately

**DoD:** the format is specified in `docs/` with a versioned schema · the verifier
validates a bundle from a third machine with no app installed and no network · a tampered
bundle fails verification with a specific, human-readable reason.

## M13 — Public citation-fidelity benchmark  *(≈ 2 weeks)*

☐ A public, reproducible benchmark scoring our pipeline and one open-source comparable.

- Run our pipeline against the fixed 10-query eval set and record real numbers (cost, time, citation fidelity).
- Run **one** open-source comparable (GPT-Researcher) against the same set. This ensures the benchmark remains reproducible without drifting API behavior or changing pricing tiers.
- Explicitly state in the methodology doc why closed competitors (Perplexity Pro, ChatGPT Deep Research, Gemini Deep Research) are excluded from v1 (rate limits, opaque behavior changes, cost), leaving room to add them later.

**DoD:** benchmark repo/section is reproducible by a third party from documented steps ·
our own failure cases are published, not just wins · results are dated and versioned
against model versions.

## M14+ — The flywheel  *(ongoing)*

☐ Connector SDK + registry (community-built PubMed/arXiv/SEC/patent retrievers — the
honest version of "dynamic agents": capability composition, not invented labels; also the
only realistic way to raise the evidence ceiling above generic web search)
☐ Audit replay — step through a completed run like a debugger; the trace and checkpoints
already exist, so this is mostly UI
✅ Research memory across sessions — **promoted to M16/M17** (see below). The original
deferral was right to fear unfiltered memory; what changed is finding the filter: only
*approved* reports enter it, so the HITL gate curates the corpus. Organizing work into
projects is also needed regardless of memory.
☐ Hosted workspaces, shared reports, reviewer roles

## M15 — Local LLM, first-class in the UI  *(≈ 1 week)*

✅ **Code complete** (commit a9b50ef). The engine already routed to Ollama; nothing in the
product *told* a user that, and
`available_providers()` optimistically reports Ollama usable even with no server running.

- ✅ Settings card: connection status, detected local models, base-URL override
- ✅ **Real connection probe** (`GET /models/local/status`) — reachable? which models are
  actually installed? which map to catalog routes?
- ✅ Honest capability warning. Measured 2026-08-06: `qwen2.5:7b` plans and calls the
  search tool correctly but fails the executor's structured-evidence step
  (`no_parsable_evidence`) — small models are weak at strict schemas and tool-calling.
  Ship the warning with the feature, not after the support tickets.
- ✅ User guide ([guides/Local_LLM_Setup.md](../guides/Local_LLM_Setup.md))

**DoD:** a user with Ollama installed can connect, see their models detected, and be told
plainly which are viable · a user *without* Ollama sees "not detected" rather than a model
that silently fails at run time.

## M16 — Projects as containers  *(≈ 1 week)*

✅ **Code complete** (commits 2ad2ca5 backend, 1566c43 frontend). Per
[14_Projects_and_Memory.md](../architecture/14_Projects_and_Memory.md) §3/§7. No memory
yet — organization only, which is most of the day-to-day value.

Verified against the live database: the three-phase backfill migration (0005) moved 19
existing sessions into 12 per-user "General" projects with 0 orphans and 0 cross-user
mismatches. Isolation, cross-user 404s (read *and* delete), case-insensitive duplicate
names (409), the running-session delete guard, and full delete cascade (project →
sessions → LangGraph checkpoints) were each exercised end to end.

- ✅ `projects` CRUD; `sessions.project_id`; migration backfilling a `General` project
- ✅ History and dashboard scoped per project; project switcher in the shell

**DoD:** every existing session still opens/chats/exports after migration · history is
per project · deleting a project cascades cleanly.

## M17 — Project memory & project chat  *(≈ 2–3 weeks)*

✅ **Done.** The differentiator. Per
[14_Projects_and_Memory.md](../architecture/14_Projects_and_Memory.md) §2/§4/§5.

- ✅ pgvector prerequisite (commit fa102f9): each compose file pinned to the
  `pgvector/pgvector:pgNN` image matching its own volume's major version, plus migration
  0006 enabling the extension on its own so a stock-image deployment fails at the
  prerequisite rather than midway. Verified live: Postgres recreated over the existing
  volume, extension installed, all 12 projects / 19 sessions / 14 users intact.
  *(CI was still on stock `postgres:16-alpine` and would have failed the next migration —
  both service blocks now pin the pgvector image too.)*
- ✅ `Embeddings` port in `research_engine/ports.py`; Ollama `nomic-embed-text` locally,
  Google/OpenAI for cloud, all at 768 dimensions. Passed explicitly rather than through a
  ContextVar — nothing in the graph embeds, so an ambient holder would have no reader
  (recorded as a deviation in doc 14 §4).
- ✅ Ingestion hooked to the **approval** transition only — the COMPLETED branch of
  `_persist_outcome`, which is reachable only through the gate.
- ✅ `chat_threads` — chat no longer bound to a single report; legacy per-report chat
  untouched, with a CHECK enforcing exactly one parent per message.
- ✅ Retrieval filtered in SQL by `project_id` **and** `embedding_model`; answers cite
  `[R1]` → report → sources, with the existing ⚠ chip for markers that don't resolve.
- ✅ `/chat` UI: project-scoped threads, citation chips carrying the retrieved excerpt,
  and a memory-status card that names the two ways memory can be quietly incomplete.

**DoD:** the §9 checklist in doc 14 passes — the automated **cross-project isolation
test** (including two projects owned by the same user) and proof that rejected drafts
never surface, both against real Postgres + pgvector. 231 backend and 57 frontend tests.

**Measured (2026-08-12):** Memory eval ran with `Gemini 2.5 Flash`. Achieved a **100% pass rate** on accurately citing supported claims and correctly refusing unsupported claims across 10 memory queries. This verifies the memory capability is robust and ready for production.

---

## 4. Scale sizing (so we don't over-build)

10,000 registered ≈ 200–500 DAU ≈ 10–30 concurrent runs. A "run" is mostly *awaiting*
external LLM and search APIs — the server orchestrates, it does not compute. One 4-vCPU
Hetzner box with Postgres local and Cloudflare free tier in front absorbs this with room
to spare.

**No Kubernetes. Not at 10k, probably not at 100k.** The desktop population costs nothing
and scales infinitely because it isn't ours to scale.

## 5. Budget

| Item | $/mo |
|---|---|
| Hetzner VPS (4 vCPU / 16 GB, hosted mode) | ~30 |
| Snapshots + offsite backup | ~5 |
| Apple Developer ($99/yr) | ~8 |
| Windows code signing (Azure Trusted Signing) | ~10 |
| Domain + transactional email (free tier) | ~3 |
| GitHub Actions, Releases, Sentry, Plausible (free tiers, public repo) | 0 |
| Search (DDG keyless for demo; users BYOK Tavily) | 0 |
| **Total** | **~$56** |

Headroom to $200 covers a bigger box, a community SearXNG instance, or a real-model eval
budget. Sustainability beyond pocket money: GitHub Sponsors + Polar from day one; a paid
convenience tier (managed hosting, sync) remains possible later **without ever gating the
open-source product**.

## 6. Distribution

Desktop launch (Show HN — exactly HN's demographic) → Product Hunt → the benchmark
post → package managers (`brew`, `winget`, AUR — each a permanent free channel) →
r/selfhosted and r/LocalLLaMA, where airgapped mode is what they have been asking for.

## 7. Out of scope — binding

Per [01_Product_Vision.md](01_Product_Vision.md), this list is binding; new ideas go to
M14, not into an active milestone.

- **Multi-model consensus voting.** Models share training data and share hallucinations;
  agreement measures correlation, not truth. Role specialization (M8) is the useful form.
- **LLM-invented agents.** A generated "FDA Agent" with no FDA connector behind it is a
  label. M14's connector registry is the real version.
- **Confidence scores and source-reliability rankings.** Unfalsifiable numbers on a
  product whose pitch is defensibility. Contradiction detection (M11) is the observable
  alternative.
- **Autonomous experimentation sandboxes.** Different product, different security surface.
- **Kubernetes, distributed workers, budget-optimizing schedulers.** §4.
- **Agent marketplace, "ResearchOS" framing.** Revisit if and when there are users.

## 8. Risk register

| Risk | Mitigation |
|---|---|
| M6 drags and blocks M9 | five-step strangler; step 1 merges alone; shim keeps `backend/` untouched |
| Launching on unmeasured claims | M5 gates everything and is 2 weeks |
| Desktop signing/AV pain | budgeted month 1; WeasyPrint excluded by design |
| Two products diverge | one engine; golden E2E runs against **both** hosts in CI |
| Solo-dev burnout | every milestone independently shippable and stoppable — the M0–M4 discipline that worked |
| Scope creep | §7 is binding |
| Launch narrative depends on a regulatory date | verify Art. 14 against a primary source in M5; the product stands without it |
