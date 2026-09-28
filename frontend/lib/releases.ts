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
    version: "v3.0.0",
    date: "2026-09-28",
    headline:
      "You can rewrite how each research agent behaves, and every artifact now records exactly which instructions produced it.",
    improved: [
      "Each of the five agents \u2014 planner, executor, critic, synthesizer and follow-up chat \u2014 can follow your own instructions instead of the shipped ones. Settings \u2192 Agents shows which agents are customized, starts every editor from the prompt that runs today, and resets any agent to the shipped prompt on its own. Instructions are limited to 2,500 characters per agent, and an empty box is never mistaken for a reset.",
      "The checks that keep research honest cannot be rewritten. Citation verification, contradiction detection, report repair and project chat\u2019s refusal line always run on the shipped prompts, whatever an agent is told \u2014 enforced in one place, before any saved instruction is read.",
      "A run keeps the instructions it started with. Editing an agent while a run waits at a review gate changes the next run, not the half-finished one, so a report is never written under two sets of instructions.",
      "Verification bundles record the instructions behind the research. A run\u2019s bundle now carries, for every prompt the pipeline used, its full text, its SHA-256 and whether it was replaced \u2014 and editing any of it after the fact fails the bundle\u2019s integrity check. The standalone verifier prints which agents ran on replaced instructions, so a clean pass no longer hides that.",
      "The app says when your instructions did and did not apply. A run\u2019s artifact names every agent that ran on replaced instructions, and research recorded on the earlier pipeline \u2014 which does not use them \u2014 says so rather than implying it did.",
      "Customized instructions can be measured before you trust them. The evaluation harness runs a candidate against the same fixed questions and the same thresholds as the shipped prompts, and reports both side by side; a candidate that scores worse is reported, not refused.",
      "Citation support is graded by an independent judge that the result names. The evaluation used to grade the pipeline\u2019s citations with the pipeline\u2019s own critic model and recorded no judge at all. A real-model evaluation now refuses to start without a judge that is none of the models under test, and the result records which model actually answered each ruling. This release\u2019s own run \u2014 Gemini 2.5 Flash running every agent, Claude Sonnet 4.5 judging \u2014 measured citation support at 96.4% over the ten fixed questions, clearing the 95% threshold.",
      "Stopping research holds wherever the stop lands. On the server, research stopped mid-run could reach the review gate anyway, or lose what it had spent; and on both hosts, research stopped just after it started could be left showing as running. Each case now keeps the stop, and the spend.",
      "Upgrading keeps everything. A desktop data directory written by the real 2.1.0 app \u2014 settings, projects, research on both pipelines, a run waiting at a review gate, and bundles already exported \u2014 was upgraded by the packaged 3.0.0 engine and checked: nothing lost, old bundles still verify, the waiting run can still be approved, and new research carries its instructions.",
    ],
    known: [
      "Bundles from this release are format v2, and a verifier from before 3.0.0 refuses them. Check a bundle with the verifier from this release; it still verifies every earlier bundle unchanged.",
      "Research recorded before 3.0.0 still exports as a v1 bundle with no instructions recorded. Its prompts were never captured, and the bundle does not invent them.",
      "Research recorded on the earlier pipeline (Sessions) does not apply customized instructions, and says so.",
      "Customization is per account and applies to every run you start; there is no per-run override, and you cannot add agents of your own.",
      "Customized instructions are written into the verification bundle in full, so anyone you share a bundle with can read them.",
      "The default model routing is Google\u2019s Gemini 2.5 models \u2014 2.5 Pro for the planner and synthesizer, 2.5 Flash for the executor, critic and chat \u2014 and Google now limits each 2.5 model to accounts that have used it before. On a key from an account that has not, the first call to that model is refused. Choose other models in Settings \u2192 Models.",
      "On a fresh desktop install, the demo report the app prepares on first launch fails: it is treated as corpus-only research against an empty corpus, so it finds no evidence. Your own research is unaffected.",
      "Citation support rests on one run: ten fixed questions on one model routing. It measures whether each claim matches the evidence it cites, not whether the claim is true.",
      "The share of evidence coming from primary sources is not measured, and is deliberately not estimated. The source URL on a piece of evidence is written by the model, so an invented link would score as a primary source with full confidence.",
      "Three questions of the scholarly evaluation set carry citation-check records and three are unverified; the set is not yet used to grade anything.",
      "Retrieval is dense-only; hybrid retrieval was measured against the baseline and did not beat it.",
      "Desktop builds are unsigned and do not auto-update. macOS shows a Gatekeeper block and Windows shows SmartScreen on first launch.",
      "Two research pipelines still exist in the backend. The product has one, and research recorded by the earlier one stays readable.",
      "Follow-up chat scoped to a single report is available on research recorded as a session and not on a run. Project chat, which cites every approved report in a project, covers both.",
      "Cancelling a run still does not interrupt research already in flight \u2014 it runs to its next checkpoint, and the tokens spent there are recorded because they were really spent.",
      "Claim verification is still not implemented, claim lineage across revisions is still not tracked, and contradiction detection is still source-level and unscored.",
    ],
  },
  {
    version: "v2.1.0",
    date: "2026-09-19",
    headline:
      "Two claims the product makes about itself turned out not to hold, and the things that would have caught them did not exist.",
    improved: [
      "Airgapped corpus mode now actually holds on the server. A run you requested as corpus-only \u2014 and which was recorded as corpus-only \u2014 could still search the open web and fetch pages from it. The flag reached the database and the corpus store, but never the code that decides whether anything asks the web in the first place, so the guarantee was recorded rather than enforced. The desktop had been fixed months earlier; the server had not. The test that should have caught it was green throughout, because it built the configuration by hand and skipped the exact step that was broken.",
      "Follow-up chat remembers what you just said. Both chat surfaces loaded the first twenty messages ever written to a conversation instead of the last twenty, so past turn twenty the model was answering a question it had never been shown \u2014 your new message was saved, then left out of the window assembled from it.",
      "Retrieval quality is measured, and the numbers are published. Four documents called retrieval the ceiling on report quality and nothing measured it. There is now a frozen sixteen-document set and a recorded baseline: recall@1 0.792, precision@1 0.917, nDCG@10 0.944, duplicate rate 0.000.",
      "A corpus can say which corpus it is, and documents have versions. Re-uploading a document supersedes the old one rather than silently sitting beside it, and a run records the corpus it read, so \u201cwhich documents produced this evidence\u201d is answerable after the fact rather than inferred from a filename.",
      "Operators get real telemetry. A server-side metrics endpoint exposes seven metric families in Prometheus text on a private registry, and terminal outcomes are recorded where runs actually end rather than where they were expected to. Run identifiers were also being logged under the field reserved for session identifiers, which made a run\u2019s logs unfindable by its own id.",
      "Database downgrades work. No downgrade had ever been run against this schema, and the first one attempted failed on every database \u2014 one migration dropped a constraint under a name the naming convention had already rewritten. CI now runs a populated migration round-trip in both directions.",
      "A scripted demo run can no longer pass by doing nothing. Fake mode picked its behaviour by searching the system prompt for hand-typed fragments of its own prose, falling through to an empty result when nothing matched. Rewording any prompt would have routed every scripted test to that branch and left the suite green on a pipeline producing nothing.",
      "The readiness check\u2019s tests no longer depend on the machine they run on. Whether the settings page reported you as ready to research was asserted from a live probe of the developer\u2019s own computer, so the same commit passed or failed depending on whether Ollama happened to be running.",
    ],
    known: [
      "Citation support is still measured at 90% on a single self-judged local-model run, and that measurement predates 2.0.0. Nothing in this release re-ran it, and it still needs re-running before the number is leaned on.",
      "Retrieval is dense-only. Hybrid retrieval was built and measured against the baseline above, and it did not beat it \u2014 the residual gap is equal-weight fusion of two retrievers of unequal reliability, not the quality of the candidates. It was rejected and reported rather than tuned until it looked better.",
      "The share of evidence coming from primary sources is not measured, and is deliberately not estimated. The source URL on a piece of evidence is written by the model, so a plausible-looking but invented link would score as a primary source with full confidence. A fakeable metric on a verifiability product is worse than none.",
      "The scholarly evaluation set is drafted but unverified. Six of twelve questions survived review, and their rubrics were written without a human opening a cited paper. Until a domain reader checks them, a rubric naming the wrong study would penalize a correct answer, so the set grades nothing. [Corrected 2026-09-27, in 3.0.0: this overstated it. The repository\u2019s own records show three of the six surviving questions carry citation-check records dated 2026-08-16 \u2014 two verified, one verified with a caveat \u2014 each stating that the works it names were looked up against the published record. The other three are unverified. The records do not say who performed the checks.]",
      "Desktop builds are unsigned and do not auto-update. macOS shows a Gatekeeper block and Windows shows SmartScreen on first launch, and a new version means downloading the installer again.",
      "Two research pipelines still exist in the backend. The product has one, and research recorded by the earlier one stays readable; consolidating them is not a patch.",
      "Follow-up chat scoped to a single report is available on research recorded as a session and not on a run. Project chat, which cites every approved report in a project, covers both.",
      "Cancelling a run still does not interrupt research already in flight \u2014 it runs to its next checkpoint, and the tokens spent there are recorded because they were really spent.",
      "Claim verification is still not implemented, claim lineage across revisions is still not tracked, and contradiction detection is still source-level and unscored.",
    ],
  },
  {
    version: "v2.0.2",
    date: "2026-08-31",
    headline:
      "The desktop app stopped reimplementing the server, and four bugs that only existed because it had.",
    improved: [
      "Every desktop settings-page load stopped 404ing in the background. The readiness check the settings page fetches on every host had no route on desktop at all — the frontend called it unconditionally and only branched on what it did with the answer, so the request itself always failed silently. It has a route now, answering from this host's own keys instead of the server's.",
      "Choosing the \"Local\" model preset on desktop now offers a model the machine actually has installed, instead of a fixed name that may never have been pulled. The server has done this since 2.0.0; the desktop build never picked it up.",
      "The routing panel's \"deployment default\" no longer mirrors your own saved preference back at you. Saving a per-role routing choice made the two numbers identical on desktop, which defeats the reason that comparison exists — seeing what changes if you clear your preference.",
      "A project containing research runs and no chat sessions no longer shows a session count of zero. The desktop's own project list only ever counted the older kind of research.",
      "Stopping a run from the desktop now records why in the same place a provider error would — a client reading the failure reason from the run's event history found nothing there for a user-stopped run specifically, even though the reason was visible elsewhere on the same screen.",
      "The desktop app and the server now run the same code for every project, corpus, and research-session operation that does not depend on where a secret is stored — proved by the two literally resolving to one function, not by two implementations that currently happen to agree. A fix to one of these from here on reaches both hosts by construction.",
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
