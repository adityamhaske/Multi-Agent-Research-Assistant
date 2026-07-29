# 12. v2 Launch Plan — local-first, 10,000 users, $200/month

> Continues [10_Roadmap.md](10_Roadmap.md) (M0–M4 ✅ code complete). Same rules:
> vertical slices, every milestone independently demoable, **done only when its
> Definition of Done passes verbatim**. Architecture contract for M6–M10 is
> [13_Local_First_Architecture.md](13_Local_First_Architecture.md).
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

- **Fix the README license contradiction.** [README.md:275](../README.md:275) says "No
  license has been set yet" while MIT ships in `LICENSE` and the badge at line 8 links to
  it. This is on the landing page of the thing being launched.
- **Record a real-model eval run.** The committed baseline
  ([`eval-2026-07-23.json`](../backend/evals/results/eval-2026-07-23.json)) is fake-mode:
  all 10 queries returned identical output — 41 words, 2 sources, 5 citations, $0.00084 —
  and `citation_support_rate` is `null`. The product's central claim is currently
  **unmeasured**. `LLM_MODE=real make eval`, ~$5 of credit, commit the result.
- **Publish the numbers in the README, with the method** — including the misses. "Across
  N runs, X of Y citations failed to resolve; the UI flagged all X." Nobody publishes
  their failure rate. We built the ⚠ chip; lead with it.
- **Hosted fake-mode demo live** at a real URL; set the repo `homepageUrl` (currently
  empty).
- **Tag `v1.0.0`** — `release.yml` exists and is waiting on a tag.
- **Run 20 real questions and read every output like a hostile reviewer.** Log every
  defect. **This reorders M11–M13.** Both strategic critiques of this project so far —
  including the one that produced this plan — reasoned about a system nobody had watched
  run at volume on real queries.

**DoD:** README has zero false statements, verified line by line · a real-model eval JSON
is committed with a non-null `citation_support_rate` and its method documented ·
`v1.0.0` tagged and GHCR images published · demo URL reachable from a clean browser ·
a written defect log from 20 real runs exists in `docs/` and M11–M13 have been reordered
against it, or explicitly confirmed unchanged.

## M6 — Engine extraction  *(≈ 3 weeks)*  ← the one big rock

☐ Per [13_Local_First_Architecture.md](13_Local_First_Architecture.md) §3–§5. Nothing in
M9 is possible until this lands. Do it as the five-step strangler; keep CI green at every
step.

Cheaper than it looks: `events.py` and `llm_factory.py` are **already** ContextVar-
indirected, and `retrievers.py` already degrades without Redis. The blocker is
`app/config.py` being a required-field singleton — the same coupling `evals/harness.py`
already hacks around with `os.environ.setdefault`.

- `RunConfig` dataclass; zero `settings` reads inside engine code
- `packages/research-engine/` extracted, no FastAPI/Celery/SQLAlchemy/Redis in its
  dependency tree, enforced by an **import-linter contract in CI**
- `runner.py` with injected checkpointer / sink / lock / key provider;
  `pipeline_runner.py` reduced to the server adapter
- SQLite adapters + a `research-engine` CLI that runs a query to the gate on a bare
  machine with no Docker

**DoD:** `pip install packages/research-engine && research-engine "query" --fake`
produces a cited draft on a machine with no Postgres, Redis, or Docker · import-linter
contract passes in CI · the `os.environ.setdefault` block is **deleted** from
`evals/harness.py` and evals still pass · all existing backend tests and the three golden
E2E journeys pass unchanged.

## M7 — Parallel task execution  *(≈ 1 week)*

☐ [`graph.py:399`](../backend/app/agent/graph.py:399) advances `current_task_index` one at
a time, so a comprehensive run is N sequential LLM+tool rounds. This is a user-facing
latency problem, not an architecture aspiration.

- Fan out independent research tasks concurrently with a bounded worker count
- Budget guards enforced against **aggregate** in-flight spend, not per-task — the
  current `_over_budget` check assumes sequential accumulation
- Per-task critic retries preserved; evidence merge stays deterministic (stable ordering,
  so citation numbering doesn't shuffle between runs)
- Events keep per-task attribution so the live monitor shows parallel lanes

**DoD:** a comprehensive-depth run completes in ≤ 40% of its sequential wall-clock on the
eval set · aggregate cost never exceeds `max_cost_per_session_usd` under concurrency
(regression test with a forced-overrun fixture) · citation numbering is byte-identical
across two runs of the same fixture · live monitor renders concurrent tasks correctly.

## M8 — Model layer  *(≈ 2 weeks)*

☐ Per [13_Local_First_Architecture.md](13_Local_First_Architecture.md) §6.

- **Fix the Opus 5 bug first:** `_ANTHROPIC_NO_SAMPLING`
  ([`llm_factory.py:37`](../backend/app/agent/llm_factory.py:37)) omits `claude-opus-5`,
  so routing a role to it sends `temperature` and 400s; it's also missing from
  `PRICE_TABLE`. Prices come from the provider's live pricing page — never estimated.
- Model **catalog** replacing the flat price table: provider, id, display name, prices,
  context window, tool-calling, structured-output, `sampling_params_supported`
- **OpenRouter** provider (one key → most frontier models) and **Ollama** provider
  (local, offline tier 2)
- Per-role picker UI with `Fast` / `Balanced` / `Best` presets in front and the
  per-role drawer behind "Customize"; selection persists per user and per session

**DoD:** a user can run one session with a different model per role, spanning two
providers, and the recorded cost matches the catalog · Opus 5 selectable and working
end-to-end · an Ollama-only run completes to the gate with no cloud key present ·
adding a model requires a catalog entry and no code change · `validate_pricing()` still
fails fast on an unpriced routed model.

## M9 — Desktop app  *(≈ 4 weeks)*

☐ Per [13_Local_First_Architecture.md](13_Local_First_Architecture.md) §7.

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
☐ Research memory across sessions — **only now**, with real users and real corpora to
learn from
☐ Hosted workspaces, shared reports, reviewer roles

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
