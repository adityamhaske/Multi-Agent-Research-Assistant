# Overview

**A self-hostable, bring-your-own-key research assistant with two human checkpoints and
citations you can verify.**

You ask a research question. A pipeline of specialised agents plans the work, searches,
gathers evidence with sources, grades that evidence, and drafts a cited Markdown report.
It pauses twice for you — once on the plan, once on the draft — and the finished report
exports to a file a third party can check offline with no AI and no network.

## The problem it solves

Every general-purpose assistant will write you a research report. The difficulty is not
getting one; it is knowing which sentences in it are true.

A citation in most tools is a link. It tells you the model saw a page, not that the page
says what the sentence claims. When independent testing looks at this closely, misattribution
is common enough that a reader has to re-check the work by hand — at which point the report
saved them nothing.

This project treats a citation as a data structure instead of a formatting convention:

- every `[n]` resolves to a source **and** the verbatim snippet that supports that claim;
- a marker that cannot be resolved renders a visible ⚠ *unverified* chip rather than
  rendering clean;
- the `.bundle.json` export carries the claims, the snippets, their content hashes, and
  the approval trail, and ships with a standalone verifier that needs no network.

The system is built to show its own failures rather than to look finished.

## Who it is for

| You are | What you get |
|---|---|
| **A researcher or analyst** | Cited output you can put in a literature review without re-checking every line, plus a corpus of your own documents alongside the open web. |
| **A privacy-conscious professional** | It runs on your machine or your server, on your API key or a local model. Nothing is proxied through a service we operate, because there isn't one. |
| **A team with oversight requirements** | A mandatory review gate with a recorded approve/rework trail, and an export that proves which draft was approved. |
| **An engineer** | A working reference for checkpointed human-in-the-loop agents: real LangGraph `interrupt()`, durable resume, fail-closed grading, and tests. |

## What makes it different

Three properties, and it is the combination that is unusual rather than any one of them.

**1. The human gate is a durable checkpoint, not a status flag.**
Both pauses are LangGraph `interrupt()` calls. The graph checkpoints to the database and
the worker process exits. Approving hours later *resumes* the same state — it does not
re-run the research you already paid for. A regression test asserts the planner is invoked
exactly once across submit and approve.

**2. You approve the plan before it spends anything.**
The first gate sits between the planner and the first search. Edit the subtopics, pick the
report structure, drop a task you did not ask for — and the dropped task is never
researched. That is the difference between "the agent picked six queries" and "these are my
six subtopics, in my structure".

**3. Verification is measured, and unmeasured is not zero.**
`citation_resolution_rate` is recorded per session and shown on every row of history —
including a *Not measured* band, because "made no citable claims" and "every marker is
broken" are opposite findings. The same rule runs through the evaluation harness: it
returns `None` where it could not measure, and refuses to print a number it did not take.

## What it does today

| Capability | State |
|---|---|
| Multi-agent pipeline (planner → executor ⇄ critic → synthesizer → finalizer) | Built |
| Two human gates: research design, then draft approval | Built |
| Web retrieval with a fallback chain (Tavily → Brave → DuckDuckGo) and caching | Built |
| Per-claim citations with verbatim snippets and a ⚠ chip for unresolved markers | Built |
| Contradiction detection between sources, surfaced not auto-resolved | Built |
| Follow-up chat over a finished report, scoped to report / corpus / web / everything | Built |
| Projects, and chat over the approved research in a project | Built (server only) |
| Uploaded document corpus, and an airgapped corpus-only mode with no network calls | Built |
| Exports: Markdown, PDF, and a hash-verifiable `.bundle.json` with an offline verifier | Built |
| Bring-your-own-key for Google, Anthropic, OpenAI, OpenRouter, and any OpenAI-compatible endpoint | Built |
| Local models through Ollama, including fully local embeddings | Built |
| Desktop app (macOS, Windows, Linux) with a bundled engine and SQLite | Built, unsigned |
| Keyless demo mode with scripted models and fixture sources | Built |

Details: [Running research](../user-guide/25-running-research.md) ·
[Citations](../user-guide/27-citations.md) ·
[Projects and memory](../user-guide/28-projects-and-memory.md)

## What is deliberately out of scope

Saying no is what keeps the parts above honest.

- **Billing, plans, or payments.** Bring your own key; the operator pays for what they use.
- **Teams, organisations, roles, shared workspaces.** Single-tenant by design.
- **Social login / OAuth providers.** Email and password, so a self-host needs no external
  identity provider.
- **Being a general chat assistant.** Chat here interrogates verified research. It is not a
  research tool that happens to chat.
- **Kubernetes manifests, autoscaling, sharding.** Not until a real scaling need exists;
  the [operations page](../deployment/31-operations.md) states the order those needs would
  actually arrive in.
- **Mobile apps.**

## Known limits, stated plainly

- **Retrieval quality is the ceiling.** With no Tavily or Brave key the chain falls back to
  DuckDuckGo, which is rate-limited and slow. Report quality tracks retrieval quality more
  than it tracks model quality.
- **Evidence de-duplication is URL-exact.** The same article at two URLs becomes two
  sources.
- **The critic grades per-task evidence, not the finished report.** Whether the
  synthesizer's `[n]` usage is faithful to the snippet it points at is measured offline by
  the [evaluation harness](../developers/08-testing-and-evaluation.md), not by a runtime
  gate.
- **Cost caps cannot fire on OpenRouter or custom endpoints**, whose prices are not in the
  catalog. Cap spend at the provider. See [Configuration](21-configuration.md).
- **Small local models fail the structured-evidence step.** 14B is the working floor for
  research; anything runs chat. See [Local LLM setup](22-local-llm.md).
- **Desktop builds are unsigned**, so macOS and Windows both warn on first launch.

## Where to go next

| You want to | Read |
|---|---|
| Run it | [Quick start](20-quick-start.md) |
| Configure a model or provider | [Configuration](21-configuration.md) |
| Run it with no API key or cost | [Local LLM setup](22-local-llm.md) |
| Understand the pipeline | [Agent architecture](../architecture/04-agent-architecture.md) |
| Understand the deployment | [System architecture](../architecture/02-system-architecture.md) |
| Deploy it publicly | [Production deployment](../deployment/30-production.md) |
| Contribute | [Development guide](../developers/32-development.md) |
