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

## v2.0.1 — 2026-08-26

Four measurements that were wrong, a feature that was inert, and one product instead of two.

**Fixed**

- **Project memory could not index anything the current pipeline produced.** Memory was
  keyed by a foreign key to the session table, so a research run counted as an approved
  report and could never be indexed: the "not indexed yet" count only climbed, and project
  chat answered from an empty store. Nothing failed and no test was red — the feature was
  simply inert for every account that had only ever used runs, which is every account
  created since 2.0.0. Both kinds of approved report now share one memory, and a citation
  in a chat answer links to whichever surface can open it.
- **Retrieval silently returned nothing.** The relevance ceiling had been tightened from
  "worse than orthogonal" to a smaller unmeasured number, on the reasoning that it would
  filter noise. It filtered the answer: a question asked of the project that owns the report
  retrieved zero results. Restored, with a test that states the rule rather than leaving
  three unrelated tests to imply it.
- **A run whose evidence was never read could still export a bundle.** That refusal was
  attached to the import ledger, so it only covered imported runs; a run executed here whose
  checkpoint could not be decoded produced a bundle that numbered every `[n]` against
  nothing and asserted a quality nobody observed. The fact now lives on the run itself and
  one rule covers every run.
- **A forced extraction pass billed its first attempt twice.** When a model declined to
  submit evidence and the fallback mechanism ran, the budget guard was handed the running
  total rather than the increment — so a spend limit could fire on money that was never
  charged.
- **The desktop app can start research.** It drives a run in-process against its own
  checkpointer, because it has no broker to hand one to. In 2.0.0 the same button answered
  501. Everything downstream is the server's code: the same engine, the same domain tables,
  the same artifact and the same bundle.
- **Approved reports are saved into their project's corpus automatically**, so follow-up
  questions can draw on them without a re-upload.
- **A task that fetched pages but never submitted evidence no longer loses them.** The
  engine asks for the extraction directly, from the text it already holds and nothing else,
  and retries through a differently-shaped request when a model ignores a forced tool call.
  Every quotation is still checked against what the tools actually returned; a quote that
  matches exactly one other fetched page is re-pointed at it and the claimed URL is recorded
  alongside, because a repair a reader cannot see is a silent rewrite.

**Improved**

- **One way to start research.** A second start form existed on the older pipeline, was
  labelled "legacy" in its own banner and was absent from the navigation. It is gone, along
  with the version vocabulary that ran through the codebase, the API path (`/api/v1/v2/runs`
  is now `/api/v1/runs`) and the interface.
- **Research recorded before runs is still readable, chattable and exportable**, listed as
  Sessions on History and on the project overview rather than by a version number.
- **The import tool is removed.** It was a one-shot utility for bringing older research into
  the current tables, its job is done, and a tool that reads a table nothing else consults
  is a maintenance cost that misleads. Its outcome table is dropped by a migration.
- **A rework journey covers the report gate end to end**, asserting that a rejection
  authorizes nothing and that the second draft is a new revision rather than an edit of the
  one that was rejected.

**Known**

- Two research pipelines still exist in the backend. The product has one, and research
  recorded by the earlier one stays readable; consolidating the two is not a patch.
- Follow-up chat scoped to a single report is available on research recorded as a session
  and not on a run. Project chat, which cites every approved report in a project, covers
  both.
- Cancelling a run still does not interrupt work already in flight; it runs to its next
  checkpoint, and the tokens spent there are recorded because they were really spent.
- Claim verification is still not implemented, claim lineage across revisions is still not
  tracked, and contradiction detection is still source-level and unscored.
- Citation support is still measured at 0.90 on a single self-judged local-model run, and
  that measurement predates 2.0.0. It needs re-running before the number is leaned on.
- Corpus-mode research still has no end-to-end test, because it requires a local embedder
  and the test environment has none.

---

## v2.0.0 — 2026-08-25

Research becomes a structured record: evidence, claims, sources, conflicts, a human
decision, and an artifact anyone can verify offline.

**The major number moves because the product's unit of output changed.** Before this a run
produced a report with citations attached to it. Now the report is a *rendering* of records
that exist in their own right — and those records, not the prose, are what you inspect,
review, export, and hand to someone who does not trust this application. The session API,
its SSE stream and its bundle format are all still served; nothing that worked against
1.0.2 stops working. See [the research record](../getting-started/19-research-record.md).

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
- **A one-shot import tool** for research recorded by the earlier pipeline, with three
  verdicts kept separate rather than collapsed into one number: does the imported record say
  what the original said (fidelity), is the result internally valid (validity), and is every
  imported fact traceable to something the original recorded (grounding). *Removed in
  2.0.1 — see below.*
- **Server and desktop route parity is now enforced, not intended.** Follow-up chat and
  bundle export previously 404'd on the desktop build; a parity suite now fails the build
  when a route exists on one host and not the other. **Route parity is not feature parity**
  — see *Desktop support* below for what the desktop build actually runs.
- **Keyless demo mode no longer reaches a real embedding provider.** It was billing real API
  calls on a run the product described as free.
- **Stopping a run now sticks.** Cancellation is durable state rather than an advisory
  event, and every writer that could move a run out of it refuses to. Previously a stopped
  run could reappear minutes later awaiting your approval, and approving it put a report you
  had tried to abandon into project memory. Tokens spent between the stop and the pipeline
  noticing are still recorded, because they were really spent.
- **A run that used scripted models says so.** `LLM_MODE=fake` — which `start.sh` selects for
  `--fake` and silently when no provider key is configured — produced runs recorded as real
  research: the exported bundle named models nothing had called, at a plausible cost, and the
  standalone verifier passed it without its demo banner. What actually ran is what gets
  recorded.

### Desktop support in 2.0.0

| | Research runs | The record (evidence, claims, sources, review, artifact) |
|---|---|---|
| **Web application** (server + worker) | Executed by a Celery worker | Supported |
| **Desktop application** (Tauri + sidecar) | **Not executable** | Read and inspect only |

The desktop build of 2.0.0 could not *execute* a run: `execute_run` acquired a Redis lock,
opened the server database engine and checkpointed to Postgres, none of which exist on a
host that is SQLite-and-keychain by design. Asked to dispatch a run it answered **501 Not
Implemented** and created nothing, rather than persisting a run no driver would advance.
Verified by running the packaged sidecar, not inferred from the configuration file.

*Fixed in 2.0.1: the desktop now drives a run in-process.*

**Known**

- **No production database has been migrated.** The tooling is validated against disposable
  copies — including one restored from real production data, where 11 of 11 sessions
  migrated with 0 refusals, 0 failures, and 0 fidelity mismatches — but running it on your
  own data is your decision and your backup.
- Two states are recorded as unimportable rather than repaired: evidence whose source URL
  was never recorded, and a plan approval for a run with no plan. Neither occurred in the
  restored-production run.
- Some history cannot be recovered at all and is recorded as absent rather than filled in:
  superseded report drafts, whether a plan was proposed or edited, and whether a run was
  cancelled. The earlier pipeline overwrote the first two and never recorded the third as a
  state.
- Corpus-mode research works but has no end-to-end test, because corpus mode requires a
  local embedder and the test environment has none.
- Cancelling a run does not interrupt work already in flight; it runs to its next
  checkpoint. The decision is durable and authoritative — a cancelled run stays cancelled
  and cannot reappear awaiting approval — and the tokens spent after the stop are recorded.
- Claim verification is not implemented: claims are extracted from the report's prose and
  carry no per-claim judgement. `verification_state` is `UNCHECKED` on every claim written.
- Claim lineage across revisions is not tracked. Nothing observes that a sentence in
  revision 2 *is* the assertion from revision 1, and matching by text would manufacture a
  relationship the system never saw.
- Project memory does not yet ingest research runs. *Fixed in 2.0.1.*
- The run list returns the most recent runs up to a limit and is not paginated.
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
breaks no documented contract: the session API, its SSE stream and its bundle format are all still
served, and a client written against 1.0.2 keeps working. The major moved because the
product's unit of output changed — from a report with citations attached to a structured
record that a report is rendered from — and calling that a minor release would have
understated it to exactly the people who read a changelog to decide whether to trust the
thing.
