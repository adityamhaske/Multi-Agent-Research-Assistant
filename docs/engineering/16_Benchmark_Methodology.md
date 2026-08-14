# 16. Citation-Fidelity Benchmark Methodology

> **Document Status**: Active (M13 Specification)  
> **Version**: 1.0.0  
> **Scope**: Public, reproducible benchmark comparing citation grounding, structural resolution, and research efficiency across autonomous research agents.

---

## 1. Purpose & Core Principles

Most AI search and deep-research evaluations rely on qualitative human preference (ELO ratings) or opaque multi-metric rubrics where hallucinated citations cannot be disentangled from prose quality.

This benchmark establishes a **reproducible, citation-grounded evaluation** based on three principles:
1. **Verification Over Vibe**: A claim is either supported by its cited evidence or it is not. Structural resolution ($[n] \to \text{Source}$) is verified deterministically; factual support is judged with a zero-shot, independent LLM under a strict binary rubric.
2. **Fixed, Independent Judge**: The evaluation judge must never be the system under test or share model-family affinity with the generator.
3. **Reproducibility**: Every tool evaluated must be executable via a deterministic, self-hostable setup with pinned versions and public queries.

---

## 2. Fixed Query Set

The benchmark evaluates 10 versioned queries across 7 distinct domains ([`backend/evals/queries.json`](../../backend/evals/queries.json)). Queries are designed to require multi-source synthesis, recent factual grounding, or nuanced technical comparisons:

| ID | Domain | Depth | Query |
|---|---|---|---|
| `llm-memory` | AI | Balanced | What are the leading approaches to long-term memory in LLM agents, and their trade-offs? |
| `postgres-vs-mysql` | Software | Fast | For a new transactional web application, what are the practical trade-offs between PostgreSQL and MySQL in 2025? |
| `solid-state-batteries` | Energy | Comprehensive | What is the current state of solid-state battery commercialization and the main remaining engineering obstacles? |
| `ozempic-mechanism` | Health | Balanced | How do GLP-1 receptor agonists like semaglutide work, and what are the documented risks and open questions? |
| `carbon-capture-cost` | Climate | Balanced | How cost-effective is direct air capture of CO2 today compared with other carbon-removal methods? |
| `rust-adoption` | Software | Fast | Why are systems teams adopting Rust, and where does it still fall short versus C++? |
| `remote-work-productivity` | Economics | Balanced | What does the research say about the effect of remote work on productivity since 2020? |
| `quantum-error-correction` | Physics | Comprehensive | What recent progress has been made on quantum error correction, and how far are we from fault-tolerant machines? |
| `eu-ai-act` | Policy | Balanced | What obligations does the EU AI Act place on providers of general-purpose AI models? |
| `mediterranean-diet` | Health | Fast | What is the strength of evidence that the Mediterranean diet reduces cardiovascular risk? |

---

## 3. Metric Definitions & Scoring Rubric

All metrics are computed strictly on the generated report body (excluding metadata, reference lists, and system-rendered conflict blocks).

### 3.1 Structural & Deterministic Metrics

* **Total Citations ($C_{\text{total}}$)**: Count of all in-text numeric citation markers ($[n]$ or comma-separated groups $[1, 3]$).
* **Citation Resolution Rate ($R_{\text{cite}}$)**:
  $$\text{Resolution Rate} = \frac{C_{\text{total}} - C_{\text{unresolved}}}{C_{\text{total}}}$$
  Where $C_{\text{unresolved}}$ represents markers referencing an index not present in the report's reference list. Returns `None` if $C_{\text{total}} = 0$.
* **Uncited Claim Count ($U_{\text{claims}}$)**: Count of assertive sentences in the body that contain zero citation markers.
* **Contradictions Surfaced**: Count of distinct conflicting-evidence pairs surfaced and highlighted to the reader.
* **Wall-Clock Time**: Total seconds elapsed from query invocation to final synthesized report.
* **Cost (USD)**: Standardized cost calculated from token usage using fixed price catalog entries.

### 3.2 LLM-Judged Citation Support Rate

The **Citation Support Rate** ($S_{\text{cite}}$) evaluates whether the text snippet extracted from the cited source actually substantiates the claim made in the report.

$$\text{Support Rate} = \frac{\text{Number of Claims Judged YES}}{\text{Total Cited Claims}}$$

#### Judge Independence & Model Assignment
To prevent **same-vendor bias** (our pipeline defaults to Google Gemini; GPT-Researcher defaults to OpenAI):
* The judge model is **fixed, pinned, and disclosed**: `claude-sonnet-4-6` (Anthropic).
* **Rationale**:
  1. *Vendor Independence*: The judge shares no corporate or architectural lineage with Google (our generator) or OpenAI (GPT-Researcher).
  2. *Determinism*: `claude-sonnet-4-6` accepts explicit `temperature=0.0` for zero-shot binary consistency.
  3. *Instruction Precision*: Strong baseline on negative constraints without over-inferring unstated facts.
* The judge receives strictly the extracted sentence claim and the textual snippet(s) associated with its cited index. It has no access to the full report, system identities, or agent traces.

#### Verbatim Judge Prompt
```text
System:
You judge whether factual claims made in research reports are strictly supported by the cited evidence snippets.
For each numbered claim and evidence pair:
- Respond "Claim N: YES" if the evidence snippet directly corroborates the assertion.
- Respond "Claim N: NO" if the snippet does not contain sufficient facts to support the claim, if the claim extrapolates beyond the text, or if the snippet is irrelevant.
Do not assume external knowledge. Be strictly conservative.

Human:
For each claim below, determine if it is supported by its cited evidence.
Answer with one line per claim in format: "Claim N: YES" or "Claim N: NO"

Claim 1: <Extracted Sentence 1>
Evidence 1:
- <Snippet 1A>
- <Snippet 1B>

Claim 2: <Extracted Sentence 2>
Evidence 2:
- <Snippet 2A>
```

#### Trace Logging Schema
For every claim scored by the judge, the runner must capture a raw JSON trace containing the exact claim, the evidence snippet, and the judge's reasoning. This ensures results are fully auditable:

```json
{
  "query_id": "llm-memory",
  "system": "our_pipeline | gpt_researcher",
  "claim_text": "...",
  "cited_indices": [1, 2],
  "cited_snippets": [
    {"index": 1, "source_url": "https://example.com", "snippet_text": "..."}
  ],
  "judge_verdict": "SUPPORTED | UNSUPPORTED",
  "judge_reasoning": "...",
  "judge_model": "claude-sonnet-4-6",
  "timestamp": "2026-08-13T21:13:53Z"
}
```

---

## 4. Systems Under Test (SUT) Specifications

### 4.1 System A: Multi-Agent Research Assistant (This Repository)
* **Git Version / Commit**: Pinned commit hash at benchmark execution.
* **Architecture**: LangGraph-based state machine (`Planner` $\to$ `Executor` $\to$ `Critic` $\to$ `Synthesizer`).
* **Retrieval Engine**: Tavily Search API with fallback to DuckDuckGo; deduplicated URL cache.
* **Default Model Configuration**:
  * Planner: `gemini-2.5-flash`
  * Executor: `gemini-2.5-flash`
  * Critic: `gemini-2.5-flash`
  * Synthesizer: `gemini-2.5-flash`

### 4.2 System B: GPT-Researcher (Open-Source Baseline)
* **Pinned Release**: `gpt-researcher==3.2.4`
* **Configuration**:
  * `report_type`: `"research_report"`
  * `report_source`: `"web"`
  * `retriever`: `"tavily"`
  * `fast_mode`: Disabled (standard research mode)
  * `llm_model`: `gpt-4o-mini` (or matched tier model)

#### Citation Normalization Protocol
GPT-Researcher natively outputs Markdown hyperlinks (e.g. `[Source Name](https://example.com/article)`) instead of bracketed numeric indices (`[1]`). To apply the scoring harness without bias:
1. **URL Canonicalization & Tracking Denylist**: URLs are normalized using an explicit tracking parameter denylist (`utm_*`, `ref`, `ref_src`, `source`, `fbclid`, `gclid`, `gclsrc`, `dclid`, `msclkid`, `mc_cid`, `mc_eid`, `_ga`, `_gl`, `yclid`).
   * *Content Parameter Preservation*: Content-differentiating query parameters (such as `?page=`, `?section=`, `?id=`, `?v=`, `?lang=`, `?tab=`) are **strictly preserved**, ensuring distinct pages or sub-sections on the same domain resolve to distinct citation indices rather than being artificially merged.
2. **Index Mapping**: Map each unique canonical URL to a sequential identifier $[1..k]$. References with identical canonical URLs (even with different anchor text) resolve to the same $[n]$ index.
3. **Reference Generation**: Build a normalized sources table `{index, title, url, snippets}` where `snippets` contains the scraped paragraphs associated with that source.
4. **Body Transformation**: Replace inline markdown links with their corresponding $[n]$ markers.
5. **Integrity Rule**: Text wording and sentence boundaries are preserved unmodified. Document titles (`# Title`) and references headings (`## References`) are excluded from claim extraction.

---

## 5. Excluded Systems & Rationale (v1 Scope)

The following proprietary products are **explicitly excluded from v1** of this public benchmark:
* **Perplexity Pro (Deep Research)**
* **ChatGPT Deep Research (OpenAI)**
* **Gemini Deep Research (Google)**

### Methodological Reasons for Exclusion:
1. **Lack of Run Reproducibility**: Proprietary services execute opaque backend routing, undocumented model swaps, and continuous prompt updates. A score recorded on Monday cannot be verified by an independent third party on Friday.
2. **Non-Deterministic Scraping & Caching**: Proprietary web crawlers utilize internal enterprise search caches and dynamic paywall bypasses that cannot be isolated or controlled.
3. **Rate Limiting & Cost Unpredictability**: Closed tools enforce non-standardized account-level rate limits and variable session timeouts that prevent uniform batch evaluation across fixed query sets.

These systems may be included in future v2 revisions as non-reproducible reference snapshots, but are excluded from the primary reproducible benchmark.

---

## 6. Failure Taxonomy & Handling

Every benchmark execution must report raw completions and categorise any run failures into the following taxonomy:

| Failure Code | Definition | Scoring Impact |
|---|---|---|
| `TIMEOUT` | Execution exceeded maximum wall-clock ceiling (600s). | 0% completion; omitted from quality aggregates. |
| `NO_PARSABLE_EVIDENCE` | Model failed to extract or parse structured evidence. | 0% support rate; counted as run failure. |
| `UNRESOLVED_MARKER` | In-text marker $[n]$ references non-existent bibliography entry. | Penalizes Citation Resolution Rate directly. |
| `UNSUPPORTED_CLAIM` | Judge evaluates claim as ungrounded by snippet. | Penalizes Citation Support Rate directly. |
| `PROVIDER_ERROR` | Upstream rate-limit or network abort during retrieval. | Disclosed in report; run re-attempted once. |

---

## 7. Execution & Audit Protocol

To run the benchmark reproducibly:

```bash
# 1. Install evaluation dependencies
pip install -r backend/requirements.txt gpt-researcher==3.2.4

# 2. Run the complete benchmark suite against both systems
BENCHMARK_JUDGE_MODEL="claude-sonnet-4-6" python -m backend.evals.benchmark --output-dir backend/evals/results/benchmark_v1

# 3. Verify that results JSON and markdown summaries are generated
cat backend/evals/results/benchmark_v1/summary.md
```

All benchmark runs generate timestamped JSON artifacts containing full prompt traces, extracted claims, judge rationales, and raw reports to enable independent peer verification.
