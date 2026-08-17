# Citation-fidelity benchmark

> **Status: methodology defined; benchmark results not yet published.**
>
> The protocol below is a specification for a comparative benchmark that has **not been
> run**. No `benchmark_v1` result artifacts exist in this repository. Nothing on this page
> should be read as a measured comparison against any other system.
>
> Separate from this: the project's own [evaluation harness](../developers/08-testing-and-evaluation.md)
> *has* been run against real models, and those results are committed. They are summarised
> in [§8](#8-what-has-actually-been-measured) with their caveats, and they measure this
> pipeline alone — they are not a benchmark.

## 1. Purpose

Most evaluations of AI search and "deep research" rest on human preference scores or opaque
multi-metric rubrics, in which a hallucinated citation cannot be disentangled from good prose.

This methodology specifies a reproducible, citation-grounded evaluation built on three
principles:

1. **Verification over vibe.** A claim is either supported by its cited evidence or it is
   not. Structural resolution (`[n]` → source) is verified deterministically; factual support
   is judged zero-shot by an independent model under a strict binary rubric.
2. **A fixed, independent judge.** The judge must never be the system under test, and must
   not share model-family affinity with any generator being compared.
3. **Reproducibility.** Every system evaluated must be executable from a deterministic,
   self-hostable setup with pinned versions and public queries.

## 2. Fixed query set

Ten versioned queries across seven domains, committed at `backend/evals/queries.json`. They
are designed to require multi-source synthesis, recent factual grounding, or nuanced
technical comparison.

| ID | Domain | Depth |
|---|---|---|
| `llm-memory` | AI | balanced |
| `postgres-vs-mysql` | Software | fast |
| `solid-state-batteries` | Energy | comprehensive |
| `ozempic-mechanism` | Health | balanced |
| `carbon-capture-cost` | Climate | balanced |
| `rust-adoption` | Software | fast |
| `remote-work-productivity` | Economics | balanced |
| `quantum-error-correction` | Physics | comprehensive |
| `eu-ai-act` | Policy | balanced |
| `mediterranean-diet` | Health | fast |

## 3. Metrics

All metrics are computed on the generated report body, excluding metadata, reference lists,
and system-rendered conflict blocks.

### 3.1 Deterministic

- **Total citations** — every in-text numeric marker, including comma-separated groups.
- **Citation resolution rate** — `(total − unresolved) / total`, where unresolved means the
  index is absent from the report's reference list. **Returns `None` when there are no
  citations at all**, never `0`.
- **Uncited claim count** — assertive sentences in the body carrying no citation marker.
- **Contradictions surfaced** — distinct conflicting-evidence pairs shown to the reader.
- **Wall-clock time** and **cost**, the latter from token usage against a fixed price
  catalog.

### 3.2 LLM-judged citation support rate

Whether the snippet extracted from the cited source actually substantiates the claim:

```
support rate = claims judged YES / claims actually judged
```

**Claims that could not be judged are excluded from the denominator, not counted as
failures.** A provider error, a partial reply, and an unparseable answer each contribute
*nothing*, in either direction — otherwise an exhausted quota is indistinguishable from a
quality collapse. When nothing could be judged the metric is `None`, rendered
`n/a (unmeasured)`.

This rule has two implementations, in the harness and in the benchmark runner, and they must
change together.

### 3.3 Judge independence

The judge model must be **fixed, pinned, and disclosed**, and must share no vendor or
architectural lineage with any system under test. It must accept an explicit `temperature=0`.

The judge receives **only** the extracted claim sentence and the snippets associated with its
cited indices. It has no access to the full report, to system identities, or to agent traces.

#### Judge prompt

```text
System:
You judge whether factual claims made in research reports are strictly supported by the
cited evidence snippets. For each numbered claim and evidence pair:
- Respond "Claim N: YES" if the evidence snippet directly corroborates the assertion.
- Respond "Claim N: NO" if the snippet does not contain sufficient facts to support the
  claim, if the claim extrapolates beyond the text, or if the snippet is irrelevant.
Do not assume external knowledge. Be strictly conservative.

Human:
For each claim below, determine if it is supported by its cited evidence.
Answer with one line per claim in format: "Claim N: YES" or "Claim N: NO"

Claim 1: <extracted sentence>
Evidence 1:
- <snippet 1A>
- <snippet 1B>
```

#### Trace logging

Every judged claim must produce an auditable record:

```json
{
  "query_id": "llm-memory",
  "system": "our_pipeline | baseline",
  "claim_text": "…",
  "cited_indices": [1, 2],
  "cited_snippets": [{"index": 1, "source_url": "https://example.com", "snippet_text": "…"}],
  "judge_verdict": "SUPPORTED | UNSUPPORTED",
  "judge_reasoning": "…",
  "judge_model": "<the model that actually answered>",
  "timestamp": "…"
}
```

**The recorded judge model must be the model that actually answered**, not the one that was
requested. Recording a requested id while calling something else is a fabricated disclosure,
and router aliases make it easy to do by accident — an alias resolves per call and can
disagree with what served the request.

## 4. Systems under test

**System A — this pipeline.** Pinned commit, full per-role model routing disclosed, retrieval
chain and cache configuration stated.

**System B — an open-source baseline.** Pinned release and full configuration disclosed.

### Citation normalisation

A baseline that emits Markdown hyperlinks rather than numeric indices must be normalised
before scoring, without advantaging or disadvantaging it:

1. **URL canonicalisation** with an explicit tracking-parameter denylist (`utm_*`, `ref`,
   `fbclid`, `gclid`, `msclkid`, `mc_cid`, `_ga`, and similar). Content-differentiating
   parameters (`page`, `section`, `id`, `v`, `lang`, `tab`) are **preserved**, so distinct
   pages on one domain resolve to distinct indices rather than being merged.
2. **Index mapping** — each unique canonical URL gets a sequential index; identical URLs with
   different anchor text share one.
3. **Reference generation** — a normalised `{index, title, url, snippets}` table, where
   `snippets` holds the text actually scraped for that source.
4. **Body transformation** — inline links become `[n]` markers.
5. **Integrity** — wording and sentence boundaries are unmodified. Titles and reference
   headings are excluded from claim extraction.

> **The snippets must be real scraped text.** Scoring a baseline against the placeholder
> string an extractor emits on failure measures nothing and flatters the system doing the
> scoring. If a baseline's source text cannot be recovered, that run is **unmeasured**, not
> zero.

## 5. Excluded systems

Proprietary deep-research products are **excluded from v1**, for methodological reasons
rather than convenience:

1. **No run reproducibility.** Opaque backend routing, undocumented model swaps, and
   continuous prompt updates mean a score recorded on Monday cannot be verified by a third
   party on Friday.
2. **Non-deterministic retrieval.** Internal caches and paywall arrangements that cannot be
   isolated or controlled.
3. **Rate limits and session behaviour** that prevent uniform batch evaluation.

They may appear in a future revision as explicitly-labelled, non-reproducible snapshots.

## 6. Failure taxonomy

Every execution must report raw completions and classify failures:

| Code | Definition | Scoring impact |
|---|---|---|
| `TIMEOUT` | Exceeded the wall-clock ceiling | Counted as an incomplete run; excluded from quality aggregates |
| `NO_PARSABLE_EVIDENCE` | No structured evidence could be extracted | Counted as a run failure |
| `UNRESOLVED_MARKER` | A marker references a nonexistent reference entry | Penalises resolution rate |
| `UNSUPPORTED_CLAIM` | The judge ruled the claim ungrounded | Penalises support rate |
| `PROVIDER_ERROR` | Upstream rate limit or network abort | **Disclosed and excluded from the denominator**, never scored as a miss |

The last row is the one that distinguishes this from an ordinary scoreboard.

## 7. Execution protocol

```bash
# 1. Install evaluation dependencies
pip install -r backend/requirements.txt

# 2. Run the suite against both systems
cd backend && python -m evals.benchmark --output-dir evals/results/benchmark_v1

# 3. Inspect the generated summary
cat backend/evals/results/benchmark_v1/summary.md
```

A run is only publishable if it emits timestamped artifacts containing the full prompt
traces, extracted claims, judge rationales, and raw reports, so an independent party can
re-derive every number.

**Results are write-once.** Committed result files are never modified; a new run goes to a
new filename. CI enforces this.

## 8. What has actually been measured

The project's own evaluation harness — a different thing from the benchmark above, measuring
this pipeline alone with no comparison — has been run against real models several times, and
those results are committed under `backend/evals/results/`.

The most recent real-model run, `eval-2026-08-13-ollama-run7.json`, 10 queries:

| Metric | Result |
|---|---|
| Reports completed | 10 / 10 |
| Citation support rate | 0.90 |
| Citation resolution rate | 0.95 |
| Uncited claims | 14.9 per report (mean) |
| Latency | 514 s per report (mean) |
| Cost | $0.00 — local models |

**Stated plainly, because these caveats are the point of the page:**

- It **misses the 0.95 release threshold**.
- It is **self-judged**: the grader was the same local model that wrote the report — not a
  human, and not an independent model. That violates principle 2 of the methodology above,
  which is exactly why this is not presented as a benchmark result.
- Support rate answers "is this claim supported by what we extracted from the source it
  cites?", which is weaker than "is this claim true".
- Ten queries is a small set.

Treat it as a regression signal, not a benchmark. A hosted-model run on the same set
(`eval-2026-08-03.json`) recorded 0.9517 support and 0.9618 resolution across 10/10
completions, and `eval-2026-08-13-gemini.json` recorded **0 completions with every metric
`null`** — a run where the provider failed, preserved as evidence rather than deleted, and
correctly reported as unmeasured rather than as zero.

Each result file carries its own method block and a `metrics_version`, bumped whenever a
definition changes, so two runs are never silently compared across incompatible metrics.
