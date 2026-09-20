# Changelog

Released versions, what improved, and what shipped with a known gap. Versions match the git
tags.

The [releases page](/releases)
renders the same data, with desktop installers and checksums available on the
[download page](/download).

**Known gaps are listed deliberately.** The people most likely to read a changelog are
deciding whether to trust the thing, and a changelog with no bad news is marketing.

---

## v2.1.0 — 2026-09-19

Two claims the product makes about itself turned out not to hold, and the things that
would have caught them did not exist.

**Fixed**

- **Airgapped corpus mode did not hold on the server.** A run requested as corpus-only,
  and recorded as corpus-only, could still search the open web and read pages from it.
  The flag reached the database and decided which corpus store to install, but never
  reached `RunConfig` — and `retrievers.search` and `tools.read_webpage`, which decide
  whether anything asks the web at all, read it from there and cannot see a database. So
  the guarantee was recorded rather than enforced, on the host that advertises it loudest.
  The desktop had been fixed earlier; the server had not. The egress test stayed green
  throughout because it constructed `RunConfig` by hand, stubbing the exact hop that was
  broken; it now drives the real host builders and asserts every retrieved source is a
  `corpus://` location.
- **Both chat surfaces read the oldest twenty turns, not the newest.** `ORDER BY
  created_at ASC LIMIT 20` returns the first twenty messages ever written. Every caller
  commits the user's new message before reading that window and assembles its prompt only
  from it, so past turn twenty the model was answering a question it had never been shown.
  Three homes, not two — the sidecar restated the same query — so it became one function,
  `chat_history.recent_turns`, which selects newest-first and restores chronological order.
  Both halves are tested independently: fixing only the limit would leave the transcript
  reversed, which reads as a different conversation.
- **A migration could not be reversed.** No downgrade had ever been run against this
  schema, and the first one attempted failed on every database: `0008_chat_threads`
  dropped a constraint under a name the naming convention had already rendered
  differently, so every downgrade past that revision died. CI now runs a populated
  round-trip in both directions, with two exception registries that each name a reason.
- **Run identifiers were logged as session identifiers.** `session_id` means a
  `sessions.id`; binding a run's id to that field made a run's own logs unfindable by its
  id. There are two binders now, and the distinction is enforced rather than remembered.
- **Scripted runs could pass by producing nothing.** Fake mode selected its behaviour by
  searching the system prompt for eight hand-typed fragments of its own prose, with an
  `else` returning an empty object. Nothing tied those fragments to the prompts they
  quoted, so rewording any prompt would have routed every scripted test to that branch and
  left the suite green on a pipeline that produced nothing. Behaviour is selected by agent
  role now, and an unrecognised scenario raises instead of answering emptily.

**Improved**

- **Retrieval quality is measured.** Four documents call retrieval the ceiling on report
  quality and a repository-wide search for `recall@` or `ndcg` returned nothing at all.
  There is now a frozen sixteen-document dataset, recall@k / precision@k / nDCG / duplicate
  metrics against the real retriever, and a write-once baseline: **recall@1 0.792 ·
  precision@1 0.917 · nDCG@10 0.944 · dedup_rate 0.000**.
- **A corpus has an identity, and its documents have versions.** Identity used to be the
  file path, so a bundle citing `corpus://<id>` could say which bytes but never which
  corpus or what state it was in. Documents carry `doc_key`, `version` and `superseded_at`,
  a re-upload supersedes rather than duplicates, and a run records the corpus snapshot it
  read.
- **Operational metrics.** A server-only metrics endpoint exposes seven metric families in
  Prometheus text on a private registry, with every label drawn from a closed table.
  Terminal outcomes are observed where runs actually terminate — completion at the approval
  route, failure and cancellation at the persistence adapter — and always after the commit.
- **A typed view of a report.** `ReportDocument` is derived from the report Markdown and
  never the other way round, recording whether the parse was exact or lossy so a lossy one
  can never become authoritative. Markdown stays the source of truth: `report_hash` is
  still `sha256(report_markdown)`, so every existing approval chain and bundle pins exactly
  what it pinned before.
- **Readiness tests are hermetic.** Whether the settings page reports you as ready to
  research was asserted from a live probe of whatever machine ran the suite, so one commit
  passed or failed depending on whether Ollama happened to be running. Both hosts now stub
  the transport rather than the probe, and the reachable, unreachable and embedding-only
  cases are each pinned — including that a reachable server offering only embedding models
  is *not* readiness, since an embedding model cannot fill an agent role.

**Measured and rejected**

- **Hybrid retrieval did not beat dense-only.** It was implemented and measured against the
  baseline above. The diagnosis is that the residual gap is equal-weight fusion of two
  retrievers of unequal reliability, not the quality of the candidates. It was rejected and
  reported rather than tuned until the number improved. Dense-only remains production
  behaviour.

**Known**

- Citation support is still measured at 0.90 on a single self-judged local-model run, and
  that measurement predates 2.0.0. Nothing here re-ran it.
- The share of evidence from primary sources is not measured, and deliberately not
  estimated: `source_url` is model-authored, so an invented but plausible link would
  classify as primary with full confidence. A fakeable metric on a verifiability product is
  worse than no metric.
- The scholarly evaluation set is drafted but unverified. Six of twelve questions survived
  review, and their rubrics were written without a human opening a cited paper. A rubric
  naming the wrong study would penalize a *correct* answer, so the set grades nothing until
  a domain reader checks it.
- Desktop builds are unsigned and do not auto-update.
- Two research pipelines still exist in the backend. The product has one, and research
  recorded by the earlier one stays readable; consolidating the two is not a patch.
- Follow-up chat scoped to a single report is available on research recorded as a session
  and not on a run. Project chat, which cites every approved report in a project, covers
  both.
- Cancelling a run still does not interrupt work already in flight; it runs to its next
  checkpoint, and the tokens spent there are recorded because they were really spent.
- Claim verification is still not implemented, claim lineage across revisions is still not
  tracked, and contradiction detection is still source-level and unscored.

---

## v2.0.2 — 2026-08-31

The desktop app stopped reimplementing the server, and four bugs that only existed because
it had.

**Fixed**

- **Every desktop settings-page load 404'd in the background.** `useReadiness()` is fetched
  unconditionally on every host — the settings layout only branches on what it does with
  the answer — and the sidecar had no route for it at all. A shipped control that never
  worked. It answers from this host's own keys now.
- **The "Local" model preset offered models the machine did not have.** The server has
  built that preset from what Ollama actually reports since 2.0.0; the desktop kept the
  static name, which 404s on the first planner call if it was never pulled.
- **The routing panel's "deployment default" mirrored your own saved preference.** Both
  numbers were computed from the same call, so saving a per-role choice made them
  identical — which defeats the reason the comparison exists.
- **A project with runs and no chat sessions reported zero sessions.** The desktop's
  project list only counted the older kind of research.
- **Stopping a run recorded no reason in its event history**, though the reason was visible
  elsewhere on the same screen.

**Improved**

- **The desktop and the server run the same code** for every project, corpus and
  research-session operation that does not depend on where a secret is stored — proved by
  the two resolving to one function object, not by two implementations that currently agree.

**Known**

- Two research pipelines still exist in the backend.
- Follow-up chat scoped to a single report is available on a session and not on a run.
- Cancelling a run does not interrupt work already in flight.
- Claim verification is not implemented, claim lineage is not tracked, and contradiction
  detection is source-level and unscored.
- Corpus-mode research has no end-to-end test, because it requires a local embedder and the
  test environment has none.
- Citation support is measured at 0.90 on a single self-judged local-model run predating
  2.0.0.

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
- **No approved report could ever be indexed, because the chunker discarded every
  section.** Markdown does not require a blank line after a heading and this product's own
  synthesizer does not emit one, so `## Summary` and the prose beneath it arrived as one
  block that the splitter treated as *a heading* — keeping the first line and dropping the
  paragraph. Every section took that branch, and a 1,600-character report chunked to
  nothing. Nothing raised: ingestion logged "report produced no chunks" and moved on. This
  is what made project memory unreachable in practice even where it was wired up.
- **The memory card counted the corpus as memory.** `indexed_reports` and `chunk_count`
  were `max(memory, corpus)`, so a project with uploaded documents reported reports as
  indexed that retrieval could not reach. Two stores, two cards, two numbers.
- **The verified-citation rate was never measured on a research run.** The engine measures
  it on its own `completed` outcome and a run never reaches one — approving at the report
  gate finalizes the run in the domain rather than resuming the graph — so the number was
  NULL on every run ever produced, while History offered a filter on it and every run card
  displayed it. It is now measured at approval, from the exact bytes the reviewer approved.
- **The standalone verifier crashed on Windows.** Every check passed and then printing the
  result raised `UnicodeEncodeError`, because a Windows console is cp1252 and `✓` is not in
  cp1252 — a traceback where the word PASS should have been. This is the one program here a
  stranger runs on their own machine to check an artifact they were handed, so it now falls
  back to ASCII markers on a console that cannot render the glyphs. Found by running the
  packaged desktop app on a Windows runner, which nothing had done before.
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

**Faster**

- **Depth now governs the run instead of describing it.** It reached the planner as a word
  in a prompt and nothing else, so "Fast — fewer sources, lowest cost" bought the same
  eight turns and five pages per task as "Comprehensive". A turn is one model call, and a
  model call on a hosted router was measured at two to four and a half *minutes*, so turns
  are the entire wall-clock of a run. Fast is now 3 turns and 3 pages per task, balanced 5
  and 5, comprehensive 8 and 8 — a fast run makes **under half** the model calls it used
  to, and the run form states the numbers rather than promising thoroughness.
- **A turn's page reads happen at once.** They ran one after another, so a model asking
  for three pages paid three fetch timeouts end to end. Fetches are capped at ten seconds
  and now overlap; the executor is also told to request its pages in a single turn, which
  is the change that removes whole model round-trips rather than shaving seconds off one.

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
