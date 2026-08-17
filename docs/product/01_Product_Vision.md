# 01. Product Vision & Scope

## One-liner

**A self-hostable, bring-your-own-key research assistant with an auditable
human-in-the-loop approval gate and verifiable per-claim citations.**

A user submits a research question. A pipeline of specialized agents (Planner →
Executor → Critic → Synthesizer) searches the web, gathers evidence with sources,
quality-checks it, and drafts a cited Markdown report. The user reviews the draft at a
mandatory approval gate — approving finalizes the report, rejecting with feedback sends
it back for rework. Completed reports support follow-up chat grounded in the report and
its sources. Every approval decision is recorded in an audit log.

## Why this exists (positioning, mid-2026)

"Deep research" is a commodity: ChatGPT, Gemini, Perplexity, and Claude all bundle
autonomous research agents at $0–20/mo, and open source has strong generic entrants
(GPT-Researcher, STORM, Onyx). We do not compete with any of them head-on. Our wedge is
the combination of three things none of them package together:

1. **Auditable human oversight.** A mandatory review gate with a recorded
   approve/rework trail. The EU AI Act's human-oversight requirements (Art. 14, in force
   Aug 2026) make this a compliance story, not just a UX preference.
2. **Verifiable citations.** Per-claim provenance: every factual claim links to a source
   with the exact supporting snippet. Independent research (Tow Center, 2025) shows AI
   search misattributes citations >60% of the time — trust is the category's biggest
   unsolved problem and does not require frontier-model scale to solve.
3. **Self-hosting + BYOK.** Users run it on their own infrastructure with their own
   model API keys. Their queries and reports never transit a third-party SaaS. This also
   makes the unit economics honest: the operator pays for exactly what they use.

## Why a researcher would leave Scholar or NotebookLM

The positioning above answers "why not ChatGPT deep research". This one answers the
question an academic actually asks, and it is the ordering principle behind the
2026 workspace overhaul rather than a phase of it.

| | What it does | Where it stops |
|---|---|---|
| **Google / Scholar** | Finds candidate sources | Hands you ten blue links. Synthesis, cross-checking and citation discipline are entirely yours, and it remembers nothing you have already read. |
| **NotebookLM** | Grounded Q&A over documents **you already have** | Cannot go find the literature. Closed corpus, Google's models only, no local models, no exportable provenance, nothing self-hostable. |
| **Perplexity / GPT deep research** | Searches and writes | A citation is a link, not a verified quote. No human gate. No corpus of your own. The model choice is theirs. |

Three things this does that none of them do:

1. **Every `[n]` is falsifiable.** A citation resolves to a source *and* a verbatim
   snippet, and one that cannot be verified renders a ⚠ chip rather than rendering
   clean. `citation_resolution_rate` puts that on every row of History — including a
   `Not measured` band, because "made no citable claims" and "every marker is broken"
   are opposite findings. The `.bundle.json` export is a standalone, hash-verifiable
   record of a report. That is the difference between something citable in a lit review
   and something you have to re-check by hand.
2. **You approve the shape *and* the draft.** Two durable checkpoints: a design gate
   after the planner, where subtopics and the report outline are still free to change
   and nothing has been spent, and the draft gate before anything is final. The first is
   the difference between "the agent picked six queries" and "these are my six
   subtopics, in my review's structure".
3. **Your corpus and the open literature in one place, on your own keys or your own
   GPU.** Airgapped corpus mode makes zero network calls; local models mean an
   unpublished manuscript never leaves the machine. Follow-up questions carry an
   explicit scope, so "answer from my uploads only" is a guarantee rather than a hope.
   NotebookLM cannot do the first half; Scholar cannot do the second.

Nothing here asks the product to be a better search box.

## Target users

| Persona | Need | What they value |
|---|---|---|
| **AI/ML engineer (portfolio reviewer)** | Evaluate the author's engineering ability | Working end-to-end demo, real LangGraph usage, tests, clean architecture |
| **Privacy-conscious professional / SMB** | Recurring research without sending data to a SaaS | One-command self-host, BYOK, no telemetry |
| **Team with oversight requirements** | Research outputs that survive review/audit | Approval gate, audit log, per-claim sources, export |

## Product principles

1. **The report must be trustworthy before it is impressive.** Citation fidelity beats
   prose quality. A claim without a source does not ship.
2. **The human gate is a feature, not friction.** We never auto-finalize. The gate is
   fast to use (approve in one click) but always present and always logged.
3. **Fail closed, fail loudly.** A degraded pipeline (search down, parse failure, budget
   exceeded) produces an explicit failed state with a reason — never a silently thinner
   report.
4. **Honest economics.** Free-tier scraping and free-tier model quotas are acceptable
   for a single self-hosted user, never assumed for multi-user deployments. BYOK is the
   default mental model.
5. **The repo is the product.** For the portfolio audience, code quality, docs accuracy,
   and CI health are user-facing features.

## Scope

### In scope (v1)

- Email/password auth (self-host friendly; no external IdP required)
- Research sessions: submit query + depth; pipeline runs in background worker
- Live progress feed (SSE) with persisted, replayable agent logs
- Human approval gate: approve → finalize; reject + feedback → rework loop
- Completed-report chat grounded in report + sources
- Per-claim citations with source snippets; sources panel
- Export: Markdown and PDF
- Session history with cost/token/duration stats
- Audit log of approval decisions
- BYOK: Gemini by default; provider-pluggable LLM factory
- Multi-retriever web search with fallback (Tavily → Brave → DuckDuckGo) and caching
- One-command local run (`docker compose up`) and documented production deploy

### Out of scope (v1) — explicitly

- Payments, plans, or any billing infrastructure
- Team/multi-tenant features (orgs, roles, shared workspaces)
- Social login / OAuth providers
- Document upload & hybrid research **[PLANNED v2]**
- Scheduled/recurring research with diffs **[PLANNED v2]**
- Kubernetes manifests **[PLANNED — only after a real need exists]**
- Mobile apps

## Success criteria

- A new user can go from `git clone` to an approved, exported, cited report in under
  15 minutes using only the README.
- The three golden E2E tests (see [08](../engineering/08_Testing_and_Quality.md)) pass in CI on every
  commit to `main`.
- Citation eval: ≥95% of claims in generated reports link to a source whose snippet
  actually supports the claim, measured by the eval harness on the fixed query set.
- Zero critical/high findings open from the security checklist in
  [06_Security.md](../engineering/06_Security.md) at release tag.
