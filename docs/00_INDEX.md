# Documentation map

> This file is the repository-facing map of `docs/`. It is **not published to the
> documentation site** — the site generates its own index at `/docs`, and a second table of
> contents beside it would be duplicate navigation rather than help. It exists for people
> browsing the tree on GitHub.

`docs/` is the build contract. Code that contradicts it is wrong; documentation that
contradicts shipped code must be fixed **in the same pull request** that changed the
behaviour. Nothing here is aspirational: every statement describes what is built, or is
explicitly marked as planned.

Engineering notes, milestone plans, and release checklists are **not** documentation and live
in [`../internal/`](../internal/README.md). Nothing under `docs/` should link to them.

`docs/governance/` and `docs/plans/` are repository governance rather than product
documentation — they describe how the project is run, not how the product works. Contributors
and coding agents are pointed at them by `AGENTS.md`; the whole of each directory is withheld
from the site by `UNPUBLISHED_DIRS` in `frontend/lib/docs.ts`.

## Layout

```
docs/
├── getting-started/   what it is, how to run it, how to configure it
├── user-guide/        using the product
├── architecture/      how it is built, and why the boundaries fall where they do
├── deployment/        Docker, production, operations
├── developers/        working on the code
├── reference/         exact contracts: API, SSE, bundle format, configuration
├── research/          measurement methodology
├── project/           roadmap and changelog
└── screenshots/       UI reference images used by the README
```

## Getting started

| Document | Purpose |
|---|---|
| [Overview](getting-started/01-overview.md) | What this is, who it is for, what makes it different, and what is out of scope |
| [Quick start](getting-started/20-quick-start.md) | Clone to first cited report |
| [Configuration](getting-started/21-configuration.md) | The settings you actually reach for |
| [Local LLM setup](getting-started/22-local-llm.md) | Running on Ollama, and which models work |
| [Desktop app](getting-started/23-desktop-app.md) | Install, first run, and what differs from the server |
| [V2 research model](getting-started/24-v2-research-model.md) | What a run records, what approval means, and how to verify an artifact yourself |
| [Troubleshooting](getting-started/24-troubleshooting.md) | The failures people actually hit |

## User guide

| Document | Purpose |
|---|---|
| [Running research](user-guide/25-running-research.md) | Submitting, execution, live progress, limits, failure states |
| [Review and approval](user-guide/26-review-and-approval.md) | Both human gates, and what becomes final |
| [Citations and verification](user-guide/27-citations.md) | What is checked, by what, and what is not |
| [Projects and memory](user-guide/28-projects-and-memory.md) | Projects, the corpus, approved-only memory, isolation |
| [Exports](user-guide/29-exports.md) | Markdown, PDF, and the verifiable bundle |

## Architecture

| Document | Purpose |
|---|---|
| [System architecture](architecture/02-system-architecture.md) | Topology, request lifecycle, technology choices, failure modes, scaling |
| [Agent architecture](architecture/04-agent-architecture.md) | The graph, state, node contracts, tools, budgets, routing |
| [Data model](architecture/05-data-model.md) | Every table, and the migration policy |
| [Local and self-hosted](architecture/13-local-and-self-hosted.md) | The engine boundary, ports, desktop, and the three privacy tiers |
| [Security](architecture/06-security.md) | Threat model through to a production hardening checklist |

## Deployment

| Document | Purpose |
|---|---|
| [Deploy with Docker](deployment/09-docker.md) | Images, Compose, startup ordering, migrations, health |
| [Production deployment](deployment/30-production.md) | TLS, hardening, backups, upgrades, releases |
| [Operations](deployment/31-operations.md) | Observability, runbook, cost control, housekeeping |

## Developers

| Document | Purpose |
|---|---|
| [Development guide](developers/32-development.md) | Setup, layout, the checks CI runs, where things bite |
| [Testing and evaluation](developers/08-testing-and-evaluation.md) | The pyramid, the golden journeys, the evaluation harness |
| [Engineering guidelines](developers/11-engineering-guidelines.md) | The rules, and the review checklist |
| [Frontend guidelines](developers/07-frontend-guidelines.md) | Theming, components, accessibility, build targets |
| [Contributing](developers/33-contributing.md) | How to propose and land a change |

## Reference

| Document | Purpose |
|---|---|
| [API reference](reference/34-api.md) | Every endpoint, with request, response, and errors |
| [SSE protocol](reference/35-sse.md) | Both streams: connection, replay, events, reconnection |
| [Research bundle format](reference/15-bundle-format.md) | The `.bundle.json` schema, hashing rules, and verifier |
| [Configuration reference](reference/36-configuration.md) | Every environment variable and its exact default |

## Research

| Document | Purpose |
|---|---|
| [Citation-fidelity benchmark](research/16-citation-fidelity-benchmark.md) | Methodology, and what has actually been measured |

## Project

| Document | Purpose |
|---|---|
| [Roadmap](project/10-roadmap.md) | Current, in progress, planned, and explicitly not planned |
| [Changelog](project/37-changelog.md) | What changed in each release, including known gaps |

## Adding a page

The site walks this tree at build time. A file's numeric prefix is a stable document
identity — source comments cite documents by number — while reading order comes from
`NAV_ORDER` in `frontend/lib/docs.ts`, keyed by the published slug (the prefix is stripped
from URLs). A page missing from that list still renders; it just sorts last in its section.

Adding a **directory** is a different matter: every one must be classified in
`frontend/lib/docs.ts` as published (`CATEGORY_ORDER`) or withheld (`UNPUBLISHED_DIRS`).
An unclassified directory fails the build rather than publishing by default, because the
site generates a route for every Markdown file it walks.
