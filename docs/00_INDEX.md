# Documentation Index

> These documents are the **build contract** for the Multi-Agent Research Assistant.
> Code that contradicts these docs is wrong; docs that contradict shipped code must be
> updated in the same PR that changes the behavior. No aspirational claims: every
> statement in these docs describes either (a) what is built, or (b) an item explicitly
> marked **[PLANNED]**.

## Layout

```
docs/
├── product/       vision, UX guidelines, roadmap, launch plan
├── architecture/  system design, tech stack, agent design, data & API
├── engineering/   security, testing, deployment, engineering standards
├── deep-dive/     narrative explainers — see deep-dive/00_INDEX.md
└── screenshots/   UI reference images used by the top-level README
```

## Documents

### Product (`product/`)

| # | Document | Purpose |
|---|----------|---------|
| 01 | [Product Vision](product/01_Product_Vision.md) | What we are building, for whom, positioning, and what we are explicitly NOT building |
| 07 | [UI/UX Guidelines](product/07_UIUX_Guidelines.md) | Academic design system, typography architecture, color matrix, citations UX, accessibility |
| 10 | [Roadmap](product/10_Roadmap.md) | Vertical-slice milestones with verifiable Definitions of Done |
| 12 | [v2 Launch Plan](product/12_Launch_Plan.md) | Local-first strategy, milestones M5–M17, budget, binding out-of-scope list |
| — | [Launch Go/No-Go](product/Launch_Go_No_Go.md) | Verification outcome and checklist for release readiness |

### Architecture (`architecture/`)

| # | Document | Purpose |
|---|----------|---------|
| 02 | [System Architecture](architecture/02_System_Architecture.md) | Topology, data flow, state machine, real-time layer |
| 03 | [Tech Stack](architecture/03_Tech_Stack.md) | Exact technologies, versions, and the justification for each |
| 04 | [Agent Design](architecture/04_Agent_Design.md) | LangGraph graph, node contracts, prompts, tools, structured outputs, budgets |
| 05 | [Data & API](architecture/05_Data_and_API.md) | Database schema, migration policy, REST + SSE contracts |
| 13 | [Local-First Architecture](architecture/13_Local_First_Architecture.md) | Engine extraction, ports/adapters, desktop packaging, offline tiers |
| 14 | [Projects & Project Memory](architecture/14_Projects_and_Memory.md) | Project containers, project-scoped chat, retrieval over approved research |

### Engineering (`engineering/`)

| # | Document | Purpose |
|---|----------|---------|
| 06 | [Security](engineering/06_Security.md) | Auth design, SSRF/prompt-injection defenses, rate limiting, headers, secrets |
| 08 | [Testing & Quality](engineering/08_Testing_and_Quality.md) | Test pyramid, golden E2E tests, evals, CI gates |
| 09 | [Deployment & Operations](engineering/09_Deployment_and_Operations.md) | Docker, environments, migrations, observability, runbook |
| 11 | [Engineering Standards](engineering/11_Engineering_Standards.md) | DOs/DON'Ts, code style, git conventions, review checklist |
| 15 | [Bundle Format](engineering/15_Bundle_Format.md) | Self-contained `.bundle.json` SBOM schema, hashing rules, and standalone verifier |

### Guides (`guides/`)

| Document | Purpose |
|----------|---------|
| [Local LLM Setup](guides/Local_LLM_Setup.md) | Setup and configuration guide for running local models via Ollama and LM Studio |

### Deep Dive (`deep-dive/`)

| # | Document | Purpose |
|---|----------|---------|
| 00 | [Deep Dive Index](deep-dive/00_INDEX.md) | Overview of narrative explainers across different architectural altitudes |
| 01 | [End-to-End System](deep-dive/01_End_to_End_System.md) | Comprehensive narrative walkthrough with principal-engineer review |
| 02 | [High-Level Design (HLD)](deep-dive/02_HLD.md) | System boundaries, 5 critical flows, failure modes, NFRs |
| 03 | [Low-Level Design (LLD)](deep-dive/03_LLD.md) | Module-by-module internals: graph nodes, auth, BYOK crypto, SSE, frontend |
| 04 | [Interview Defense](deep-dive/04_Interview_Defense.md) | Hard architectural questions and production bug post-mortems |

## How to use these docs

1. **Before implementing a feature**: read the relevant doc section. If the design is
   missing or ambiguous, update the doc first, then implement.
2. **Before merging a PR**: run the review checklist in
   [11_Engineering_Standards.md](engineering/11_Engineering_Standards.md).
3. **Milestone gates**: a milestone is complete only when its Definition of Done in
   [10_Roadmap.md](product/10_Roadmap.md) passes verbatim.

## Ground rules (learned the hard way)

The previous iteration of this project failed because docs and code diverged: the docs
described LangGraph checkpointing, Tavily, Kubernetes, and tests, while the code had a
hand-rolled loop, DuckDuckGo scraping, no Dockerfiles, and no tests — and the core
pipeline shipped broken at four separate points. The rules above exist to prevent that
class of failure. Specifically:

- **No "temporarily simplified" implementations of core mechanisms.** If the design says
  LangGraph checkpointing, we build LangGraph checkpointing in the first slice, not a
  stand-in loop "for M1".
- **Every vertical slice ends with an automated end-to-end test** proving the slice works
  through the real stack (see [08_Testing_and_Quality.md](engineering/08_Testing_and_Quality.md)).
- **Fail closed.** Parsing failures, missing data, and quality-gate errors stop the
  pipeline with a clear error; they never silently pass.
