# Multi-Agent Research Assistant V2
## Verifiable, Self-Hosted Research Workspace — Product + Engineering Master Plan

**Status:** V2 planning baseline  
**Repository:** `adityamhaske/Multi-Agent-Research-Assistant`  
**Primary deployment model:** Open source, self-hosted, BYOK  
**Public website:** Must remain a first-class product surface  
**Primary objective:** Evolve the current project into a focused, trustworthy research workspace rather than another generic AI research/chat application.

---

# 0. Executive Direction

V2 is **not a greenfield rewrite**.

The existing repository is the accumulated implementation knowledge from V1. It contains valuable production/debugging experience around:

- agent orchestration
- human-in-the-loop checkpoints
- evidence extraction
- citation verification
- BYOK
- security
- self-hosting
- local inference
- evaluation
- project memory
- deployment
- desktop/local execution

V2 should reuse that knowledge and the parts of the implementation that remain correct.

However, V2 should also be willing to **rewrite, simplify, move, consolidate, or delete** parts of the implementation when the current architecture creates unnecessary complexity.

## V2 principle

> **Reuse the knowledge, not the accidental complexity.**

The project should evolve from:

> "Multi-Agent Research Assistant"

toward:

> **"A verifiable research workspace for AI-assisted research you can inspect, review, reproduce, and self-host."**

The project remains:

- open source
- self-hosted
- BYOK
- extensible
- privacy-conscious
- transparent about limitations
- useful without requiring the user to trust a hosted vendor

---

# 1. Product Thesis

## 1.1 Core problem

Existing AI products are excellent at producing answers.

The harder problem is producing research that a person can:

- inspect
- verify
- challenge
- correct
- approve
- reproduce
- hand off
- revisit later

V2 should optimize for **research integrity**, not merely answer fluency.

## 1.2 Product promise

The product should make this workflow first-class:

```text
Research Question
       ↓
Research Plan
       ↓
Evidence Gathering
       ↓
Claim Construction
       ↓
Claim ↔ Evidence Verification
       ↓
Human Review
       ↓
Approved Research Artifact
       ↓
Report / Memory / Export / Reuse
```

The system should make the provenance chain visible.

## 1.3 Product differentiation

Do not position V2 as:

- "an open-source Perplexity"
- "another multi-agent chatbot"
- "a ChatGPT clone"
- "a better search engine"
- "a generic RAG application"

The product should be differentiated around:

### Verifiability

A claim should be connected to evidence.

### Human review

The user can review and approve before research becomes authoritative.

### Reproducibility

A research run produces a structured artifact rather than only prose.

### Ownership

Users self-host the system and bring their own provider keys.

### Extensibility

Providers and storage/search/model capabilities are replaceable.

### Historical research

Projects can evolve over time rather than existing only as one-off chats.

---

# 2. Product Positioning

Preferred positioning:

> **Research you can defend.**

Suggested description:

> An open-source, self-hosted research workspace that turns AI-assisted research into verifiable, reviewable, reproducible artifacts.

Alternative language:

- Verifiable AI Research
- Auditable Research Workspace
- Research with Provenance
- Research Artifacts for AI-Assisted Investigation

Do not over-index on "multi-agent" in user-facing product copy. Agents are implementation details.

---

# 3. What V2 Is and Is Not

## 3.1 Core product

V2 is:

- a research workspace
- a research execution engine
- a provenance/evidence system
- a human review system
- a research artifact generator
- a self-hostable application
- a BYOK application
- an open-source reference implementation

## 3.2 Not the goal

Do not expand into:

- generic chat platform
- social network
- broad AI assistant
- voice assistant
- mobile app unless justified later
- dozens of agent types
- arbitrary autonomous browser automation
- enterprise billing platform
- feature parity with every competitor
- "agent framework" for all possible workflows

---

# 4. Core Product Invariants

These are V2's most important technical/product rules.

## INV-001 — Evidence provenance

Every evidence item used for a claim must originate from content actually returned by a retrieval/fetch operation or a user-provided trusted source.

The model must not be trusted to invent a citation snippet.

## INV-002 — Citation resolution

Every citation in a finalized report must resolve to a known evidence/source record.

If it cannot resolve, the system must surface the failure.

## INV-003 — Approval boundary

Only explicitly approved research may become an approved/final artifact.

## INV-004 — Memory boundary

Only approved artifacts enter durable project memory.

## INV-005 — Fail closed

Invalid validation output must never silently become success.

Examples:

- malformed critic response → failure/retry
- missing evidence → unresolved state
- unmeasured evaluation → `unmeasured`, not zero
- missing provenance → unverified

## INV-006 — Reproducibility metadata

A research artifact records the information necessary to understand how the result was produced.

At minimum:

- question
- research configuration
- sources
- evidence
- claims
- provenance
- timestamps
- model/provider metadata where appropriate
- approval information
- final report

## INV-007 — User ownership

Provider credentials belong to the user/deployment and must never be exposed to other users.

## INV-008 — Self-hosting remains first-class

The application must remain runnable by users on their own infrastructure.

## INV-009 — BYOK remains first-class

Users can bring their own provider keys.

The system must not require the project maintainer to subsidize user inference.

## INV-010 — Security boundaries are architectural

Security must not depend on prompt instructions alone.

---

# 5. V2 Domain Model

The product should be organized around **Research Projects and Research Runs**, not chat threads.

Conceptual model:

```text
Research Project
│
├── Research Runs
│   │
│   ├── Question
│   ├── Research Plan
│   ├── Sources
│   ├── Evidence
│   ├── Claims
│   ├── Contradictions
│   ├── Review
│   └── Artifact
│
├── Approved Research
│
├── Project Memory
│
└── History
```

## Core entities

### ResearchProject

A persistent workspace around a topic or decision.

### ResearchRun

One execution of research.

### ResearchPlan

The structured set of tasks/topics the system intends to investigate.

### Source

A web document or trusted user-provided source.

### Evidence

A concrete piece of source-derived information used by the research process.

### Claim

An assertion appearing in research.

### ClaimEvidenceLink

Relationship connecting a claim to one or more evidence items.

### Contradiction

A detected conflict between evidence/claims.

### Review

Human feedback, edits, approval, rejection, and review state.

### ResearchArtifact

The durable output of an approved research run.

### ProjectMemory

Approved knowledge that can be retrieved in future project research/chat.

---

# 6. Claim Graph

A key V2 capability should be an explicit claim/evidence model.

Conceptually:

```text
Claim
│
├── Supporting Evidence
│   ├── Source A
│   └── Source B
│
├── Contradicting Evidence
│   └── Source C
│
├── Confidence / Verification State
│
└── Human Review State
```

Do not reduce citations to simple `[1]` strings.

Those markers can remain in the report UI, but the underlying data model should represent the relationships explicitly.

## Suggested claim states

```text
UNVERIFIED
SUPPORTED
CONTESTED
INSUFFICIENT_EVIDENCE
HUMAN_REVIEWED
APPROVED
REJECTED
```

Use only states actually needed by the implementation. Avoid premature state explosion.

---

# 7. Evidence Integrity Pipeline

The evidence pipeline should be explicit:

```text
Search / User Source
        ↓
Retrieved Content
        ↓
Stored / Normalized Source
        ↓
Evidence Extraction
        ↓
Evidence Provenance Validation
        ↓
Claim Construction
        ↓
Claim ↔ Evidence Linking
        ↓
Citation Rendering
```

## Critical rule

The model may propose evidence metadata, but the system must be capable of determining:

> "Did this text actually come from the source?"

Evidence validation should compare model-produced snippets against tool-returned text.

Normalization may allow:

- whitespace normalization
- case normalization where appropriate
- punctuation normalization where appropriate

It must not turn fabricated content into verified evidence.

---

# 8. Research Workflow V2

## Phase A — Create Project

User creates:

```text
Project title
Description
Optional source scope
```

## Phase B — Ask Question

User provides:

- research question
- depth
- optional research constraints
- optional private sources
- optional output type

## Phase C — Research Planning

Planner creates a transparent plan.

User may optionally edit:

- topics
- questions
- priorities
- exclusions

The goal is not to expose agent internals. The goal is to expose research scope and user control.

## Phase D — Evidence Gathering

System gathers sources and evidence.

UI should show:

- sources found
- evidence collected
- tasks completed
- unresolved tasks
- failures
- contradictions

## Phase E — Claim Construction

System produces structured claims and evidence mappings.

## Phase F — Verification

System checks:

- citation resolution
- evidence provenance
- claim/evidence consistency
- contradictory evidence
- missing support

## Phase G — Human Review

User can:

- approve
- reject
- request rework
- inspect evidence
- edit claims/report
- flag unsupported claims
- request more evidence for a topic

## Phase H — Finalization

Approved research becomes a ResearchArtifact.

## Phase I — Reuse

Artifact can be:

- exported
- stored in project history
- indexed into project memory
- revisited
- compared against later research

---

# 9. Research Artifact

This should become one of V2's central concepts.

A ResearchArtifact is a portable record of a research result.

It should contain, as appropriate:

```text
Manifest
Question
Research configuration
Research plan
Sources
Evidence
Claims
Claim/evidence mappings
Contradictions
Review history
Approval information
Report
Model/provider metadata
Timing/cost metadata
Integrity hashes
```

The artifact should be inspectable independently of the running application where feasible.

## Long-term direction

Potential future project:

`research-artifact-spec`

Do not create a second repository immediately.

First stabilize the artifact contract inside this repository.

---

# 10. Research Replay and Versioning

V2 should support a research history model.

Example:

```text
Research v1
    ↓
Evidence changes
    ↓
Research v2
    ↓
Conclusion changes
```

A future user should be able to understand:

- what changed
- when it changed
- which sources changed
- which claims changed
- why the conclusion changed

Do not claim deterministic replay of external web research.

Instead distinguish:

### Reproducible

Same artifact/provenance can be inspected again.

### Re-runnable

The process can be executed again.

### Reconstructable

The historical research artifact can be understood from stored evidence.

External web content changing over time must be treated explicitly.

---

# 11. Contradiction Handling

Contradictions should become first-class research objects.

Example:

```text
Source A → supports Claim X
Source B → conflicts with Claim X
```

The UI should communicate:

- conflict detected
- sources involved
- possible reason for conflict
- whether methodology differs
- whether time period differs
- whether the conflict is unresolved

Do not force the model to choose one side silently.

The system should preserve disagreement.

---

# 12. Uncertainty

Do not make false precision.

Potential presentation:

```text
Claim
"Technology X improves latency."

Verification
SUPPORTED

Confidence
MEDIUM

Evidence
3 sources

Counter-evidence
1 source

Evidence gap
No production benchmark
```

Confidence must have an explicit methodology.

If confidence cannot be defensibly computed, do not invent a numeric confidence score.

---

# 13. "What Would Change the Conclusion?"

A strong V2 report should eventually expose:

```text
Current conclusion
Key assumptions
Evidence gaps
Counter-evidence
What would change this conclusion?
```

This is especially useful for:

- engineering decisions
- technology selection
- market analysis
- policy research
- security investigation
- scientific research

Only implement when backed by a sound evaluation strategy.

---

# 14. Project Memory V2

Project memory remains valuable, but it is not the main product.

Memory should be:

```text
Approved artifacts
        ↓
Chunking/indexing
        ↓
Project-scoped retrieval
        ↓
Future research/chat
```

Do not allow arbitrary model-generated chat history to become authoritative knowledge by default.

The approval gate should continue to act as a trust boundary.

---

# 15. Private Sources

A major long-term differentiator should be combining:

```text
Public evidence
+
Private/internal evidence
```

Potential sources:

- user-uploaded documents
- local PDFs
- GitHub repositories
- local source trees
- approved internal URLs
- local corpora

The architecture must preserve source trust boundaries.

A private source should never accidentally become accessible to another user/project.

---

# 16. Open-Source / Self-Hosted Requirements

These are non-negotiable.

## Source availability

The full core application must remain source-available under the selected OSI-compatible license.

## Self-hosting

Users must be able to run the application independently.

## BYOK

Users should be able to configure provider keys themselves.

## No mandatory maintainer infrastructure

The project must not require a central paid API owned by the maintainer for core functionality.

## No telemetry by default

Do not introduce analytics/telemetry that silently sends user research data elsewhere.

If telemetry is ever added:

- opt-in
- documented
- minimal
- easy to disable

## Transparent network behavior

Documentation must clearly state what leaves the user's machine.

---

# 17. Supported Deployment Modes

Keep the deployment strategy intentionally small.

## Primary

### Self-hosted server

```text
Browser
  ↓
Frontend
  ↓
API
  ↓
Worker
  ↓
Postgres / Redis
```

## Secondary

### Local development

Developer runs services locally.

## Experimental / optional

### Desktop

Keep only if it remains maintainable and clearly valuable.

Do not let desktop architecture force duplicated application logic.

Prefer shared engine/core interfaces wherever possible.

---

# 18. Provider Architecture

Provider abstractions should be explicit and minimal.

Potential categories:

```text
LLM Provider
Embedding Provider
Search Provider
Source Provider
Artifact Storage Provider
```

Each interface should define a small stable contract.

Avoid building generic plugin frameworks before there are multiple real implementations.

Rule:

> Abstract when a second implementation exists or is immediately required.

---

# 19. UI/UX V2 Rewrite

This is a major part of V2.

The UI should not look like a generic AI chatbot.

## 19.1 Primary navigation

Recommended:

```text
Projects
Research
Sources
Artifacts
Settings
Docs
```

Avoid making Chat the dominant navigation item.

## 19.2 Project workspace

Project overview should show:

```text
Project
├── Current research
├── Recent findings
├── Open questions
├── Approved artifacts
├── Conflicts
└── Research history
```

## 19.3 Research run screen

Suggested layout:

```text
┌─────────────────────────────────────────────┐
│ Research question                           │
│ Status / progress / controls                │
├───────────────────────┬─────────────────────┤
│ Research Plan         │ Evidence            │
│                       │                     │
│ ✓ Topic A             │ Source 1             │
│ ✓ Topic B             │ Source 2             │
│ ● Topic C             │ Source 3             │
│ ○ Topic D             │                     │
├───────────────────────┴─────────────────────┤
│ Claims / Findings                           │
│                                             │
│ Claim 1   ✓ supported                       │
│ Claim 2   ⚠ contested                       │
│ Claim 3   ? insufficient evidence           │
└─────────────────────────────────────────────┘
```

## 19.4 Review screen

Review should be the strongest UI.

For each claim:

```text
Claim
    ↓
Supporting evidence
    ↓
Source
    ↓
Counter-evidence
    ↓
Human action
```

Actions:

- Approve
- Reject
- Request evidence
- Edit
- Comment

## 19.5 Report screen

The report should be readable like a professional research document.

Citations should open an evidence panel rather than interrupt reading.

## 19.6 Artifact screen

Expose:

- report
- claims
- evidence
- sources
- review
- provenance
- export
- integrity information

## 19.7 Empty states

Every empty state should explain:

- what this section means
- why it is empty
- how to get data into it

---

# 20. Visual Design Direction

The visual language should communicate:

- serious
- research-oriented
- technical
- trustworthy
- calm
- transparent

Avoid:

- flashy "agent" animations
- excessive gradients
- chatbot-like bubble UI
- gamification
- fake "AI thinking" theatrics

The product should look closer to:

```text
research workspace
+
technical notebook
+
audit console
```

than to:

```text
consumer chatbot
```

---

# 21. Website Must Remain a First-Class Surface

The public website is not optional marketing decoration.

It must provide:

```text
Home
Downloads
Latest Release
Documentation
Tutorials
Architecture
Roadmap
Changelog
Community
Contributing
Security
```

## Website goals

A visitor should be able to:

1. understand the product in 30 seconds
2. launch a demo if available
3. download the latest release
4. find self-hosting instructions
5. read docs
6. follow a tutorial
7. inspect the roadmap
8. open GitHub
9. contribute

---

# 22. Website Structure

Recommended:

```text
/
├── Home
├── Download
├── Docs
├── Tutorials
├── Changelog
├── Roadmap
├── Community
└── GitHub
```

## Home

Should emphasize:

> Research you can defend.

Show a visual workflow:

```text
Question
→ Research
→ Evidence
→ Review
→ Verified Artifact
```

## Download

Show:

- latest version
- release date
- supported platforms
- checksums
- release notes
- source code
- installation instructions

Never hard-code a release version in multiple unrelated places.

Create a single source of truth for latest release metadata.

## Docs

Use the improved information architecture defined separately in the documentation plan.

## Tutorials

Create task-driven tutorials.

Examples:

### Tutorial 1

Run your first research project.

### Tutorial 2

Use Ollama locally.

### Tutorial 3

Connect your own API key.

### Tutorial 4

Self-host with Docker.

### Tutorial 5

Research with private documents.

### Tutorial 6

Inspect a research artifact.

### Tutorial 7

Build a custom provider.

Only publish tutorials that correspond to working functionality.

---

# 23. Public Website "Trust Page"

Add a page explaining what the system does and does not guarantee.

For example:

```text
What we verify
- citation resolution
- evidence provenance
- approval history
- artifact integrity

What we do not guarantee
- truth of external sources
- correctness of every generated claim
- timelessness of web research
- perfect model behavior
```

This fits the project's philosophy extremely well.

---

# 24. Community Design

The project is open source only if strangers can participate.

Add:

## CONTRIBUTING.md

Explain:

- development setup
- project structure
- testing
- docs
- PR process
- commit conventions
- architecture changes
- release process

## GOOD_FIRST_ISSUE.md or labels

Create issues for:

- docs
- UX
- testing
- provider integrations
- retrieval
- deployment
- examples
- tutorials

## RFC process

Architecture-changing proposals should use an RFC template.

## Discussions

Use GitHub Discussions for:

- ideas
- questions
- integrations
- research
- use cases

Issues should be used primarily for actionable bugs/features.

---

# 25. Contribution Ladder

Create contribution levels.

### 5-minute contribution

- typo
- docs correction
- example improvement

### 30-minute contribution

- test
- UI fix
- error handling
- tutorial improvement

### 2-hour contribution

- provider adapter
- retrieval improvement
- export feature

### 1-day contribution

- meaningful feature

### Architecture contribution

- new storage/provider subsystem
- research artifact evolution
- major workflow changes

Make the first three levels particularly easy.

---

# 26. Maintainer Principles

V2 maintainership should follow:

## 26.1 Small PRs

Prefer narrow PRs.

## 26.2 Evidence before opinion

For product-impacting changes, explain the reason.

## 26.3 Reproducible bug reports

Require:

- environment
- version/commit
- steps
- expected
- actual
- logs where safe

## 26.4 No silent scope creep

A PR should not introduce unrelated cleanup unless justified.

## 26.5 Code ownership through interfaces

Keep stable contracts where possible.

## 26.6 Documentation follows product reality

Docs must change with behavior.

---

# 27. Documentation V2

The documentation should be reorganized into:

```text
Getting Started
User Guide
Architecture
Deployment
Developers
Reference
Research
Project
```

Detailed page-by-page documentation cleanup is in:

`Multi-Agent-Research-Assistant-Docs-Plan.md`

Use that plan as the documentation-specific implementation reference.

---

# 28. Evaluation Strategy V2

The evaluation framework should be focused.

## Core metrics

### Citation Support

Does evidence actually support the claim?

### Citation Resolution

Does every citation resolve?

### Evidence Provenance

Did the evidence actually originate from a retrieved/user source?

### Completion Rate

Did the research run reach a valid reviewable state?

### Cost

What did the run cost?

### Latency

How long did it take?

### Human Correction Rate

How frequently did users change/reject AI output?

This can become one of the most valuable product-quality metrics because it measures where the AI still needs human intervention.

---

# 29. Evaluation Rules

Never:

- fabricate benchmark results
- convert unavailable measurements into zero
- claim a model ran when it did not
- overwrite historical evidence
- compare incompatible metric versions without disclosure

Evaluation artifacts are write-once.

Every evaluation result should have a unique identity.

---

# 30. Open-Source Release Discipline

Every release should have:

```text
Version
Release notes
Source commit
Artifact checksums
Container image tags
Desktop artifacts if supported
Documentation updates
Known limitations
```

The website should update automatically from one release source of truth.

---

# 31. Repository Architecture Direction

Prefer the following conceptual layering:

```text
Core Domain
│
├── Research
├── Evidence
├── Claims
├── Review
└── Artifacts

Application Layer
│
├── Research orchestration
├── Retrieval
├── Model routing
└── Project workflows

Infrastructure
│
├── PostgreSQL
├── Redis
├── Provider adapters
├── HTTP
└── Containers

Presentation
│
├── Web
├── Desktop (optional)
└── CLI (optional)
```

The domain should not depend directly on web frameworks.

Provider adapters should stay at the edges.

---

# 32. Architecture Simplification Rule

For every subsystem ask:

1. Can this be removed?
2. Can this be shared?
3. Can this be made deterministic?
4. Can this be made testable?
5. Can this be made provider-independent?
6. Does it need to exist now?

Do not keep duplicated server/desktop implementations if one shared abstraction can safely serve both.

Do not create a generic framework for hypothetical future plugins.

---

# 33. V2 Development Phases

## Phase 0 — Product/architecture audit

Do not build features first.

Inspect:

- current architecture
- actual code
- current tests
- actual workflows
- UI
- docs
- release system
- deployment
- desktop
- evals

Produce a V1 → V2 migration map.

## Phase 1 — Domain model

Implement/stabilize:

- Project
- Research Run
- Source
- Evidence
- Claim
- Claim/Evidence links
- Review
- Artifact

Keep migrations safe and reversible.

## Phase 2 — Evidence integrity

Make provenance first-class.

## Phase 3 — Review workflow

Build the best review experience.

## Phase 4 — Research artifact

Make artifacts first-class and exportable.

## Phase 5 — UI rewrite

Rebuild the frontend around:

- projects
- research runs
- claims
- evidence
- review
- artifacts

## Phase 6 — Website

Rebuild public website information architecture and release/docs integration.

## Phase 7 — Community infrastructure

Improve:

- contributing
- RFCs
- issue templates
- labels
- tutorials
- contributor onboarding

## Phase 8 — Differentiators

Only after the core workflow works:

- contradictions
- research versioning
- research replay/reconstruction
- private sources
- "what changed?"
- decision-aware research

---

# 34. V2 Explicit Non-Goals During Initial Development

Do not add until the core workflow has been validated:

- mobile applications
- voice
- social features
- billing
- huge provider lists
- dozens of agent types
- generic agent marketplace
- autonomous external side effects
- complex enterprise SSO
- Kubernetes
- microservice decomposition
- premature plugin marketplace

---

# 35. User Validation Requirements

Before calling the new UX/product direction successful, test with real humans.

At minimum:

- 5 technical users
- 5 research/analysis users where possible

Observe:

- can they start a research run?
- do they understand the plan?
- do they inspect evidence?
- do they understand uncertainty?
- do they trust the approval workflow?
- do they export/use the artifact?
- do they return to the project?

Do not rely only on internal judgment.

---

# 36. V2 Success Criteria

V2 is successful when:

### Product

- A user understands the value without understanding agents.
- A first research run can be completed with minimal friction.
- The research workspace feels different from a chatbot.
- Human review is genuinely useful.
- Evidence provenance is visible.
- Research artifacts are useful independently of the chat UI.

### Engineering

- Core domain is explicit.
- Evidence provenance is enforced.
- Claims have structured evidence relationships.
- Major provider boundaries are stable.
- Server and local paths share as much core logic as practical.
- Tests verify invariants rather than only happy paths.
- Evaluation claims are trustworthy.

### OSS

- New contributors can get started quickly.
- Good-first issues exist.
- Documentation is organized.
- Website is current.
- Releases are easy to find.
- Self-hosting works.
- BYOK works.
- No telemetry is enabled by default.

---

# 37. V2 Definition of Done

Do not mark V2 complete simply because code exists.

For each major capability:

```text
Design
→ Implementation
→ Tests
→ Documentation
→ UX verification
→ Self-host verification
→ Release verification
```

A feature is incomplete when any of these are missing.

---

# 38. Final V2 Principle

The project should become **smaller conceptually even as it becomes more capable technically**.

The user should see:

```text
Research
Evidence
Review
Artifacts
```

The user should NOT need to think about:

```text
Celery
Redis
LangGraph
agents
provider adapters
checkpointers
ContextVars
```

Those are implementation mechanisms.

V2 succeeds when the complexity exists underneath the product without becoming the product.

---

# 39. Long-Term Vision

The long-term vision is not:

> "Build a better AI chatbot."

It is:

> **Make AI-assisted research inspectable, auditable, reproducible, and ownable.**

Potential long-term ecosystem:

```text
                    Open Research Ecosystem
                             │
               ┌─────────────┴─────────────┐
               ↓                           ↓
        Research Workspace          Research Artifact Spec
               │                           │
               ↓                           ↓
        Evidence / Claims            Validators / Tools
               │                           │
               └─────────────┬─────────────┘
                             ↓
                     External Integrations
```

Do not build all of this now.

Build the smallest product that proves the thesis.

