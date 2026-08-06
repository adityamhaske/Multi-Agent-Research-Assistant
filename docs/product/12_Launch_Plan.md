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

- **Fix the README license contradiction.** [README.md:275](../../README.md:275) says "No
  license has been set yet" while MIT ships in `LICENSE` and the badge at line 8 links to
  it. This is on the landing page of the thing being launched.
- **Record a real-model eval run.** The committed baseline
  ([`eval-2026-07-23.json`](../../backend/evals/results/eval-2026-07-23.json)) is fake-mode:
  all 10 queries returned identical output — 41 words, 2 sources, 5 citations, $0.00084 —
  and `citation_support_rate` is `null`. The product's central claim is currently
  **unmeasured**. `LLM_MODE=real make eval`, ~$5 of credit, commit the result.
- **Publish the numbers in the README, with the method** — including the misses. "Across
  N runs, X of Y citations failed to resolve; the UI flagged all X." Nobody publishes
  their failure rate. We built the ⚠ chip; lead with it.
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
- **Tag `v1.0.0`** — `release.yml` exists and is waiting on a tag. It now publishes
  multi-arch images (`linux/amd64` + `linux/arm64`; Always Free compute is Ampere ARM, and
  an amd64-only image will not start there) and can be run manually to publish an `edge`
  tag, so the demo box is not blocked on the `v1.0.0` decision.
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

`executor_wrapup reason=no_parsable_evidence` fires on **nearly every task** in real mode:
Gemini 2.5 Flash frequently fails to emit well-formed structured evidence on the first
attempt and falls back to the no-tools retry at
[`graph.py`](../../backend/research_engine/graph.py). The run recovers — that fallback exists
precisely for this — but it costs an extra model call per task, and the recovery rate is
currently unmeasured. Candidate fixes: a stronger executor model (now one click via M8's
picker), a firmer structured-output instruction, or accepting it as the cost of a cheap
executor. **Needs a decision backed by a measurement, not a guess.**

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

☐ Per [13_Local_First_Architecture.md](../architecture/13_Local_First_Architecture.md) §7.

- Tauri shell + PyInstaller Python sidecar; frontend as static export
- **Sidecar bound to `127.0.0.1` on an ephemeral port with a per-launch bearer token**
  (not optional — see §7 of the architecture doc)
- No-login local mode; SQLite storage; keys in the OS keychain
- Signed and notarized for macOS and Windows; AppImage + `.deb` for Linux
- Auto-update against GitHub Releases
- Desktop PDF via WebView print; WeasyPrint excluded from the bundle

**DoD:** a fresh non-developer machine on each of the three OSes installs from a released
artifact, runs a research session with a pasted key, hits the gate, approves, and exports —
with no terminal, no Docker, no login · macOS Gatekeeper and Windows SmartScreen both pass
clean · auto-update moves n−1 → n successfully · the sidecar rejects an unauthenticated
localhost request.

## M10 — Airgapped corpus mode  *(≈ 2 weeks)*  ← **LAUNCH HERE**

☐ Offline tier 3. Promotes v2 item #1 from [10_Roadmap.md](10_Roadmap.md) to headline.

- Document ingest (PDF/MD/TXT) → chunk → bundled local embeddings → SQLite vector store
- A retrieval connector shaped like `retrievers.search()`; **the graph does not change**
- Corpus-only mode: no network calls at all, verified by test
- Citation snippets resolve to exact document locations (page/offset)

**DoD:** with networking disabled at the OS level, a local-model run over a user corpus
produces a cited report whose every `[n]` resolves to an exact document location · a
network-egress test proves zero outbound connections in corpus-only mode · ingest of 500
documents completes on a consumer laptop without OOM.

**→ Then launch:** rename, Show HN ("citation-grade deep research that runs entirely on
your laptop"), Product Hunt, r/selfhosted, r/LocalLLaMA.

## M11 — Contradiction detection  *(≈ 2 weeks)*

☐ The only trust feature on the table that is **observable** rather than oracular: two
sources assert incompatible things, and that is checkable without a truth model.

- Detect conflicting claims across evidence; surface in the report as a first-class block
  with both sources and the nature of the disagreement
- Never auto-resolve. Present the conflict; the human gate is where it gets adjudicated

**DoD:** a curated fixture set of known-contradictory sources is detected at ≥ 80% recall
with ≤ 10% false-positive rate on a known-consistent control set · conflicts render in
report, export, and PDF · a new eval metric `contradictions_surfaced` is recorded in the
baseline.

## M12 — The research bundle + offline verifier  *(≈ 2 weeks)*

☐ The standards play. SBOM-for-research.

- An open, documented bundle format: report, claims, evidence snippets, source URLs **with
  content hashes**, full agent trace, models used, costs, approval record
- A **standalone verifier** (single small binary, no AI, no network) that confirms every
  citation resolves and the trace is intact
- Bundle export from every mode; verifier published separately

**DoD:** the format is specified in `docs/` with a versioned schema · the verifier
validates a bundle from a third machine with no app installed and no network · a tampered
bundle fails verification with a specific, human-readable reason.

## M13 — Public citation-fidelity benchmark  *(≈ 2 weeks)*

☐ Whoever defines the measurement defines the category — and we already have the harness
nobody else bothered to build.

- Extend `backend/evals/` into a published benchmark: fixed public query set, documented
  metrics, **published failure cases**
- Score comparable tools alongside ours; publish methodology and raw outputs
- Write it up: *"We measured citation fidelity across N deep-research tools — here's the
  data and the harness."*

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

◐ The engine already routes to Ollama; nothing in the product *tells* a user that, and
`available_providers()` optimistically reports Ollama usable even with no server running.

- ☐ Settings card: connection status, detected local models, base-URL override
- ☐ **Real connection probe** (`GET /models/local/status`) — reachable? which models are
  actually installed? which map to catalog routes?
- ☐ Honest capability warning. Measured 2026-08-06: `qwen2.5:7b` plans and calls the
  search tool correctly but fails the executor's structured-evidence step
  (`no_parsable_evidence`) — small models are weak at strict schemas and tool-calling.
  Ship the warning with the feature, not after the support tickets.
- ☐ User guide ([guides/Local_LLM_Setup.md](../guides/Local_LLM_Setup.md))

**DoD:** a user with Ollama installed can connect, see their models detected, and be told
plainly which are viable · a user *without* Ollama sees "not detected" rather than a model
that silently fails at run time.

## M16 — Projects as containers  *(≈ 1 week)*

☐ Per [14_Projects_and_Memory.md](../architecture/14_Projects_and_Memory.md) §3/§7. No
memory yet — organization only, which is most of the day-to-day value.

- ☐ `projects` CRUD; `sessions.project_id`; migration backfilling a `General` project
- ☐ History and dashboard scoped per project; project switcher in the shell

**DoD:** every existing session still opens/chats/exports after migration · history is
per project · deleting a project cascades cleanly.

## M17 — Project memory & project chat  *(≈ 2–3 weeks)*

☐ The differentiator. Per [14_Projects_and_Memory.md](../architecture/14_Projects_and_Memory.md) §2/§4/§5.

- ☐ pgvector prerequisite (`pgvector/pgvector:pg16` + `CREATE EXTENSION`)
- ☐ `EmbeddingsPort` injected like every other engine port; Ollama `nomic-embed-text`
  locally, provider embeddings for cloud
- ☐ Ingestion hooked to the **approval** transition only
- ☐ `chat_threads` — chat no longer bound to a single report
- ☐ Retrieval filtered in SQL by `project_id`; answers cite `[R1]` → report → sources

**DoD:** the §9 checklist in doc 14 passes verbatim — including the automated
**cross-project isolation test** and proof that rejected drafts never surface.

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
