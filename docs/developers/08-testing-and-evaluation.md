# Testing and evaluation

Two different questions, deliberately kept apart:

- **Tests** ask *does it work* — deterministic, free, and on every commit.
- **Evaluations** ask *is the output any good* — real models, real money, run on purpose.

## The pyramid

| Layer | Tooling | Scope | Speed |
|---|---|---|---|
| Unit (backend) | pytest | Schemas, guards, cost maths, citation and prompt validators, chunking, normalisation | ms |
| Integration (backend) | pytest + httpx ASGI client + real Postgres/Redis | API endpoints, auth flows, migrations, project isolation | s |
| Pipeline (backend) | pytest with scripted models | The compiled graph end to end, no network and no keys | s |
| Unit (frontend) | Vitest + Testing Library | SSE parser, citation renderer, pipeline derivations, formatters | ms |
| Golden end-to-end | Playwright against the real stack in fake mode | Whole user journeys through a real browser | min |
| Evaluations | Custom harness | Report quality against a fixed query set with real models | min–$ |

`LLM_MODE=fake` is what makes the middle layers deterministic and free: the factory returns
scripted models and the retriever chain returns fixture results, so no network call and no
API key is involved.

## The golden journeys

Five journeys run in CI against the packaged stack, and they encode the product's promises.

| Journey | What it proves |
|---|---|
| **0 — the design gate** | Editing the plan before any search runs changes the run, then the draft is reached |
| **1 — research reaches the gate** | Register → submit → live pipeline events over SSE → a cited draft renders |
| **2 — approval completes the session** | Approving finalises **without re-running research**, and Markdown export downloads |
| **3 — rework loops and chat works** | Rejecting with feedback re-runs synthesis, the gate is re-reached, approval works, and chat answers from the report |
| **6 — corpus documents preview in place** | A document is uploaded and read without leaving the page |

Journey 2 is the load-bearing one: it asserts that resume enters the graph **at the gate**,
not at the planner.

```bash
cd frontend && npm run e2e
```

**Running it locally.** The suite drives the real stack, so bring one up first — `./start.sh
--fake` is enough, and fake mode is what CI uses. Then point Playwright at it:

```bash
E2E_NO_SERVER=1 E2E_BASE_URL=http://localhost:3031 npm run e2e
```

Omit `E2E_NO_SERVER` and Playwright builds and starts the frontend itself; set it when one
is already running, which is faster and what CI does.

**Repeated local runs are safe, and that is not an accident.** Registration is capped at 5
per IP per hour and the cap is *not* configurable — it is brute-force protection, and one a
test suite can switch off is not a cap. The suite registers one account per journey and has
more journeys than that, so it would exhaust the cap on the first run and fail on the
second. `e2e/fixtures.ts` therefore deletes this suite's own `rl:*` counters before each
journey; it never issues `FLUSHDB`, because the same Redis carries the SSE channels and the
search cache and blowing those away would change what the run under test actually does.

If you do hit the cap — running one spec against a stack whose Redis the fixture cannot
reach, say — the failure now names itself rather than surfacing as a navigation timeout.
Clear the counters by hand with:

```bash
redis-cli -n 1 --scan --pattern 'rl:*' | xargs -r redis-cli -n 1 del
```

The cap itself stays armed: `backend/tests/security/test_auth_rate_limit.py` proves a sixth
registration from one address is refused, and pins the published limit so widening it has
to be deliberate.

CI starts the API and the worker in fake mode, then Playwright. It waits for an explicit
worker preload signal rather than for a ping — a Celery worker answers a ping while LangGraph
and the provider clients are still importing, which measurably cost tens of seconds on the
first task and made these journeys look flaky when the real cause was a worker that had not
finished booting.

## Testing an absence

A recurring trap worth its own section. When you write a test for an *absence* — no network
egress, no writes, no spend — check what the fixtures replaced.

A test once asserted zero network calls in corpus mode while injecting a fake embedder, and
the query embedding was the only call that egressed. The suite was green precisely because it
had replaced the defect. **If the mechanism under test is the thing you mocked, the test is
decorative.**

## What CI enforces

Run what CI runs, not what is convenient:

```bash
cd backend && ruff check app/ research_engine/ tests/ evals/ \
  && ruff format --check app/ research_engine/ tests/ evals/ \
  && python -m pytest
```

```bash
cd frontend && npm run lint && npm run typecheck && npm test && npm run build
```

Plus, in the frontend job, [four bespoke greps](32-development.md#the-four-greps-that-fail-the-build)
that `npm run lint` does not run.

Jobs: `backend`, `frontend`, `golden-e2e`, and `eval-artifacts`. Dependency audits
(`pip-audit`, `npm audit`) run non-blocking.

### Evaluation results are write-once

The `eval-artifacts` job fails the build if a committed file under `backend/evals/results/`
is *modified*. Adding a new result is always fine; changing one is not.

This exists because a frontend commit once silently overwrote a real 10/10 measurement with a
failed run, leaving the README citing numbers whose proof no longer existed. Nothing failed
and nothing warned. Record a new run under a new name — `eval-<date>-<routing>-run<N>.json`,
because a date alone is not a run identity.

## Evaluations

The harness runs a versioned query set through the compiled graph up to the review gate and
records per-report metrics to a dated JSON file, so report quality is diffable over time.

```bash
make eval                                   # fake mode: deterministic, free, no keys
LLM_MODE=real GOOGLE_API_KEY=… make eval    # real models
```

Mode is read from the *real* environment before `.env` is loaded, and `.env` supplies keys
only. That ordering is deliberate: a developer `.env` commonly carries `LLM_MODE=real` for
the app, and letting that reach the harness would silently turn `make eval` — documented and
relied on as the free default — into a run that spends money on every invocation. **Spending
is opt-in, per invocation.**

### Metrics

| Metric | Definition |
|---|---|
| Completion rate | Fraction of queries that reached a report |
| Citation resolution rate | In-text `[n]` markers that resolve to a real source |
| Citation support rate | Cited claims an independent judge rules are actually supported by their snippet |
| Uncited claims | Assertive sentences carrying no citation marker |
| Contradictions surfaced | Distinct conflicting pairs shown to the reader |
| Source count, cost, latency | Per report |

Every run records its own method block and a `metrics_version`, bumped whenever a definition
changes, so two runs are never silently compared across incompatible metrics.

### Retrieval quality

Report quality is bounded by retrieval quality — [`docs/01`](../getting-started/01-overview.md),
[`docs/10`](../project/10-roadmap.md), [`docs/21`](../getting-started/21-configuration.md) and
[`docs/33`](33-contributing.md) all say so — and for a long time nothing measured it. A second
harness does now, separate from the report harness above because it answers a narrower
question: given a query, does the retriever return the right documents?

```bash
python -m evals.retrieval             # measure and print
python -m evals.retrieval --write     # also record a write-once result file
```

It measures; it does not rank. Queries go through `CorpusStore.search` — the same call the
executor makes — so what is recorded is production behaviour rather than a reimplementation
of it. The dataset is a frozen 16-document corpus with a fingerprint, so a changed corpus
cannot be mistaken for a changed retriever.

| Metric | Definition |
|---|---|
| recall@k | Of the documents that should be found, the fraction retrieved in the top *k* |
| precision@k | Of the top *k* retrieved, the fraction that should have been found |
| nDCG@10 | Rank-aware relevance — being right at position 1 counts for more than at 10 |
| dedup rate | Near-duplicate documents collapsed rather than returned twice |

**A real embedder is required, and its absence is reported rather than filled in.**
`FakeEmbeddings` hashes text with blake2b — deterministic, and carrying no semantic signal —
so recall over those vectors would be a number with no meaning attached. With no embedding
endpoint reachable the harness refuses and records `"status": "unmeasured"` with the reason.
That is the same rule as [Unmeasured is not zero](#unmeasured-is-not-zero), one level up.

The recorded baseline
(`backend/evals/results/retrieval-2026-09-09-corpus-local.json`, `ollama:nomic-embed-text`,
12 queries):

| recall@1 | precision@1 | nDCG@10 | dedup rate |
|---|---|---|---|
| 0.792 | 0.917 | 0.944 | 0.000 |

This baseline is the gate a retrieval change has to clear: no change merges without a
measured, committed result either side of it. Hybrid retrieval was built and measured against
exactly this and did not beat it, so it was rejected — see
[the roadmap](../project/10-roadmap.md).

### Unmeasured is not zero

The rule the whole harness is built around, and the reason it exists at all.

A provider error, a partial model reply, and an unparseable answer must not each silently
contribute a *miss* to a quality score — that makes an exhausted quota indistinguishable from
a quality collapse. So:

- unjudged claims are **excluded from the denominator**, not counted as failures;
- a metric returns `None` when nothing could be judged, and `None` renders as
  `n/a (unmeasured)`, never `0.0`;
- a trace records the model that actually answered, never the one that was requested.

**The rule has two homes** — the harness and the benchmark — and they must change together.

### Release criteria

Citation support ≥ 0.95 and completion ≥ 0.90 on the fixed set. The most recent real-model
run does not clear the first; see
[Citation-fidelity benchmark](../research/16-citation-fidelity-benchmark.md) for what has
actually been measured, and under what caveats.

## Quality gates

| Gate | Enforced by |
|---|---|
| No merge with failing golden journeys | Branch protection on `main` |
| No schema change without a migration round-trip | The backend CI job |
| Committed evaluation results are never modified | The `eval-artifacts` CI job |
| No banned frontend pattern | The four greps |
| Prompt or model changes carry an evaluation run | Review |
| Documentation updated in the same pull request as behaviour | Review |
