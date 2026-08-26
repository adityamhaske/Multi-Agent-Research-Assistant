# Multi-Agent Research Assistant — Open Source Maintainer Constitution

This document defines how the repository should be built, maintained, documented, released, and evolved as a serious open-source project.

Add this file's path to the repository-level `AGENTS.md` and instruct coding agents to read it before making substantial changes.

---

# 1. Mission

The project exists to make AI-assisted research:

- verifiable
- reviewable
- reproducible
- self-hostable
- open
- user-owned

The project is not optimized to maximize the number of features.

It is optimized to maximize:

> **trustworthy research capability per unit of complexity.**

---

# 2. Open-Source First Principles

## Rule 001 — Public repository means public product

Anything treated as a core product capability must be understandable from the public repository and website.

Do not build important functionality that can only be understood through private context.

## Rule 002 — Self-hosting is first-class

A user should be able to run the project independently.

Never introduce a feature that silently requires the maintainer's private infrastructure.

## Rule 003 — BYOK remains first-class

Users can provide their own provider credentials.

Provider keys must remain:

- scoped
- protected
- never logged
- never returned unnecessarily
- never exposed across users

## Rule 004 — No silent telemetry

Do not introduce telemetry or analytics that sends research/user data elsewhere without explicit user knowledge and consent.

Default should remain privacy-preserving.

## Rule 005 — Open-source users are not beta customers

Do not make public users depend on undocumented manual steps.

If a capability is not ready for public use, label it as experimental/planned.

---

# 3. Code Is the Source of Truth

Documentation, tickets, plans, and AI-generated proposals are not evidence of implementation.

When documentation and implementation disagree:

1. inspect the code
2. inspect tests
3. inspect deployment/release artifacts
4. determine actual behavior
5. update docs
6. add a regression test where appropriate

Never document an intention as an implemented feature.

---

# 4. Product Scope Discipline

Before implementing a new feature, answer:

1. What user problem does it solve?
2. Who has the problem?
3. Why is it core to verifiable research?
4. What is the smallest useful version?
5. What maintenance burden does it introduce?
6. Can it be removed later?
7. Does an existing feature already solve the problem?

If the answer to the user/problem questions is weak, do not build the feature.

---

# 5. The Product's Core Invariants

These invariants are more important than individual technologies.

## Evidence

Evidence must originate from actual source content.

## Citations

Citations must resolve to evidence.

## Approval

Unapproved research must not be treated as approved research.

## Memory

Only approved knowledge becomes authoritative project memory.

## Evaluation

Unmeasured is not zero.

## Security

Prompt instructions are never treated as the sole security boundary.

## Ownership

One user's credentials/data must never become accessible to another user.

---

# 6. Architecture Rules

## Rule — Domain before framework

Core domain concepts should not depend unnecessarily on:

- FastAPI
- Next.js
- Celery
- Redis
- LangGraph
- database-specific implementation details

Keep business invariants testable independently where practical.

## Rule — Providers at the edges

LLM/search/embedding providers are adapters.

Core product logic should depend on stable contracts rather than vendor-specific clients.

## Rule — Avoid speculative abstractions

Do not create a generic abstraction just because there might someday be multiple implementations.

Preferred sequence:

```text
Concrete implementation
→ second real implementation
→ identify shared contract
→ extract interface
```

## Rule — Prefer shared implementation over parallel copies

The project has multiple deployment modes.

If two implementations maintain the same business behavior, prefer extracting the shared behavior rather than copying it.

If duplication is unavoidable, add tests that prove the contracts remain aligned.

## Rule — Complexity needs a reason

A new:

- service
- queue
- datastore
- abstraction
- dependency
- execution mode

requires an explicit reason.

---

# 7. UI Rules

The UI is a research workspace, not a generic chatbot.

Primary concepts should be:

- Projects
- Research
- Evidence
- Claims
- Review
- Artifacts

Do not make internal agent details the primary UX.

Avoid:

- fake "AI thinking" animations
- excessive chat-bubble patterns
- agent-count marketing
- confusing progress theatrics

The interface should communicate:

- status
- provenance
- uncertainty
- evidence
- human control

---

# 8. Research Workflow Rules

Research should conceptually follow:

```text
Question
→ Plan
→ Gather
→ Verify
→ Review
→ Approve
→ Artifact
```

Do not add hidden autonomous actions that can materially affect users or external systems without a clearly defined boundary.

---

# 9. Evidence Rules

When a model returns evidence:

1. treat it as untrusted
2. validate against source/tool output
3. normalize conservatively
4. preserve provenance
5. expose failures

Never trust:

```text
model-provided URL
model-provided title
model-provided quote
```

without appropriate validation.

---

# 10. Citation Rules

A citation that cannot be resolved should never silently render as verified.

Use explicit states such as:

- verified
- unresolved
- unverified
- contested

Do not hide uncertainty to make the UI look better.

---

# 11. Claim Rules

Claims are first-class research objects.

A claim should be able to reference:

- supporting evidence
- contradicting evidence
- source(s)
- review state

Do not flatten important provenance into a single markdown string if structured data is required by the product.

---

# 12. Human Review Rules

Human review is a product capability, not an implementation checkbox.

Users must be able to understand:

- what the system concluded
- why it concluded it
- what evidence supports it
- where conflicts exist
- what remains uncertain
- what they are approving

Do not make "Approve" a blind green button without context.

---

# 13. Testing Rules

A test should prove a useful property.

Be suspicious of tests that mock away the mechanism under test.

Especially for absence claims:

- no network
- no spend
- no write
- no secret leakage
- no cross-tenant access

verify that the real mechanism is actually exercised.

## Prefer invariant tests

Example:

Bad:

```text
response == expected JSON
```

Better:

```text
every citation resolves
```

Better:

```text
every evidence snippet appears in retrieved source content
```

Better:

```text
unapproved report is absent from project memory
```

---

# 14. Evaluation Rules

Evaluation artifacts are evidence.

Therefore:

- write once
- never overwrite historical results
- use unique run IDs
- record metric versions
- distinguish `unmeasured` from `0`
- disclose evaluator model/provider
- disclose dataset version
- disclose limitations

Do not publish a benchmark number until the artifact supports it.

---

# 15. Security Rules

Security requirements must be enforced in code/configuration/tests.

Do not rely on:

- prompt wording
- UI hints
- documentation claims
- developer discipline alone

Important areas:

- authentication
- authorization
- BYOK isolation
- SSRF
- prompt injection
- output rendering
- CSRF
- rate limits
- secrets
- dependency security
- source isolation

Security-sensitive changes require tests.

---

# 16. Dependency Rules

Do not add a dependency merely because it is convenient.

Before adding one:

1. verify no existing dependency solves the problem
2. identify the exact import/use
3. evaluate maintenance/security cost
4. verify license compatibility
5. update dependency documentation if relevant

No "résumé dependencies."

---

# 17. Documentation Rules

Every behavior-changing PR should update relevant documentation.

Documentation should:

- describe current behavior
- provide verified commands
- clearly mark planned functionality
- avoid internal project-management details
- avoid unnecessary duplication
- link to canonical pages

Do not write documentation that is more ambitious than the code.

---

# 18. Website Rules

The public website is a product surface.

It must remain synchronized with:

- latest release
- downloads
- docs
- tutorials
- roadmap
- changelog
- GitHub repository

Avoid hard-coded release versions in many files.

Prefer one release metadata source of truth.

When a release changes user-facing behavior, update:

- website
- README
- docs
- changelog
- release notes

in the same change where practical.

---

# 19. Tutorial Rules

Tutorials must be task-oriented.

Every tutorial needs:

- prerequisites
- setup
- exact commands
- expected result
- common failure modes
- cleanup if relevant

Do not publish tutorials for functionality that has not been verified.

---

# 20. Contributor Experience

A contributor should be able to answer quickly:

- where is the relevant code?
- how do I run it?
- what tests do I run?
- what contract must I preserve?
- how do I add a provider?
- how do I update docs?
- how do I open a PR?

Create contribution paths for different skill levels.

---

# 21. Good First Issues

Maintain issues that can be completed without understanding the whole system.

Examples:

- documentation
- accessibility
- frontend copy
- isolated test
- provider example
- troubleshooting improvement
- example research workflow

Avoid labeling architecture work "good first issue."

---

# 22. RFC Rules

Architecture-changing changes should use an RFC.

RFC must contain:

```text
Problem
Context
Goals
Non-goals
Proposed design
Alternatives
Trade-offs
Migration
Testing
Rollback
```

Do not merge major architectural changes based on a one-line implementation request.

---

# 23. PR Rules

PR descriptions should contain:

### Problem

What is wrong?

### Why

Why does it matter?

### Change

What changed?

### Trade-offs

What alternatives were considered?

### Testing

What was verified?

### Limitations

What remains unverified?

### Documentation

Which docs changed?

### Scope

What intentionally did not change?

Prefer small PRs over giant mixed changes.

---

# 24. Commit Rules

Use clear conventional commits where practical:

```text
feat:
fix:
docs:
test:
refactor:
chore:
perf:
security:
```

The commit message should explain the change, not the entire history of the project.

---

# 25. Release Rules

A release must have:

- version
- source commit
- release notes
- artifacts
- checksums where appropriate
- docs consistency
- known limitations

Do not call a release production-ready if a documented critical workflow is unverified.

---

# 26. AI Coding Agent Rules

AI coding agents are implementation tools.

They are not automatically architects.

The maintainer/developer must define:

- invariant
- acceptance criteria
- scope
- trade-offs

Before allowing a coding agent to make substantial changes.

Agents should:

1. inspect the repository
2. inspect related tests
3. inspect applicable `AGENTS.md`
4. identify contracts
5. propose implementation
6. add/update tests
7. implement
8. run verification
9. report uncertainty

Never accept an AI-generated claim such as:

> "verified"

without actual verification evidence.

---

# 27. AI Agent Anti-Patterns

Avoid prompts such as:

```text
"Build this entire feature."
"Refactor everything."
"Make the architecture better."
"Rewrite the project."
```

Prefer:

```text
"Implement invariant X.
Preserve contract Y.
Change only modules A/B/C.
Add regression tests for failure Z.
Run commands Q/R.
Report anything unverified."
```

---

# 28. Historical Knowledge

Historical engineering lessons are valuable.

However:

- core rules should become tests when possible
- architecture decisions should become ADRs
- user-facing docs should focus on current behavior
- internal audit narratives should not dominate public docs

Use history to improve the system, not to preserve complexity.

---

# 29. ADR Rules

For significant architectural decisions, create an ADR with:

```text
ID
Title
Status
Context
Decision
Alternatives
Consequences
```

Examples:

- why LangGraph
- why human approval
- why evidence provenance
- why PostgreSQL is source of truth
- why project memory only accepts approved artifacts
- why provider interfaces are shaped the way they are

---

# 30. Product Decision Rules

When proposing a feature:

Do not ask only:

> "Can we build it?"

Ask:

> "Should we build it?"

Then evaluate:

```text
User value
Differentiation
Complexity
Security
Maintenance
Reversibility
Open-source contribution value
```

A feature that is technically impressive but does not strengthen the product thesis should usually wait.

---

# 31. "Delete Before Add" Rule

Before adding a new subsystem, ask:

> Can the existing system accomplish this by removing or simplifying something?

When possible:

- delete duplicate code
- remove unused dependencies
- remove unnecessary abstractions
- simplify state
- remove unused deployment modes

Prefer simplification over accumulation.

---

# 32. Stable Core / Experimental Edge

Keep a small stable core.

Experimental capabilities should be:

- explicitly labeled
- isolated
- reversible
- tested
- documented as experimental

Do not let experiments redefine stable architecture too early.

---

# 33. Community Health

The maintainer should optimize for:

- contributor response time
- clear issue triage
- welcoming discussion
- transparent roadmap
- recognition of contributors
- sustainable release cadence

Do not optimize only for GitHub stars.

---

# 34. License and Third-Party Components

Before adding external code/content:

- check license
- document attribution where required
- avoid incompatible terms
- track third-party assets

Do not copy proprietary content into fixtures or documentation without permission.

---

# 35. Privacy

Treat research content as potentially sensitive.

Never log:

- provider API keys
- passwords
- session tokens
- full private documents
- unnecessary user research content

Use redaction and minimal logging.

Document network behavior.

---

# 36. Performance

Do not prematurely optimize.

Measure before optimizing.

For research workflows, prioritize:

1. correctness
2. reliability
3. evidence integrity
4. useful latency
5. cost

Do not trade evidence correctness for cosmetic latency wins.

---

# 37. Compatibility

Prefer stable user-facing behavior.

Breaking changes should include:

- reason
- migration path
- documentation
- release notes

Avoid breaking formats such as research artifacts without versioning.

---

# 38. Public Readiness Acceptance Test

Before declaring the product mature enough for broad public adoption, a stranger should be
able to:

1. find the website
2. understand the product
3. download or self-host it
4. configure a BYOK provider
5. run research
6. inspect evidence
7. review a claim
8. approve/reject
9. generate an artifact
10. understand the artifact
11. find documentation
12. find contribution instructions
13. open a useful issue/PR without private context

---

# 39. Final Maintainer Principle

Do not build a repository that only its original author can operate.

Build a project that can survive:

- another maintainer
- another contributor
- another deployment
- another model provider
- another year
- another product direction

The ultimate goal is:

> **The project should become easier to understand as it grows, not harder.**
