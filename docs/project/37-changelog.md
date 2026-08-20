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

## v2.0.0 — on `main`, not yet tagged

Research becomes a structured record: evidence, claims, sources, conflicts, a human
decision, and an artifact anyone can verify offline.

**The major number moves because the product's unit of output changed.** In V1 a run
produced a report with citations attached to it. In V2 the report is a *rendering* of
records that exist in their own right — and those records, not the prose, are what you
inspect, review, export, and hand to someone who does not trust this application. The V1
API, the V1 SSE stream, and the V1 bundle format are all still served; nothing that worked
against 1.0.2 stops working. See [the V2 research model](../getting-started/24-v2-research-model.md).

**Improved**

- **A run is a record, not a document.** Evidence, sources, claims, claim→evidence links,
  contradictions, revisions, review decisions, and the approved artifact are first-class
  rows you can inspect and export.
- **Claims trace to evidence.** Every claim resolves to the evidence it was matched against
  and the source that evidence came from — and a claim that resolved to nothing says so
  instead of rendering prose that looks supported.
- **Retrieved is not cited, and retrieved is not verified.** A source the report never cites
  keeps no citation number but still appears in Sources. Evidence carries a three-valued
  provenance state where `UNCHECKED` means *nobody checked*, not that it passed.
- **Conflicting sources are a finding, not a footnote** — two attributed quotations side by
  side with the reason they cannot both hold.
- **A run workspace** over that record: plan, evidence, claims, sources, conflicts, review,
  and artifact as views of one run, with live progress that reconnects with `Last-Event-ID`
  and replays what it missed rather than restarting.
- **The review screen shows what you are approving** before you approve it: claims with and
  without evidence, cited versus retrieved-only sources, unresolved conflicts, and an
  unmeasured citation rate reported as unmeasured rather than as `0%`.
- **Approval freezes a verifiable artifact.** The bundle it produces passes the standalone
  verifier that ships in this repository — offline, no network, no model, no account.
- **A second human checkpoint before any search spends money.** The research plan is
  reviewed on its own terms: drop a task and it is never researched; reword one and that is
  what gets searched. Approving a plan never creates an artifact — enforced in the schema,
  the application, the bundle serialization, and the verifier.
- **Reports are versioned.** A rework adds a revision; it never overwrites the one a
  reviewer already read.
- **Follow-up questions can be scoped** to this report, your corpus, the web, or everything,
  and the answer states which grounding produced it.
- **In-app document preview** for PDF, Markdown, text, and HTML from the corpus list.
  Uploaded HTML renders inside a fully sandboxed frame.
- **History filters** by verified-citation rate and by model, so a weak run is findable
  rather than buried.
- **V1 → V2 migration tooling** with three verdicts kept separate rather than collapsed into
  one number: does V2 say what V1 said (fidelity), is the result internally valid
  (validity), and is every migrated fact traceable to something V1 recorded (grounding).
  See the [migration guide](../deployment/38-migration-v1-to-v2.md).
- **Server and desktop route parity is now enforced, not intended.** Follow-up chat and
  bundle export previously 404'd on the desktop build; a parity suite now fails the build
  when a route exists on one host and not the other. **Route parity is not feature parity**
  — see *Desktop support* below for what the desktop build actually runs.
- **Keyless demo mode no longer reaches a real embedding provider.** It was billing real API
  calls on a run the product described as free.

### Desktop support in 2.0.0

| | Research journey | V2 record (evidence, claims, sources, review, artifact) |
|---|---|---|
| **Web application** (server + worker) | V2 | Supported |
| **Desktop application** (Tauri + sidecar) | V1 | Read and inspect only — runs cannot be executed |

The desktop build ships the **V1** research journey for 2.0.0. Its sidecar serves the V2
routes and they answer correctly, but nothing in the desktop UI calls them, and a V2 run
cannot be *executed* there: `v2_execution.execute_run` acquires a Redis lock, opens the
server database engine and checkpoints to Postgres, none of which exist on a host that is
SQLite-and-keychain by design. Asked to dispatch a V2 run, the desktop answers **501 Not
Implemented** and creates nothing, rather than persisting a run no driver would ever
advance.

Making the desktop a V2 host means writing an in-process V2 driver — a second execution
path with its own checkpointer and no distributed lock. That is a milestone, not a patch,
and it is not in this release. Verified by running the packaged sidecar, not inferred from
the configuration file.

**Known**

- **No production database has been migrated.** The tooling is validated against disposable
  copies — including one restored from real production data, where 11 of 11 sessions
  migrated with 0 refusals, 0 failures, and 0 fidelity mismatches — but running it on your
  own data is your decision and your backup.
- Two V1 states are recorded as unmigratable rather than repaired: evidence whose source URL
  was never recorded, and a plan approval for a run with no plan. Neither occurred in the
  restored-production run.
- Some V1 history cannot be recovered at all and is recorded as absent rather than filled
  in: superseded report drafts, whether a plan was proposed or edited, and whether a run was
  cancelled. V1 overwrote the first two and never recorded the third as a state.
- Corpus-mode research works on V2 but has no end-to-end test, because corpus mode requires
  a local embedder and the test environment has none.
- Cancelling a run is advisory. It is recorded durably and no new work is started, but
  research already in flight runs to its next checkpoint.
- Claim verification is not implemented: claims are extracted from the report's prose and
  carry no per-claim judgement. `verification_state` is `UNCHECKED` on every claim V2 writes.
- Claim lineage across revisions is not tracked. Nothing observes that a sentence in
  revision 2 *is* the assertion from revision 1, and matching by text would manufacture a
  relationship the system never saw.
- Project memory does not yet ingest V2 runs.
- The V2 run list returns the most recent runs up to a limit and is not paginated.
- Citation support is still measured at 0.90 on a single self-judged local-model run, and
  that measurement predates this work. It needs re-running before the number is leaned on.

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

Semantic-ish: the patch number moves for fixes, the minor for features, and the major moves
for a break in a documented contract — the API, the SSE event shapes, or the
[bundle format](../reference/15-bundle-format.md), which carries its own `bundle_version`
besides.

**v2.0.0 is the one deliberate exception, and it is worth stating rather than glossing.** It
breaks no documented contract: the V1 API, SSE stream, and bundle format are all still
served, and a client written against 1.0.2 keeps working. The major moved because the
product's unit of output changed — from a report with citations attached to a structured
record that a report is rendered from — and calling that a minor release would have
understated it to exactly the people who read a changelog to decide whether to trust the
thing.
