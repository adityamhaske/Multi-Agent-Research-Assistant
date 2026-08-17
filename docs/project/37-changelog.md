# Changelog

Released versions, what improved, and what shipped with a known gap. Versions match the git
tags.

The [releases page](https://adityamhaske.github.io/Multi-Agent-Research-Assistant/releases/)
renders the same data, and every tag has a
[GitHub release](https://github.com/adityamhaske/Multi-Agent-Research-Assistant/releases)
with the desktop installers and a `SHA256SUMS` file attached.

**Known gaps are listed deliberately.** The people most likely to read a changelog are
deciding whether to trust the thing, and a changelog with no bad news is marketing.

---

## Unreleased

The research design gate, scoped follow-ups, and in-app document preview.

**Improved**

- A second human checkpoint: the run now pauses after the planner so you can edit the
  subtopics and pick the report outline before any search spends money. Drop a task and it is
  never researched; reword one and that is what gets searched.
- Follow-up questions can be scoped to this report, your corpus, the web, or everything —
  and the answer states which grounding produced it.
- PDF, Markdown, text, and HTML documents preview in place from the corpus list instead of
  downloading and switching applications. Uploaded HTML renders inside a fully sandboxed
  frame.
- A project workspace joining recent runs, corpus, and model configuration in one view.
- History filters by verified-citation rate and by model, so a weak run is findable rather
  than buried.
- Follow-up chat works on the desktop build. It previously rendered a chat box that returned
  404 — the sidecar had no chat routes at all.
- Keyless demo mode no longer reaches a real embedding provider. It was billing real API
  calls on a run the product described as free.

**Known**

- Citation support is still measured at 0.90 on a single local-model run, and that
  measurement predates this work. It needs re-running before the number is leaned on.
- The desktop bundle for this work has not been tagged or published yet.

---

## v1.0.2 — 2026-08-15

Budgets became opt-in, and citation snippets became verifiable.

**Improved**

- Every run limit is now opt-in, with `0` meaning unlimited. A hardcoded token ceiling used
  to kill long runs with no way to raise it.
- A citation snippet must be text that was actually fetched, so a quote cannot be
  reconstructed from a model's memory of a page.
- The evaluation baseline was corrected to stop scoring a competing system against
  placeholder text.
- CI waits for the worker to be ready instead of sleeping, and a flaky end-to-end run now
  fails the gate rather than passing quietly on a retry.

**Known**

- Cost caps remain inert on OpenRouter and custom providers, because the pricing catalog
  cannot price them. Cap spend at the provider.

---

## v1.0.1 — 2026-08-15

Desktop distribution fixes: the bundle actually contained the app.

**Improved**

- The desktop bundle ships the engine it needs. The previous build produced a 5 MB app that
  passed CI, uploaded cleanly, and died on first launch.
- Release assets are checksummed under the names they are actually served with, so
  verification succeeds instead of silently checking nothing.

**Known**

- Builds are unsigned. macOS and Windows both warn on first launch; the download page
  explains the unblock steps before you download rather than leaving the OS to explain
  after.

---

## v1.0.0 — 2026-08-14

First release: the pipeline, the human gate, and verifiable exports.

**Improved**

- Planner, executor, critic, and synthesizer running as a graph, with a durable human
  approval checkpoint before anything is finalised.
- Every citation resolves to a source and a verbatim snippet; one that cannot be verified
  renders a warning chip instead of rendering clean.
- Markdown, PDF, and hash-verifiable bundle exports, with a standalone offline verifier.
- Self-hosting with Docker, bring-your-own-key, and local models through Ollama.

**Known**

- Project memory is Postgres-only, so the desktop build has no cross-report memory.

---

## Versioning

Semantic-ish: the patch number moves for fixes, the minor for features, and the major would
move for a breaking change to a documented contract — the API, the SSE event shapes, or the
[bundle format](../reference/15-bundle-format.md), which carries its own
`bundle_version` besides.
