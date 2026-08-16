# Plan: Researcher Workspace Overhaul

**Source**: free-form brief, 2026-08-16
**Audience**: academics, postdocs, PhD students, research-active undergrads
**Complexity**: Large — 8 phases, ~55 files, backend + frontend + desktop + docs
**Confirmed decisions**: desktop auto-start + web guided install · second human gate after Planner · sandboxed-iframe preview · keep the academic identity, fix the execution

---

## 0. Why anyone would leave Google Scholar and NotebookLM

This is requirement 7, and it is not a phase — it is the ordering principle for every
other phase. If the answer is weak, the rest is decoration.

| | What it does | Where it stops |
|---|---|---|
| **Google / Scholar** | Finds candidate sources | Hands you 10 blue links. Synthesis, cross-checking and citation discipline are entirely yours. No memory of what you already read. |
| **NotebookLM** | Grounded Q&A over documents **you already have** | Cannot go find the literature. Closed corpus, Google's models only, no local models, no exportable provenance, nothing self-hostable. |
| **Perplexity / GPT deep research** | Searches and writes | Citation is a link, not a verified quote. No human gate. No corpus of your own. Model choice is theirs. |

**The three things this product does that none of them do:**

1. **Every `[n]` is falsifiable.** A citation resolves to a source *and* a verbatim
   snippet, and one that cannot be verified renders a ⚠ chip instead of rendering clean.
   The `.bundle.json` export is a standalone, hash-verifiable SBOM of a report. That is
   the difference between something you can cite in a lit review and something you have
   to re-check by hand. This is the product.
2. **You approve the draft before it is final.** A durable checkpoint pauses the run and
   puts a human in the loop — the thing an advisor asks for and no chatbot offers.
3. **Your corpus and the open literature in one place, on your own keys or your own
   GPU.** Airgapped corpus mode makes zero network calls; local models mean an unpublished
   manuscript never leaves the machine. NotebookLM cannot do the first half; Scholar cannot
   do the second.

**What that means for this plan.** Phases are ordered by how much each one strengthens
that claim. Model attribution (Phase 1) and verified previews (Phase 6) are provenance
work. Connection health (Phase 2) exists because a tool nobody can start has no claim at
all. The design gate (Phase 4) is what turns "the agent chose 6 queries" into "I chose the
shape of my review". Nothing in this plan asks the product to be a better search box.

---

## 1. Requirements restatement

| # | Ask | Reading |
|---|---|---|
| 1 | Name the model each agent uses, in the planning phase | The run must disclose the **actually-dialled** `provider:model` per role, at plan time and in the report/export. Router aliases must never be shown as pinned models (AGENTS.md). |
| 2 | Modern, easy first impression; depth in Settings | Progressive disclosure: three things on first run, everything else behind a searchable settings IA. |
| 3 | As much customization as possible | Per-role models, budgets, retrieval, outline, prompts, exports, appearance, keyboard — with safe defaults and one-click reset. |
| 4 | Test API / custom / OpenRouter connections on save — red/yellow/green | Live credential probe returning a three-state verdict with a reason, on save and on demand. |
| 5 | Local LLM connected in one click, no terminal | Desktop starts/stops `ollama serve` itself; web detects, guides, and flips to green live. |
| 6 | Let users choose topics/subtopics and the document flow | A **plan review gate** after the Planner: edit subtopics, and pick/author the report outline. |
| 7 | Why replace Google / NotebookLM | Section 0 above; drives ordering. |
| 8 | Follow-up questions: web search **or** corpus only | Explicit per-message retrieval scope on both chat surfaces. |
| 9 | One project = one workspace, with in-app file preview | Project hub joining sessions, corpus, and agents; PDF/MD/TXT/HTML preview in place. |
| — | Rethink UI, colour, flow, ease of use; delete what doesn't belong | Phase 7 sweeps globally; every earlier phase ships to the refined system. |

---

## 2. Patterns to mirror (found in this codebase — do not reinvent)

| Category | Source | Pattern |
|---|---|---|
| Live probe endpoint | `backend/app/api/v1/models.py:229` `local_llm_status` | Live I/O kept *off* the catalog endpoint so the catalog stays instant and always renderable. Connection tests follow this split. |
| Honest three-state status | `backend/app/services/local_llm.py:196` | Status carries `reachable`, `usable`, **and** an actionable `hint`. Never a bare boolean. |
| Never-raises probe | `backend/app/services/local_llm.py:140` `probe()` | Every failure becomes a user-phrased status, never a 500. |
| Derived, never-stored readiness | `backend/app/api/v1/models.py:139` `get_readiness` | Computed per request, "because a stored flag desynchronises from reality". Connection health follows this — no cached green. |
| Fail-closed structured LLM call | `backend/research_engine/graph.py:84` `_structured` + `_last_api_error` | Provider errors surface their own message; retry once; report the real cause. |
| Durable human gate | `backend/research_engine/graph.py:1060` `hitl_gate_node`, `:1150` `route_after_gate` | LangGraph `interrupt()` + checkpointer. The plan gate is a second instance of exactly this. |
| Config as a `RunConfig` field | `backend/research_engine/runconfig.py:53` | Engine reads nothing from env/settings. New knobs become `RunConfig` fields with mirrored defaults. |
| Two-path config | `backend/app/runtime.py` + `backend/research_engine/local.py::run_config_from_env` | Every new field lands in **both**. |
| Progressive disclosure | `frontend/app/(app)/dashboard/page.tsx:202` | Collapsed disclosure that **names its own non-default state**. The model for every new options group. |
| Setup-first reordering | `frontend/app/(app)/settings/page.tsx:138`, `:211` | `order: -3/-2/-1` promotes setup blocks with a `role="note"` explaining the reshuffle. |
| Colour tokens only | `frontend/app/globals.css:26` | Define in `:root` **and** `.dark`; audit AA against both ground and card. |
| Agent hue as reinforcement | `frontend/lib/pipeline.ts:15` `AGENT_TOKEN` | Colour never the sole carrier — the rail also numbers and positions each node. |
| Remount over effect-derived state | `frontend/AGENTS.md` | `key={projectId}` instead of `setState` in an effect. |
| Resilient queue UI | `frontend/app/(app)/corpus/page.tsx:128` | Serial queue, per-item state, one failure never abandons the batch. |
| Tests | `frontend/lib/*.test.ts(x)` (vitest + RTL), `backend/tests/test_*.py` (pytest), `frontend/e2e/golden.spec.ts` | Behaviour-focused; absence-tests must not stub the mechanism under test. |

**No existing pattern for:** live provider credential probing, process spawning from the
Tauri shell, iframe-sandboxed document preview, or a second graph interrupt. Those are new
and are called out under Risks.

---

## 3. Phases

### Phase 0 — Design foundations (blocking; everything else ships into it)

Decision: keep the academic identity, fix the execution.

| File | Action | Why |
|---|---|---|
| `frontend/app/globals.css` | UPDATE | Add a spacing scale, a 6-step type scale, and `--radius-*`/`--density-*` tokens. Keep every existing colour token and its AA audit. |
| `frontend/components/ui/` | CREATE | Extract the four ad-hoc card/badge/field patterns (`Section`, `.card`, inline `border border-border bg-bg-surface`, `.badge`) into `Card`, `StatusDot`, `Field`, `Disclosure`, `EmptyState`, `Toolbar`. |
| `frontend/components/session/LiveFeed.tsx` | UPDATE | Replace 9 emoji section headers with the existing SVG icon vocabulary; move inline styling onto primitives. It is the single worst offender for visual drift. |
| `frontend/components/icons.tsx` | CREATE | Lift the 8 inline SVGs out of `SideNav.tsx` so nav, feed and preview share one icon set (24×24, 1.75 stroke). |
| `docs/product/07_UIUX_Guidelines.md` | UPDATE | Record the scales and the primitive inventory. Docs are the build contract. |

**Deletions in this phase** (things that do not belong):
`SideNav`'s "Navigation" section label (4 items need no header); the decorative `◇` in
three empty states; the duplicate New Research entry point (sidebar button and the
`/dashboard` nav item are the same route — keep the button); the Corpus page's "Telemetry
Status" heading (it is corpus stats, not telemetry); the standalone Appearance section
(folds into Phase 3's IA).

**Validate**: `npm run lint && npm run typecheck && npm test && npm run build`, plus the
four CI greps. Contrast-audit any touched token against both grounds in both themes.

---

### Phase 1 — Truthful per-agent model attribution (req 1)

The session already snapshots resolved routing (`session.model_routing`, set in
`backend/app/workers/pipeline_runner.py:84`) — it is simply never surfaced. The work is
disclosure, not plumbing.

| File | Action | Why |
|---|---|---|
| `backend/research_engine/graph.py` | UPDATE | Planner emits `detail.models = {role: route}` from `get_run_config().models`; each node stamps `detail.model` with the route it actually dialled. |
| `backend/research_engine/llm_factory.py` | UPDATE | Surface the **served** model id alongside the response where the provider reports one, so an `auto/*` alias is never displayed as a pinned model (AGENTS.md, "Router aliases are not pinned models"). |
| `backend/app/schemas/research.py` | UPDATE | Add `model_routing: dict[str,str] \| None` to `SessionDetail`. Third copy of this contract — see the `snippets` comment in `SourceSchema` for the identical bug. |
| `backend/desktop/sidecar.py` | UPDATE | Same field on the sidecar's session response. |
| `frontend/lib/types.ts` | UPDATE | `SessionDetail.model_routing`. |
| `frontend/components/session/PipelineRail.tsx` | UPDATE | Each node shows its model under the label; unresolved reads `—`, never a guess. |
| `frontend/components/session/ModelAttribution.tsx` | CREATE | A "Models used" block on the report and in the export header. |
| `backend/app/services/export.py` | UPDATE | Markdown/PDF/bundle carry the per-role table. |
| `backend/tests/test_model_attribution.py` | CREATE | A routing that differs per role renders per role; an alias is labelled as an alias. |

**Trap**: a run that failed before the planner must render "not resolved", not a default —
the unmeasured-vs-zero rule.

---

### Phase 2 — Connection health and one-click local models (reqs 4, 5)

**2a — Credential probe, red/yellow/green.**

| File | Action | Why |
|---|---|---|
| `backend/app/services/provider_health.py` | CREATE | `probe(provider, key, base_url) -> Verdict{state: ok\|degraded\|failed, reason, checked_at, model_count}`. Cheapest authenticated call per provider (models list where one exists; a 1-token completion otherwise). Never raises — mirrors `local_llm.probe`. |
| `backend/app/api/v1/models.py` | UPDATE | `POST /models/providers/test` (probe a submitted key **before** storing) and `GET /models/providers/health` (probe what is stored). Live I/O stays off `GET /models`. |
| `backend/app/api/v1/auth.py` | UPDATE | `PUT /me/api-key` returns the verdict inline, so saving *is* testing. |
| `backend/desktop/sidecar.py` | UPDATE | Same two endpoints against keychain-stored keys. Contract copy #2. |
| `frontend/components/account/ConnectionStatus.tsx` | CREATE | Three states with distinct shape **and** colour: ● green "Connected · 47 models", ◐ amber "Reachable, key rejected" / "quota exhausted", ○ red "No response". Never colour alone. |
| `frontend/app/(app)/settings/` | UPDATE | Probe on save, re-probe on demand, show `reason` verbatim. |
| `backend/tests/test_provider_health.py` | CREATE | Green/amber/red each asserted against a stubbed transport. **Do not stub `probe` itself** — that is the decorative-test trap from AGENTS.md. |

Amber is load-bearing: "server answered, key refused" and "nothing answered" have
different fixes, and collapsing them is what makes a status light useless.

**2b — Local LLM without a terminal.**

| File | Action | Why |
|---|---|---|
| `desktop/Cargo.toml`, `desktop/capabilities/default.json` | UPDATE | Add `tauri-plugin-shell` scoped to **exactly** the ollama binary. The shell holds only `core:default` today — that least-privilege posture gets narrowed deliberately, not widened. |
| `desktop/src/lib.rs` | UPDATE | `start_local_server` / `stop_local_server` commands; resolve the binary from standard install paths per OS. |
| `backend/app/services/local_llm.py` | UPDATE | Add `pull(model)` with streaming progress and `install_state` (`running` \| `installed_not_running` \| `not_installed`) — "Not detected" currently conflates two states with different fixes. |
| `backend/desktop/sidecar.py` | UPDATE | `POST /local/start`, `/local/stop`, `/local/pull`. |
| `frontend/components/account/LocalLLMCard.tsx` | UPDATE | Desktop: **Start local models** button → live progress → green. Web: OS-detected one-line command with copy button, a real installer link, and 2s polling that flips to green the moment the server appears. Recommended-model one-click pull with progress on both. |
| `docs/guides/Local_LLM_Setup.md` | UPDATE | Document the one-click path, and state plainly that the web build cannot spawn a process on your machine. |

**Honest boundary, stated in the UI**: the web build guides, the desktop build acts. Users
are told which they are on rather than handed a button that cannot work.

---

### Phase 3 — Settings IA and the customization surface (reqs 2, 3)

Today `frontend/app/(app)/settings/page.tsx` is one 452-line scroll of six unrelated
concerns. Split it into a searchable, sectioned surface — depth available, never in the way.

| File | Action | Why |
|---|---|---|
| `frontend/app/(app)/settings/layout.tsx` | CREATE | Left rail: Models · Connections · Research · Corpus · Exports · Appearance · Advanced. |
| `frontend/app/(app)/settings/[section]/page.tsx` | CREATE | One section per route; deep-linkable from anywhere that says "configure this". |
| `frontend/components/settings/SettingsSearch.tsx` | CREATE | Type-to-filter across every setting — the only thing that makes "as much customization as possible" survivable. |
| `frontend/components/settings/ResetToDefault.tsx` | CREATE | Per-setting revert. Deep customization without a way back is a trap. |
| `backend/app/models/user.py` + Alembic migration | UPDATE / CREATE | `preferences` JSON column. Migration for Postgres **and** the ORM model — the desktop reads `create_all` plus startup column sync (AGENTS.md). |
| `backend/research_engine/runconfig.py` | UPDATE | New fields: `outline_template`, `topic_seeds`, `retrieval_k`, `min_sources_per_task`, `snippet_max_chars`, `prompt_overrides`. Every one defaults to today's behaviour. |
| `backend/app/runtime.py` **and** `backend/research_engine/local.py` | UPDATE | Both config paths. This has drifted twice; it will drift a third time if only one is touched. |
| `backend/desktop/sidecar.py::sidecar_run_config` | UPDATE | Third path. |
| `docs/architecture/04_Agent_Design.md`, `docs/product/07_UIUX_Guidelines.md` | UPDATE | Same PR as the behaviour change. |

**Customization inventory to ship** (each with a default and a reset):
per-role model + temperature; depth→task-count mapping; `max_parallel_tasks`; all four
budget ceilings (0 = unlimited, already the convention); critic strictness and loop count;
retrieval `k`, chunk size, embedding model, corpus-vs-web weighting; citation density and
snippet length; report outline templates; export defaults (citation style, front matter,
demo stamping); density / theme / serif toggle; keyboard shortcuts.

**Anti-goal**: the first-run screen shows **three** things — ask a question, pick depth,
connect a model. Everything above lives in Settings and is reachable from the run form's
existing disclosure.

---

### Phase 4 — The research design gate: topics, subtopics, outline (req 6)

A second durable interrupt after the Planner. The 6-task cap in
`backend/research_engine/schemas.py::PlannerOutput._bounded` becomes a *default*, not a wall.

| File | Action | Why |
|---|---|---|
| `backend/research_engine/schemas.py` | UPDATE | `ResearchTask` gains `subtopics: list[str]`, `include: bool`, `source_hint`. `PlannerOutput` gains `proposed_outline: list[OutlineSection]`. Raise the cap; keep it configurable. |
| `backend/research_engine/graph.py` | UPDATE | `plan_gate_node` + `route_after_plan_gate`, mirroring `hitl_gate_node` / `route_after_gate`. Skipped entirely when the user's preference says so, so the extra pause is opt-out. |
| `backend/research_engine/prompts.py` | UPDATE | Planner accepts seeded topics as constraints; Synthesizer accepts an outline contract. |
| `backend/app/models/session.py` + Alembic migration | UPDATE / CREATE | `plan_json`, `outline_json`, `plan_approved_at`. Migration **and** ORM. |
| `backend/app/api/v1/research.py` | UPDATE | `GET/POST /{id}/plan`. Start request gains `topic_seeds`, `outline_template`, `skip_plan_gate`. |
| `backend/desktop/sidecar.py` | UPDATE | **Request→`Session(...)` fields have three homes and all three have been wrong before.** Wire the new fields in both hosts. |
| `frontend/components/session/PlanGate.tsx` | CREATE | Add / remove / reorder / edit subtopics; drag-order outline sections; live cost estimate that moves as you edit. |
| `frontend/components/session/OutlineTemplatePicker.tsx` | CREATE | Ship four: **Literature Review** (background → methods → findings → gaps), **Systematic Comparison**, **Methods Survey**, **Custom**. Templates are `RunConfig` data, not prompt text hardcoded in the UI. |
| `frontend/components/session/PipelineRail.tsx` | UPDATE | Six nodes: Plan review sits between Planner and Executor, same visual grammar as the Review node. |
| `backend/tests/test_plan_gate.py` | CREATE | Resume-after-edit is checkpoint-durable; an edited plan actually changes what the executor runs; `skip_plan_gate` bypasses cleanly. |

**The value**: for a PhD student this is the difference between "the agent picked 6
queries" and "these are my six subtopics, in my review's structure". It is also where cost
becomes visible *before* it is spent.

---

### Phase 5 — Scoped follow-up questions (req 8)

Two chat surfaces exist and neither can search:
`frontend/components/session/ChatPanel.tsx` is grounded in one report's sources;
`frontend/components/chat/ProjectChatPanel.tsx` is grounded in project memory
(`backend/app/services/memory.py::retrieve`). Web search in follow-ups is new capability.

| File | Action | Why |
|---|---|---|
| `backend/app/schemas/research.py`, `backend/app/schemas/chat.py` | UPDATE | `ChatRequest.scope: "report" \| "corpus" \| "web" \| "auto"`. |
| `backend/app/api/v1/chat.py`, `backend/app/api/v1/threads.py` | UPDATE | Route scope into retrieval; `web` runs the retriever chain and returns new sources; `corpus` asserts zero egress. |
| `backend/research_engine/prompts.py` | UPDATE | Per-scope grounding instructions. Keep `PROJECT_CHAT_PROMPT`'s refusal line — it is load-bearing and its DoD tests for it. |
| `backend/desktop/sidecar.py` | UPDATE | Contract copy. |
| `frontend/components/chat/ScopeSelector.tsx` | CREATE | Segmented control above the composer: **This report · My corpus · Web · Everything**, each naming what it will and will not touch. |
| `frontend/components/session/ChatPanel.tsx`, `frontend/components/chat/ProjectChatPanel.tsx` | UPDATE | Mount the selector; the answer states which scope produced it. |
| `backend/tests/test_chat_scope_egress.py` | CREATE | Corpus scope makes **zero** network calls — and per AGENTS.md, assert that without stubbing the thing that would egress. `test_corpus_egress.py` was green for exactly that reason once. |

---

### Phase 6 — The project workspace and in-app preview (req 9)

Today a project is a filter applied to four unrelated pages. Make it a place.

| File | Action | Why |
|---|---|---|
| `frontend/app/(app)/project/page.tsx` | CREATE | Project hub: recent runs, corpus at a glance, agent/model config, memory status, "what this project knows" — one view. Becomes the default landing page when a project is active. |
| `frontend/components/preview/DocumentPreview.tsx` | CREATE | Route by type. **PDF** → `<object>` off the existing `/documents/{id}/download`. **MD** → the `react-markdown` + `remark-gfm` pipeline reports already use. **TXT** → `<pre>`. **HTML** → `<iframe sandbox="" srcdoc=…>`, no scripts, no same-origin, strict CSP. `dangerouslySetInnerHTML` and `rehype-raw` stay banned; CI greps for both. |
| `frontend/components/preview/PreviewDrawer.tsx` | CREATE | Opens in place from corpus rows **and** from citation hovercards — clicking `[3]` should show you the page, not download it. |
| `backend/research_engine/documents.py` | UPDATE | Accept `.html`/`.htm`; extract text for indexing while keeping the original for preview. Update the rejection message in `kind_for` in the same edit. |
| `frontend/app/(app)/corpus/page.tsx` | UPDATE | Rows open the preview; "Open" downloads only on request. |
| `backend/app/api/v1/corpus.py` | UPDATE | `Content-Disposition: inline` for previewable types; `Content-Security-Policy` and `X-Content-Type-Options: nosniff` on the download route. |
| `backend/app/services/security_headers.py` | UPDATE | CSP must allow the sandboxed frame without loosening the page's own policy. |
| `frontend/components/ActiveProject.tsx`, `frontend/components/SideNav.tsx` | UPDATE | Nav becomes project-first: **Overview · Research · Corpus · Chat**, all under the active project. |
| `frontend/e2e/golden.spec.ts` | UPDATE | Upload → preview → cite → click citation → preview opens at the right document. |

**Security note**: uploaded HTML is untrusted content rendered in the user's browser. The
sandbox attribute — not a sanitizer — is the boundary, and the ingest path must never
render it any other way.

---

### Phase 7 — Global UX pass, deletions, accessibility

| File | Action | Why |
|---|---|---|
| `frontend/app/(app)/dashboard/page.tsx` | UPDATE | Reduce to question + depth + one **Options** disclosure that names its own state. The pattern is already there and already good — extend, don't replace. |
| `frontend/components/session/LiveFeed.tsx` | UPDATE | Collapse 9 detail blocks into 4 semantic groups: Reasoning · Evidence · Verdict · Draft. Density toggle. |
| `frontend/components/session/StatusBar.tsx`, `SessionCard.tsx`, `StatusBadge.tsx` | UPDATE | One status vocabulary across list, card and detail. |
| `frontend/app/(app)/history/page.tsx` | UPDATE | Filter by project, depth, verified-citation rate, model. |
| all touched components | UPDATE | Full keyboard path; `focus-visible` on every interactive element; `aria-live` correct on the feed; AA re-audit for every token pair that moves surface. |
| `docs/product/07_UIUX_Guidelines.md`, `docs/product/01_Product_Vision.md` | UPDATE | Record the IA and the positioning from §0. |
| `README.md`, `docs/screenshots/` | UPDATE | Regenerate via `npm run screenshots`. |

**Confirmed deletions** (nothing that carries meaning): duplicate New Research entry point;
the "Navigation" rail label; `◇` decorative glyphs; `LiveFeed` emoji headers; the
"Telemetry Status" mislabel; the standalone Appearance block; the `showAdvanced` local
state superseded by the settings IA.

---

## 4. Validation

Green locally is not green in CI. Run what CI runs, per phase:

```bash
cd backend && ruff check app/ research_engine/ tests/ evals/ && ruff format --check app/ research_engine/ tests/ evals/ && python -m pytest
```

```bash
cd frontend && npm run lint && npm run typecheck && npm test && npm run build
```

```bash
cd frontend && npm run e2e
```

Plus, before any phase is called done:

- The four frontend CI greps (`dangerouslySetInnerHTML`/`rehype-raw`, hex colours, backend
  URLs, web storage). `npm run lint` does not catch these.
- **Grep for the second home** of every changed contract: config → `app/runtime.py` +
  `research_engine/local.py`; request→session → `app/api/v1/research.py` +
  `desktop/sidecar.py`; per-session run config → `app/workers/pipeline_runner.py` +
  `sidecar.py::_drive_session`; routing validation → `model_routing.validate` +
  `llm_factory.validate_pricing` + `sidecar.validate_routing` (**three** copies).
- Any schema change has an Alembic migration **and** an ORM model change.
- Desktop bundle launched, not just built — artifact ~180 MB, not ~5 MB.
- Nothing new written under `backend/evals/results/`.

---

## 5. Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| **Desktop/server divergence** — every phase touches a two-host contract | **High** | High | Per-phase grep checklist above; prefer extracting one shared function (`map_local_host` is the worked example) over keeping copies in step by discipline. |
| Second graph interrupt corrupts resume | Medium | High | Mirror `hitl_gate_node` exactly rather than inventing a mechanism; checkpoint-durability test lands before any UI. |
| `tauri-plugin-shell` widens the shell's attack surface | Medium | High | Scope the capability to the ollama binary only; the shell holds `core:default` today and that is a deliberate posture, not an accident. |
| Sandboxed HTML preview escapes | Low | High | `sandbox=""` (no `allow-scripts`, no `allow-same-origin`) + CSP + `nosniff`; the ban stays enforced by CI grep. |
| Provider probe leaks a key into logs | Medium | High | Probe never logs the key; structlog binds provider + verdict only; the existing `api_key_hint` (last 4) is the only display form. |
| Probe cost / rate-limits | Medium | Low | Cheapest authenticated call; debounced; never on page load without user action. |
| Customization surface becomes unmaintainable | **High** | Medium | Every knob is a `RunConfig` field with a default mirroring today's behaviour, a reset, and one owning doc section. Settings search is not optional. |
| Contrast regressions from density/spacing work | Medium | Medium | Colour tokens are not changing; re-audit any pair that moves surface. |
| Golden E2E churn across 8 phases | High | Medium | Update `golden.spec.ts` inside each phase, never batched at the end. |
| Scope: this is 8 phases, not one PR | **Certain** | — | Each phase is independently shippable and independently green. Phases 1 and 2 deliver most of the trust and setup value on their own. |

---

## 6. Acceptance

- [ ] Every phase ships with backend + frontend + **desktop** + docs updated together
- [ ] `provider:model` shown per agent at plan time, in the report, and in all three exports — aliases labelled as aliases, unresolved shown as unresolved
- [ ] Saving a key returns green/amber/red with a reason; amber distinguishes "key refused" from "no response"
- [ ] Desktop starts a local model server from one button; web guides and auto-detects
- [ ] A user can edit subtopics and pick the report outline before any search spends money
- [ ] Follow-up questions can be pinned to report, corpus, or web, and say which was used
- [ ] PDF, MD, TXT and HTML preview in place, reachable from both the corpus list and a citation
- [ ] All four CI greps pass; both CI command blocks green; desktop bundle launched and ~180 MB
- [ ] Every deleted element is deleted because it carried no meaning — listed, not silently dropped
