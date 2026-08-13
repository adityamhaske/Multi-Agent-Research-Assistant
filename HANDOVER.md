# HANDOVER → Antigravity

> **Read this whole file first.** It is the complete brief for the one pending task, plus
> the project orientation you need to do it safely. Everything here was verified against
> real code and real eval runs, not milestone checkboxes.

---

## 0. What this project is

A **citation-grade multi-agent deep-research assistant**. A LangGraph pipeline
(`planner → executor ⇄ critic → contradiction_detector → synthesizer → HITL gate →
finalizer`) searches the web, gathers verbatim evidence, and writes a Markdown report
where every claim carries an inline `[n]` citation that is machine-checked against the
source snippet. The product's whole pitch is *citation fidelity*, enforced by an eval
harness with hard numeric bars.

- Backend engine: `backend/research_engine/` (pure, host-agnostic).
- API host: `backend/app/`. Evals: `backend/evals/`. Tests: `backend/tests/`.
- Authoritative milestone list + Definitions of Done: `docs/product/12_Launch_Plan.md`.
- Build contract: `docs/product/01_Product_Vision.md` … `docs/engineering/11_Engineering_Standards.md`.

**Binding constraints (do not violate):**
1. **Cost is a design constraint.** Never run inference on our own infra for end-users;
   prefer local/Ollama models for any intermediate measurement.
2. **Security is a SQL predicate — fail closed everywhere.** Untrusted web content is
   always wrapped in `<untrusted_web_content>`; a hallucinated/injected source must never
   reach a report.
3. **Do not trust milestone checkboxes.** Verify every "done" claim against actual code
   and a real eval run.
4. **Conventional commits** (`feat/fix/chore/docs/refactor/test`), small and focused.

---

## 1. Where things stand (verified)

| Milestone | State | Evidence |
|---|---|---|
| v1.0.0 release | ✅ shipped (interim, documented numbers) | tag live, CI green |
| M9 Desktop (Tauri + PyInstaller sidecar) | ✅ shipped | 3-OS desktop CI green |
| M10 Airgapped corpus mode (LAUNCH) | ✅ shipped | zero-egress test proves no outbound sockets |
| **M11 Contradiction detection** | 🟡 **mechanism done & committed; FP bar is the only gap** | see below |
| M12 Research bundle + offline verifier | ⬜ not started | |
| M13 Public citation-fidelity benchmark | ⬜ not started | |
| M14+ Flywheel | ⬜ not started | |

Backend suite is **green: 298 passed, 1 skipped**; `ruff check app/ research_engine/
tests/ evals/` is clean. This was re-verified immediately before this handover.

---

## 2. M11 — what is ALREADY built (do not rebuild)

M11 detects conflicting claims across evidence sources and surfaces them as a first-class
report block **without ever resolving them** (the human HITL gate adjudicates). It is
complete, tested, and on `main`:

- **`research_engine/contradictions.py`** — pure module: `group_snippets_by_source`,
  `build_detector_input`, `validate_pairs`, `render_block`, `insert_block`. Unit-tested.
- **`research_engine/graph.py::contradiction_detector_node`** — one bounded LLM call over
  the capped snippet set, routed on the **`critic`** role (temperature-0 adjudication).
  **Fail-closed**: an unavailable/unparseable detector surfaces *nothing*.
- **`research_engine/schemas.py::ContradictionPair` / `ContradictionReport`** — structured
  output; `pairs` capped at 10.
- **`research_engine/prompts.py::CONTRADICTION_DETECTOR_PROMPT`** — the detector prompt.
- **`evals/metrics.py`** — `contradictions_surfaced()` metric; `METRICS_VERSION` bumped to 4;
  the conflict block is excluded from claim-extraction so it isn't judged as claims.
- **`tests/test_contradictions.py`** — 12 tests, all passing.

### M11 Definition of Done (`docs/product/12_Launch_Plan.md`, M11) — status

| DoD item | Status |
|---|---|
| ≥ 80% **recall** on known-contradictory fixtures | ✅ **1.0** (measured) |
| ≤ 10% **false-positive rate** on known-consistent controls | ❌ **0.33** — THE GAP |
| Conflicts render in report, export, and PDF | ✅ block inserts before `## Sources` |
| New eval metric `contradictions_surfaced` recorded in baseline | ✅ METRICS_VERSION=4 |

**So the single remaining M11 item is driving the false-positive rate ≤ 0.10.**

---

## 3. The measurement setup (how the bar is scored)

- Fixtures: **`backend/evals/contradictions.json`** — 6 `contradiction` cases + 12
  `consistent` control cases. Ground truth is baked into each case's `expect`.
- Scorer: **`backend/evals/contradiction_eval.py`**. Bars: `MIN_RECALL = 0.80`,
  `MAX_FALSE_POSITIVE = 0.10`. It calls `contradiction_detector_node` directly per case.
- Best honest measurement so far (on the local 7B `qwen2.5`):
  **`backend/evals/results/contradictions_2026-08-13_172600.json`** →
  `recall = 1.0`, `false_positive_rate = 0.3333`, `fp_ok = false`.

### Why the 7B model can't pass the FP bar (already root-caused — don't redo this)

The 4 stable false positives are `k2-different-subjects`, `k8-precision-vs-rounding`,
`k9-base-vs-ceiling`, `k10-different-periods` — all **numeric near-misses**. The detector
prompt *already* forbids these (rules about same-subject/same-period/scope, overlapping
ranges). Three prompt iterations did not move the FP set, and adding a hedge/estimate rule
left FP unchanged while *hurting* recall (that experiment was reverted). Conclusion: **this
is a 7B model-capacity floor, not a prompt or architecture bug.** A more capable model is
needed to measure the bar honestly.

### The chosen path (user decision)

**Add reasoning-model output support so the local `deepseek-r1:14b` can be used to measure
the M11 FP bar.** It is already pulled locally (`ollama list` → `deepseek-r1:14b`, 9 GB),
costs nothing, and keeps us off the paid Gemini API (whose quota is currently exhausted).
This work also directly de-risks M15 (local LLM, first-class).

---

## 4. THE PENDING TASK — root cause already found (this is the important part)

Running the eval against `deepseek-r1:14b` currently scores **recall 0.0 AND fp 0.0**
(nothing detected in any case). **This is NOT a think-block or JSON-parse failure.** A
diagnostic reproduced the exact node call and found the real cause:

**`deepseek-r1` correctly identifies the contradiction and produces the right claims, but
it mis-fills the `ContradictionPair` fields.** For fixture `c1-market-size` it returned:

```
claim_a  = "Global electric vehicle sales reached 17.1 million units in 2024…"   ✅ right
snippet_a = "https://example.org/reports/ev-market-2024"                        ❌ this is the URL
source_a  = "Source: https://example.org/reports/ev-market-2024"                ❌ "Source:" prefix
```

i.e. it shifted the values: URL went into `snippet_a`, and the literal `"Source: <url>"`
label went into `source_a`. Then **`contradictions.validate_pairs` (line ~92) drops the pair**
because `source_a`/`source_b` are not in the known-URL set. Every pair gets dropped → zero
detections across the board.

Supporting facts from the same diagnostic:
- The **default** `with_structured_output(schema, include_raw=True)` method returns valid
  JSON with **no `` block** in `.content` — parsing itself is fine.
- `method="function_calling"` → Ollama 400: `deepseek-r1:14b does not support tools`.
- `method="json_mode"` → parses, but the model invents the wrong top-level keys
  (`"contradictions"` instead of `"pairs"`) → empty result. So **use the default method.**

### The fix (recommended, preserves the security invariant)

Fix at the **schema/prompt** level so the model emits correct fields. **Do NOT loosen
`validate_pairs`** — it is the fail-closed boundary that keeps injected/hallucinated
sources out of the report.

1. **`schemas.py::ContradictionPair`** — add explicit `Field(description=…)` to each field,
   e.g. `claim` = "your one-sentence restatement of the conflict side"; `snippet` = "the
   VERBATIM snippet text exactly as shown (not a URL)"; `source` = "the source URL exactly
   as shown after 'Source:' (no prefix, no extra text)". Field descriptions flow into the
   structured-output schema the model sees and are the highest-leverage change.
2. **`prompts.py::CONTRADICTION_DETECTOR_PROMPT`** — make rule 4 explicit about field
   semantics (snippet = quoted text, source = bare URL).
3. Optionally, a **defensive normalization** in the node before `validate_pairs`: strip a
   leading `"Source: "` from `source_*`, and if a `source_*` is not a known URL but the
   corresponding `snippet_*` *is* a known URL, swap them. Keep this narrow and still subject
   to `validate_pairs` (don't bypass the known-URL check).
4. After the change, `deepseek-r1:14b` should start detecting the 6 real contradictions
   (recall) and — being a far more capable model — clear the ≤ 0.10 FP bar.

### Then measure and record

```bash
cd backend && \
LLM_MODE=real \
MODEL_CRITIC=ollama:deepseek-r1:14b MODEL_PLANNER=ollama:deepseek-r1:14b \
MODEL_EXECUTOR=ollama:deepseek-r1:14b MODEL_SYNTHESIZER=ollama:deepseek-r1:14b \
MODEL_CHAT=ollama:deepseek-r1:14b \
GOOGLE_API_KEY=placeholder OLLAMA_BASE_URL=http://localhost:11434/v1 \
.venv/bin/python -m evals.contradiction_eval
```

- Expect ~15–40 s per case (it's a 14B reasoning model run locally).
- The scorer writes a dated JSON to `backend/evals/results/` and prints
  `recall_ok` / `fp_ok`. **The bar passes only when `recall_ok == true` AND `fp_ok == true`.**
- Keep the passing result JSON; it becomes the M11 baseline artifact.
- Gotcha: if you hit `No price for routed model(s): ['deepseek-r1']`, add a `ModelSpec`
  for `deepseek-r1` to `research_engine/catalog.py` (local models price to 0 — but note
  `validate_pricing` refuses unpriced *routed* models; the eval path tolerated it in
  testing, so only add the spec if you actually hit the error).

### Acceptance for closing M11
- `recall ≥ 0.80` **and** `false_positive_rate ≤ 0.10` on a real (non-fake) model run.
- Full backend suite + ruff still green.
- Commit the passing result JSON + any schema/prompt/normalization changes.
- Then update `docs/product/12_Launch_Plan.md` M11 checkbox **only after** the above.

---

## 5. After M11 — continue the roadmap in strict order

- **M12 — Research bundle + offline verifier**: open bundle format (report, claims,
  evidence + source URLs **with content hashes**, full agent trace, models, costs, approval
  record) + a **standalone no-AI no-network verifier** that checks every citation resolves
  and the trace is intact; a tampered bundle must fail with a human-readable reason.
- **M13 — Public citation-fidelity benchmark**: publish `backend/evals/` as a reproducible
  benchmark with dated, model-versioned results and our own failure cases.
- **M14+ — Flywheel**: connector SDK/registry, audit replay, hosted workspaces.

---

## 6. Useful commands

```bash
cd backend
.venv/bin/python -m pytest -q                         # full suite (expect 298 passed, 1 skipped)
.venv/bin/ruff check app/ research_engine/ tests/ evals/   # CI-gated lint scope
.venv/bin/python -m pytest tests/test_contradictions.py -q # M11 mechanism tests
ollama list                                            # confirm deepseek-r1:14b present
```

**Your mission, in one line:** make `deepseek-r1:14b` fill `ContradictionPair` correctly
(schema field descriptions + prompt clarity, optionally a narrow normalization), re-run the
contradiction eval, and get `recall_ok` and `fp_ok` both true — then commit and close M11,
and proceed to M12.
