/**
 * Release history for the public site.
 *
 * Hand-maintained data rather than a build-time call to the GitHub releases API, for two
 * reasons. The Pages build would gain a network dependency that can rate-limit or fail,
 * and a site that cannot build because a third party is slow is a worse trade than a list
 * someone updates when they cut a tag. And the interesting column — *what improved for
 * you* — is not in the API: release notes generated from commit subjects read as changelog
 * noise, and the honest version of "what changed" is written by whoever knows why.
 *
 * **Rules for adding an entry.** Same honesty rules as `comparison.ts`. `known` is not
 * optional decoration: a release that shipped with a known gap says so here, because the
 * people most likely to read this page are deciding whether to trust the thing, and a
 * changelog with no bad news is marketing.
 *
 * Keep `version` matching the git tag exactly (`v` prefix included) — the download page
 * and the README badge both point at assets named from it.
 */

export interface Release {
  version: string;
  /** ISO date the tag was cut. */
  date: string;
  /** One line: what this release is *for*. */
  headline: string;
  /** What improved since the previous release, in user-visible terms. */
  improved: string[];
  /** Known gaps shipped with this release. Empty only when there genuinely are none. */
  known: string[];
  /** True for work merged to main but not yet tagged. */
  unreleased?: boolean;
}

export const RELEASES: Release[] = [
  {
    version: "v2.0.1",
    date: "2026-08-26",
    headline:
      "Four measurements that were wrong, a feature that was inert, and one product instead of two.",
    improved: [
      "Project memory now indexes every approved report, whichever pipeline produced it. It was keyed to the older one, so a research run counted as approved and could never be indexed — the backlog only climbed and project chat answered from an empty store. Nothing failed and no test was red; the feature was simply inert for every account created since 2.0.0.",
      "Retrieval stopped returning nothing. The relevance ceiling had been tightened to an unmeasured number on the reasoning that it would filter noise; it filtered the answer, so a question asked of the project that owns the report retrieved zero results.",
      "A run whose evidence was never read can no longer export a bundle. That refusal only covered imported runs, so a run whose checkpoint could not be decoded produced a bundle that numbered every citation against nothing and asserted a quality nobody observed.",
      "Approved reports can actually be indexed. The report splitter treated a heading and the prose beneath it as a heading alone whenever there was no blank line between them — which is what this product's own synthesizer writes — so it kept the heading and dropped the paragraph, and a full report reduced to nothing. Nothing raised an error; indexing simply logged that the report produced no chunks.",
      "The memory card counts memory, not the corpus. The two were blended, so a project with uploaded documents reported reports as indexed that retrieval could not reach.",
      "The verified-citation rate is measured on every approved report. It was NULL on every run ever produced — the engine measures it on a graph outcome a run never reaches, because approving at the report gate finalizes the run directly — while History offered a filter on it and every run card displayed it.",
      "The standalone verifier no longer crashes on Windows. Every check passed and then printing the result raised an encoding error, because a Windows console cannot render the tick character — a traceback where the word PASS should have been. It is the one program here a stranger runs on their own machine to check an artifact they were handed.",
      "A forced extraction pass no longer bills its first attempt twice, so a spend limit cannot fire on money that was never charged.",
      "The desktop app can start research. It drives the run in-process against its own checkpointer, because it has no broker to hand one to; in 2.0.0 the same button answered 501. Everything downstream is the server's code — same engine, same records, same artifact, same bundle.",
      "A task that fetched pages but never offered evidence no longer loses them: the engine asks for the extraction directly, from the text it already holds and nothing else. Every quotation is still checked against what the tools actually returned, and a quote found on a different fetched page is re-pointed at it with the claimed source recorded alongside.",
      "Approved reports are saved into their project's corpus automatically, so follow-up questions can draw on them without a re-upload.",
      "Research depth now changes the run rather than describing it. It reached the planner as a word in a prompt and nothing else, so \"Fast\" bought exactly as many model turns as \"Comprehensive\" — and turns are the whole wall-clock of a run, at minutes each on a hosted model. Fast is now 3 turns and 3 pages per task against comprehensive's 8, and the form states the numbers.",
      "A turn's page reads happen at once instead of one after another, and the executor is asked to request its pages in a single turn — which removes whole model round-trips rather than shaving seconds off one.",
      "One way to start research. A second start form existed on the older pipeline, labelled \"legacy\" in its own banner and absent from the navigation; it is gone, along with the version vocabulary that ran through the interface, the API paths and the code.",
      "Research recorded before runs is still readable, chattable and exportable — listed as Sessions, rather than by a version number.",
    ],
    known: [
      "Two research pipelines still exist in the backend. The product has one, and research recorded by the earlier one stays readable; consolidating them is not a patch.",
      "Follow-up chat scoped to a single report is available on research recorded as a session and not on a run. Project chat, which cites every approved report in a project, covers both.",
      "Cancelling a run still does not interrupt research already in flight — it runs to its next checkpoint, and the tokens spent there are recorded because they were really spent.",
      "Claim verification is still not implemented, claim lineage across revisions is still not tracked, and contradiction detection is still source-level and unscored.",
      "Corpus-mode research still has no end-to-end test, because it requires a local embedder and the test environment has none.",
      "Citation support is still measured at 90% on a single self-judged local-model run, and that measurement predates 2.0.0. It needs re-running before the number is leaned on.",
    ],
  },
  {
    version: "v2.0.0",
    date: "2026-08-25",
    headline:
      "Research becomes a structured record: evidence, claims, sources, conflicts, a human decision, and an artifact anyone can verify offline.",
    improved: [
      "A research run is no longer a report with citations bolted on. Evidence, sources, claims, claim-to-evidence links, contradictions, review decisions and the approved artifact are all first-class records you can inspect and export.",
      "Every claim in a report can be traced to the evidence it resolved to and the source that evidence came from — and a claim that resolved to nothing says so instead of looking supported.",
      "Retrieved is not cited, and retrieved is not verified. A source the report never cites keeps no citation number, and evidence carries a three-valued provenance state where UNCHECKED means nobody checked, not that it passed.",
      "Conflicting sources are surfaced as a first-class finding — two attributed quotations side by side with the reason they cannot both hold — rather than buried in prose.",
      "A run workspace built around that record: plan, evidence, claims, sources, conflicts, review and artifact as views over one run, with live progress that reconnects and replays what it missed rather than restarting.",
      "The review screen shows what you are approving: claims with and without evidence, cited versus retrieved-only sources, unresolved conflicts, and an unmeasured citation rate reported as unmeasured rather than as zero.",
      "Approving a report freezes a verifiable artifact. The bundle it produces passes the same standalone verifier that ships with it, offline, with no network and no model.",
      "A second human checkpoint before any search spends money: the research plan is reviewed on its own terms. Drop a task and it is never researched; reword one and that is what gets searched. Approving a plan never creates an artifact.",
      "Reports are versioned. A rework adds a revision; it never overwrites the one a reviewer already read.",
      "Follow-up questions can be pinned to this report, your corpus, the web, or everything — and the answer states which grounding produced it.",
      "PDF, Markdown, text and HTML documents preview in place from the corpus list, instead of downloading and switching applications. Uploaded HTML renders inside a fully sandboxed frame.",
      "History filters by verified-citation rate and by model, so a weak run is findable rather than buried.",
      "A one-shot import tool for research recorded by the earlier pipeline, with three separate verdicts — does the imported record say what the original said, is the bundle internally valid, and is every imported fact traceable to something the original recorded — kept apart rather than collapsed into one number. Removed in 2.0.1, its job done.",
      "Server and desktop serve the same routes, and a parity suite fails the build when one host has a route the other does not — follow-up chat and bundle export previously 404'd on desktop. Route parity is not feature parity, and this release does not claim it: executing a run was server-only, because it took a Redis lock, opened the server engine and checkpointed to Postgres. The desktop refused with 501 rather than creating a run nothing would advance. Fixed in 2.0.1.",
      "Keyless demo mode (`--fake`) no longer reaches a real embedding provider. It was billing real API calls on a run the product described as free.",
      "Stopping a run now sticks. Cancellation is durable state rather than an advisory event, and every writer that could move a run back out of it refuses to — a stopped run used to reappear minutes later awaiting approval. The tokens spent before the pipeline noticed are still recorded, because they were really spent.",
      "A run that used scripted models says so. Fake mode is selected automatically when no provider key is configured, and runs on it were recorded as real research: the bundle named models nothing had called, at a plausible cost, and the standalone verifier passed it without its demo banner.",
    ],
    known: [
      "No production database has been migrated. The tooling is validated against disposable copies — including one restored from real production data, which migrated 11 of 11 sessions with no fidelity mismatch — but running it on your own data is your decision and your backup.",
      "Two states are recorded as unimportable rather than repaired: evidence whose source URL was never recorded, and a plan approval for a run with no plan. Neither occurred in the restored-production run.",
      "Some history cannot be recovered at all and is recorded as absent rather than filled in: superseded report drafts, whether a plan was edited, and whether a run was cancelled. The earlier pipeline overwrote the first two and never recorded the third as a state.",
      "Corpus-mode research works but has no end-to-end test, because corpus mode requires a local embedder and the test environment has none.",
      "Cancelling a run does not interrupt research already in flight — it runs to its next checkpoint, and the tokens it spends there are recorded rather than dropped. What the stop does guarantee is that it sticks: a cancelled run stays cancelled, and the outcome arriving afterwards can no longer overwrite it and offer the report for approval.",
      "Claim verification is not implemented: claims are extracted from the report's prose and carry no per-claim judgement.",
      "Claim lineage across revisions is not tracked. Nothing observes that a sentence in revision 2 is the assertion from revision 1.",
      "Project memory does not yet ingest research runs. Fixed in 2.0.1.",
      "The run list returns the most recent runs up to a limit and is not paginated.",
      "Citation support is still measured at 90% on a single self-judged local-model run, and that measurement predates this work. It needs re-running before the number is leaned on.",
    ],
  },
  {
    version: "v1.0.2",
    date: "2026-08-15",
    headline: "Budgets became opt-in, and citation snippets became verifiable.",
    improved: [
      "Every run limit is now opt-in with 0 meaning unlimited. A hardcoded token ceiling used to kill long runs with no way to raise it.",
      "A citation snippet must be text that was actually fetched, so a quote cannot be reconstructed from a model's memory of a page.",
      "The evaluation baseline was corrected to stop scoring a competitor against placeholder text.",
      "CI waits for the worker to be ready instead of sleeping, and a flaky end-to-end run now fails the gate rather than passing quietly on a retry.",
    ],
    known: [
      "Cost caps remain inert on OpenRouter and custom providers, because the pricing catalog cannot price them. Cap spend at the provider.",
    ],
  },
  {
    version: "v1.0.1",
    date: "2026-08-15",
    headline:
      "Desktop distribution fixes: the bundle actually contained the app.",
    improved: [
      "The desktop bundle ships the sidecar it needs. The previous build produced a 5 MB app that passed CI, uploaded cleanly and died on first launch.",
      "Release assets are checksummed under the names they are actually served with, so verification succeeds instead of silently checking nothing.",
    ],
    known: [
      "Builds are unsigned. macOS and Windows will both warn on first launch; the download page explains the unblock steps before you download rather than leaving the OS to explain after.",
    ],
  },
  {
    version: "v1.0.0",
    date: "2026-08-14",
    headline:
      "First release: the pipeline, the human gate, and verifiable exports.",
    improved: [
      "Planner, executor, critic and synthesizer running as a graph, with a durable human approval checkpoint before anything is finalised.",
      "Every citation resolves to a source and a verbatim snippet; one that cannot be verified renders a warning chip instead of rendering clean.",
      "Markdown, PDF and hash-verifiable bundle exports, with a standalone offline verifier.",
      "Self-hosting with Docker, bring-your-own-key, and local models through Ollama.",
    ],
    known: [
      "Project memory is Postgres-only, so the desktop build has no cross-report memory.",
    ],
  },
];

/** The newest tagged release — what the download page should offer. */
export function latestRelease(): Release | null {
  return RELEASES.find((r) => !r.unreleased) ?? null;
}
