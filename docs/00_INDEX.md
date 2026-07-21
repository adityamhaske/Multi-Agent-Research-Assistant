# Documentation Index

> These documents are the **build contract** for the Multi-Agent Research Assistant.
> Code that contradicts these docs is wrong; docs that contradict shipped code must be
> updated in the same PR that changes the behavior. No aspirational claims: every
> statement in these docs describes either (a) what is built, or (b) an item explicitly
> marked **[PLANNED]**.

## Documents

| # | Document | Purpose |
|---|----------|---------|
| 01 | [Product Vision](01_Product_Vision.md) | What we are building, for whom, positioning, and what we are explicitly NOT building |
| 02 | [System Architecture](02_System_Architecture.md) | Topology, data flow, state machine, real-time layer |
| 03 | [Tech Stack](03_Tech_Stack.md) | Exact technologies, versions, and the justification for each |
| 04 | [Agent Design](04_Agent_Design.md) | LangGraph graph, node contracts, prompts, tools, structured outputs, budgets |
| 05 | [Data & API](05_Data_and_API.md) | Database schema, migration policy, REST + SSE contracts |
| 06 | [Security](06_Security.md) | Auth design, SSRF/prompt-injection defenses, rate limiting, headers, secrets |
| 07 | [UI/UX Guidelines](07_UIUX_Guidelines.md) | Design system, page specs, states, citations UX, accessibility |
| 08 | [Testing & Quality](08_Testing_and_Quality.md) | Test pyramid, golden E2E tests, evals, CI gates |
| 09 | [Deployment & Operations](09_Deployment_and_Operations.md) | Docker, environments, migrations, observability, runbook |
| 10 | [Roadmap](10_Roadmap.md) | Vertical-slice milestones with verifiable Definitions of Done |
| 11 | [Engineering Standards](11_Engineering_Standards.md) | DOs/DON'Ts, code style, git conventions, review checklist |

## How to use these docs

1. **Before implementing a feature**: read the relevant doc section. If the design is
   missing or ambiguous, update the doc first, then implement.
2. **Before merging a PR**: run the review checklist in
   [11_Engineering_Standards.md](11_Engineering_Standards.md).
3. **Milestone gates**: a milestone is complete only when its Definition of Done in
   [10_Roadmap.md](10_Roadmap.md) passes verbatim.

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
  through the real stack (see [08_Testing_and_Quality.md](08_Testing_and_Quality.md)).
- **Fail closed.** Parsing failures, missing data, and quality-gate errors stop the
  pipeline with a clear error; they never silently pass.
