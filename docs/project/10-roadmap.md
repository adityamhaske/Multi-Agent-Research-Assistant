# Roadmap

What exists, what is being worked on, and what is deliberately not planned. Items are here
because they are useful to someone using or contributing to the project — not as a schedule.

Anything marked **Planned** is not built. If a page describes a feature without that marker,
it exists.

## Current

Shipped and in use:

- **The pipeline** — planner, executor ⇄ critic, contradiction detection, synthesizer,
  finalizer, as a compiled graph with durable checkpointing.
- **Two human gates** — a design gate before any spend, and a draft gate before finalisation,
  both durable and both resumable from a checkpoint.
- **Verifiable citations** — per-claim provenance with verbatim snippets, a visible ⚠ chip for
  unresolved markers, and a recorded resolution rate that distinguishes *not measured* from
  zero.
- **Research bundles** — a hash-verifiable export with a standalone offline verifier.
- **Projects, corpus, and project memory** — only human-approved research enters memory;
  isolation is a SQL predicate.
- **Airgapped corpus mode** — research over your own documents with zero network calls.
- **Bring your own key** — Google, Anthropic, OpenAI, OpenRouter, and any OpenAI-compatible
  endpoint, encrypted at rest and isolated per run.
- **Local models** through Ollama, including local embeddings.
- **Self-hosting** with Docker Compose, and a documented $0/month single-host deployment.
- **Desktop app** for macOS, Windows, and Linux, with a bundled engine and SQLite.

## In progress

- **A published citation-fidelity benchmark.** The
  [methodology](../research/16-citation-fidelity-benchmark.md) is specified and the runner
  exists; no comparative run has been published. The blocker is an independent judge and a
  reproducible baseline configuration, not the harness.
- **A real-model evaluation run that clears the 0.95 support threshold.** The most recent run
  is 0.90 and self-judged, which is stated wherever the number appears.

## Planned

Accepted, not yet built.

| | What it is | Why it matters |
|---|---|---|
| **Code signing** | Signed and notarised macOS and Windows builds | Removes the first-launch warning, which is the biggest install friction today |
| **Auto-update** | In-place desktop updates | Currently you download the new installer. The open question is whether Gatekeeper re-blocks an unsigned app after replacement |
| **Prometheus metrics** | A `/metrics` endpoint and a dashboard | Logs and the run trace are what exist today |
| **Cross-project chat** | A thread readable across several projects | Explicit opt-in per thread, visible scope, audited on change, still a SQL predicate |
| **Shareable read-only report links** | Hand someone a report without an export | |
| **Grouped citation chips** | Make `[3, 11, 18]` hoverable | Only single markers are interactive today |
| **More export formats** | DOCX, HTML | |
| **Scheduled research with diffs** | Re-run a question and report what changed | The "research as a monitored pipeline" case |

## Future

Ideas that fit the product but are not committed:

- Better evidence de-duplication — the same article at two URLs is currently two sources.
- A runtime check that the synthesizer's citation use is faithful to the snippet, rather than
  measuring it only offline.
- Retrieval quality work. Report quality tracks retrieval quality more than model quality,
  and the keyless fallback is the weak link.
- Notion and Obsidian integrations.

## Not planned

Saying no is what keeps the rest coherent. These are declined rather than deferred:

- **Payments, plans, or billing.** Bring your own key.
- **Teams, organisations, roles, shared workspaces.** Single-tenant by design.
- **Social login / OAuth providers.** Email and password, so a self-host needs no external
  identity provider.
- **Being a general chat assistant.** Chat here interrogates verified research.
- **Kubernetes manifests, autoscaling, sharding.** See the
  [scaling path](../architecture/02-system-architecture.md#scaling-path) for the order those
  needs would actually arrive in.
- **Mobile apps.**

## Suggesting something

Open an issue describing the use case and why it matters. Read
[what is out of scope](../getting-started/01-overview.md#what-is-deliberately-out-of-scope)
first — a proposal that crosses one of those lines needs to argue against the line, not
around it.
