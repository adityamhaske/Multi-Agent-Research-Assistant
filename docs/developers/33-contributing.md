# Contributing

The full policy lives in
**[CONTRIBUTING.md](https://github.com/adityamhaske/Multi-Agent-Research-Assistant/blob/main/CONTRIBUTING.md)**
at the repository root, alongside the
[Code of Conduct](https://github.com/adityamhaske/Multi-Agent-Research-Assistant/blob/main/CODE_OF_CONDUCT.md).
This page is the developer-facing summary and the pointers to everything you will need.

## Where to start

| You want to | Read |
|---|---|
| Get the stack running locally | [Development guide](32-development.md) |
| Understand the pipeline before changing it | [Agent architecture](../architecture/04-agent-architecture.md) |
| Understand the deployment shape | [System architecture](../architecture/02-system-architecture.md) |
| Know what will be checked in review | [Engineering guidelines](11-engineering-guidelines.md) |
| Run the tests CI runs | [Testing and evaluation](08-testing-and-evaluation.md) |

## Reporting a bug

Open a [GitHub issue](https://github.com/adityamhaske/Multi-Agent-Research-Assistant/issues)
with steps to reproduce, expected versus actual behaviour, and your environment. Check the
existing issues first.

**Do not open a public issue for a security vulnerability.** Use
[GitHub Security Advisories](https://github.com/adityamhaske/Multi-Agent-Research-Assistant/security/advisories/new)
instead; see
[SECURITY.md](https://github.com/adityamhaske/Multi-Agent-Research-Assistant/blob/main/SECURITY.md).

## Suggesting a feature

Open an issue describing the use case and why it matters. The
[roadmap](../project/10-roadmap.md) is where accepted ideas land, and the
[Overview](../getting-started/01-overview.md#what-is-deliberately-out-of-scope) says what is
deliberately out of scope — worth reading before proposing something large.

## Submitting a change

1. Branch from `main`.
2. Keep the diff small and focused — one logical change per pull request.
3. Add or update tests. A feature without its tests is not done, and a bug fix lands with a
   regression test.
4. Update the documentation in the **same** pull request if behaviour, configuration, or the
   API changed.
5. Run what CI runs:

```bash
cd backend && ruff check app/ research_engine/ tests/ evals/ \
  && ruff format --check app/ research_engine/ tests/ evals/ \
  && python -m pytest
```

```bash
cd frontend && npm run lint && npm run typecheck && npm test && npm run build
```

6. Open the pull request against `main`, describing **what** and **why**, and linking the
   issue with `Fixes #123`.

Commits follow the conventional format (`feat:`, `fix:`, `docs:`, `test:`, `refactor:`,
`chore:`) in imperative mood.

## Things reviewers will look for

Beyond the [review checklist](11-engineering-guidelines.md#review-checklist), three recurring
ones:

- **The second home.** Most shared behaviour in this codebase exists in two places — the
  server host and the desktop host, or the harness and the benchmark. Changing one without
  the other is the most common defect here.
- **Fail-open handlers.** A caught exception that returns a plausible default is rejected;
  surface the error.
- **Unmeasured rendered as zero.** If your change can produce a number, make sure it can also
  produce "not measured", and that the two do not collapse.

## What is helpful

Good first contributions, in rough order of usefulness:

- **Retrieval quality.** Report quality tracks retrieval quality more than model quality, and
  the keyless fallback is the weak link.
- **Evaluation runs.** Committed results are how quality becomes diffable. New ones are
  always welcome — add a file, never modify one.
- **Provider and model catalog entries**, with the provider's published prices.
- **Accessibility fixes**, which are held to a merge criterion rather than a wishlist.
- **Documentation corrections.** If something on this site is wrong, that is a real bug — the
  documentation is meant to describe what is built.

By contributing you agree your contributions are licensed under the MIT License.
