# Deep Dive — Understanding This Project in Detail

Four documents that explain the system from four different altitudes. Read them in
order if you're new; jump straight to the one you need if you're not.

| # | Document | Written for | Answers |
|---|---|---|---|
| 1 | [End-to-End System](01_End_to_End_System.md) | Anyone — PM, engineer, reviewer | What is it, who is it for, how do you use it, how is it built, why is it novel? Includes a **principal-engineer-level technical review**. |
| 2 | [High-Level Design (HLD)](02_HLD.md) | Engineers, architects | Containers, boundaries, the five critical flows, data model, failure modes, scaling, NFRs. |
| 3 | [Low-Level Design (LLD)](03_LLD.md) | Implementers, reviewers | Module-by-module internals: graph nodes, state, worker/locking, auth, BYOK crypto, SSE, retrieval, frontend. |
| 4 | [Interview Defense](04_Interview_Defense.md) | The author, in a room | The hard questions and honest answers, including the four production bugs found by actually running it. |

## The 60-second version

A user asks a research question. A **LangGraph `StateGraph`** decomposes it into tasks,
runs real web-search and page-read tool calls per task, grades the evidence with a
**fail-closed critic**, synthesizes a **cited** Markdown report, and then **pauses at a
real checkpoint** (`interrupt()`) for a human decision. Approve → finalize. Reject with
feedback → the synthesizer re-runs *from the checkpoint*, never from scratch.

The differentiators are not "we called an LLM in a loop":

1. **The gate is a checkpoint, not a flag.** Approval resumes durable graph state in
   Postgres. A worker can die mid-run and the resume still lands at the gate.
2. **Citations are verifiable.** Every `[n]` resolves to a source with the verbatim
   supporting snippet. A marker that resolves to nothing renders as a visible ⚠, so a
   pipeline bug is surfaced rather than hidden behind confident prose.
3. **The critic fails closed.** Unparseable critic output counts as failure. The common
   failure mode in agent systems — a malformed judge response silently reading as "pass"
   — is designed out.
4. **It is honest about cost and provenance.** Real `usage_metadata` token accounting, a
   per-session budget guard, and per-user BYOK keys encrypted at rest.

## What makes this repo unusual as a portfolio artifact

Most agent demos are a notebook. This is a **deployable product** with a migration-owned
schema, a background worker with distributed locking, cookie auth with refresh-token
rotation and reuse detection, an SSRF guard, per-operation rate limits, an eval harness
with a committed baseline, container images, and CI.

More importantly, the interesting engineering here is **the bugs that only appear when
you actually run it** — a gzip layer silently buffering the entire live-event stream, an
evidence parser dropping a whole task's research into an empty `except`. Those stories
are in [Interview Defense](04_Interview_Defense.md) §3 and they are the most honest
signal in this repository.

## Source-of-truth map

Deep-dive docs explain *why*. These are the specs that define *what*:

| Concern | Spec |
|---|---|
| Product scope, out-of-scope | [../01_Product_Vision.md](../product/01_Product_Vision.md) |
| Architecture | [../02_System_Architecture.md](../architecture/02_System_Architecture.md) |
| Stack choices + rejected options | [../03_Tech_Stack.md](../architecture/03_Tech_Stack.md) |
| Agent/graph design | [../04_Agent_Design.md](../architecture/04_Agent_Design.md) |
| Schema + API contracts | [../05_Data_and_API.md](../architecture/05_Data_and_API.md) |
| Threat model, auth, BYOK | [../06_Security.md](../engineering/06_Security.md) |
| UI/UX rules | [../07_UIUX_Guidelines.md](../product/07_UIUX_Guidelines.md) |
| Test strategy, golden journeys | [../08_Testing_and_Quality.md](../engineering/08_Testing_and_Quality.md) |
| Deploy/ops runbook | [../09_Deployment_and_Operations.md](../engineering/09_Deployment_and_Operations.md) |
| Milestones | [../10_Roadmap.md](../product/10_Roadmap.md) |
