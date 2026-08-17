/**
 * The competitive comparison, as data (docs/01 §0).
 *
 * Data rather than prose in a component for two reasons. It is rendered twice — as a wide
 * table on desktop and as stacked cards on mobile, because a 6-column table is unreadable
 * at 375px and horizontal scroll hides exactly the columns that make the argument. And it
 * is the sort of content that goes stale: keeping it in one array means updating a claim
 * is one edit, not a hunt through JSX.
 *
 * **Honesty rules for editing this file.** The product's whole thesis is that a false
 * measurement is worse than no measurement, and a comparison table is the easiest place in
 * a codebase to quietly lie. So:
 *
 * - `no` and `partial` entries for *this* product are not defeats to hide. They are what
 *   makes the `yes` entries believable, and `LOSSES` below exists for the same reason.
 * - Competitor columns are a best-understanding snapshot, not audited fact. They move
 *   fast. `AS_OF` is rendered on the page so a reader can weigh it themselves.
 * - Never claim a capability here that is not built. Every `yes` in the `ours` column was
 *   verified against the working tree, and several are named in `MECHANISMS` with the file
 *   that implements them so the claim is checkable rather than assertive.
 */

export const AS_OF = "August 2026";

export type Support = "yes" | "partial" | "no" | "na";

export interface ComparisonRow {
  dimension: string;
  ours: Support;
  notebooklm: Support;
  scholar: Support;
  perplexity: Support;
  elicit: Support;
  /** Shown under the dimension name — why the row is worth a line at all. */
  note?: string;
}

export const COMPETITORS = [
  { key: "notebooklm", label: "NotebookLM" },
  { key: "scholar", label: "Scholar" },
  { key: "perplexity", label: "Perplexity" },
  { key: "elicit", label: "Elicit" },
] as const;

export const ROWS: ComparisonRow[] = [
  {
    dimension: "Finds the literature for you",
    ours: "yes",
    notebooklm: "partial",
    scholar: "yes",
    perplexity: "yes",
    elicit: "yes",
    note: "NotebookLM is strongest on documents you already have.",
  },
  {
    dimension: "Grounded in your own documents",
    ours: "yes",
    notebooklm: "yes",
    scholar: "no",
    perplexity: "partial",
    elicit: "partial",
  },
  {
    dimension: "Citation resolves to a verbatim snippet",
    ours: "yes",
    notebooklm: "yes",
    scholar: "no",
    perplexity: "no",
    elicit: "partial",
    note: "Not just a link — the exact sentence the claim rests on.",
  },
  {
    dimension: "Says when it cannot verify a citation",
    ours: "yes",
    notebooklm: "no",
    scholar: "na",
    perplexity: "no",
    elicit: "no",
    note: "A failed check renders a ⚠ chip rather than rendering clean.",
  },
  {
    dimension: "Standalone offline verifier",
    ours: "yes",
    notebooklm: "no",
    scholar: "no",
    perplexity: "no",
    elicit: "no",
    note: "No AI, no network, no account, no trust in us.",
  },
  {
    dimension: "Tamper-evident export",
    ours: "yes",
    notebooklm: "no",
    scholar: "no",
    perplexity: "no",
    elicit: "no",
    note: "Editing the report after approval breaks the hash chain.",
  },
  {
    dimension: "You approve the plan before it spends",
    ours: "yes",
    notebooklm: "no",
    scholar: "na",
    perplexity: "no",
    elicit: "no",
  },
  {
    dimension: "You approve the draft before it is final",
    ours: "yes",
    notebooklm: "no",
    scholar: "na",
    perplexity: "no",
    elicit: "no",
  },
  {
    dimension: "Zero network calls, guaranteed",
    ours: "yes",
    notebooklm: "no",
    scholar: "no",
    perplexity: "no",
    elicit: "no",
    note: "Airgapped corpus mode, with a test that does not stub what would egress.",
  },
  {
    dimension: "Runs on local models",
    ours: "yes",
    notebooklm: "no",
    scholar: "na",
    perplexity: "no",
    elicit: "no",
  },
  {
    dimension: "A different model per agent",
    ours: "yes",
    notebooklm: "no",
    scholar: "na",
    perplexity: "no",
    elicit: "no",
  },
  {
    dimension: "Self-hostable",
    ours: "yes",
    notebooklm: "no",
    scholar: "no",
    perplexity: "no",
    elicit: "no",
  },
  {
    dimension: "Your own API keys",
    ours: "yes",
    notebooklm: "no",
    scholar: "na",
    perplexity: "no",
    elicit: "no",
  },
  {
    dimension: "Cost visible before it is spent",
    ours: "yes",
    notebooklm: "na",
    scholar: "na",
    perplexity: "no",
    elicit: "no",
  },
  {
    dimension: "Polish, scale, ecosystem",
    ours: "no",
    notebooklm: "yes",
    scholar: "yes",
    perplexity: "yes",
    elicit: "yes",
    note: "Small and new. This is a real gap, not a rounding error.",
  },
  {
    dimension: "Audio overviews",
    ours: "no",
    notebooklm: "yes",
    scholar: "no",
    perplexity: "no",
    elicit: "no",
    note: "NotebookLM's are genuinely good and there is no answer to them here.",
  },
  {
    dimension: "Zero setup",
    ours: "no",
    notebooklm: "yes",
    scholar: "yes",
    perplexity: "yes",
    elicit: "yes",
    note: "Docker or a desktop app, plus your own keys.",
  },
];

export interface Mechanism {
  claim: string;
  how: string;
  why: string;
  /** Where it lives, so the claim can be checked rather than believed. */
  source: string;
}

export const MECHANISMS: Mechanism[] = [
  {
    claim: "Every [n] is falsifiable",
    how:
      "The executor submits evidence carrying a verbatim snippet. The synthesizer is shown " +
      "only that snippet — never the executor's paraphrase, because a model shown both " +
      "writes from the paraphrase and drifts past the quotable text. A separate pass then " +
      "checks each cited sentence against its snippet, and a failure is flagged rather than " +
      "hidden.",
    why:
      "NotebookLM links you to a passage. This tells you when the link does not hold up — " +
      "the difference between “here is where I got it” and “I checked, and this one is weak”.",
    source: "research_engine/graph.py",
  },
  {
    claim: "A third party can verify without trusting you",
    how:
      "The .bundle.json export carries the report, evidence, sources, contradictions, the " +
      "models actually dialled, cost, and the approval chain — with the report hashed " +
      "against the draft a human approved, and a bundle hash covering every field except " +
      "itself. A standalone verifier checks all of it offline.",
    why:
      "An advisor, reviewer or journal can confirm the synthesis was not edited after " +
      "approval without an account, an internet connection, or trusting the vendor. For " +
      "contested work that is a category difference, not a feature.",
    source: "research_engine/verify_bundle.py",
  },
  {
    claim: "Your unpublished manuscript never leaves the machine",
    how:
      "Corpus mode delegates retrieval exclusively to the local store, refuses every " +
      "non-corpus URL, and fails closed — an embedder that does not declare itself local is " +
      "treated as remote and rejected.",
    why:
      "A cloud product structurally cannot offer this. With embargoed data, patient records " +
      "or an unpublished draft, “upload it to Google” is not a decision you are allowed to " +
      "make.",
    source: "backend/tests/test_corpus_egress.py",
  },
];

export interface Audience {
  who: string;
  verdict: string;
  /** True when the honest answer is "use something else". */
  elsewhere: boolean;
  why: string;
}

export const AUDIENCES: Audience[] = [
  {
    who: "PhD student writing a literature review",
    verdict: "Use this",
    elsewhere: false,
    why: "The citation chain is the deliverable, and the design gate makes the structure yours.",
  },
  {
    who: "Researcher with confidential or embargoed data",
    verdict: "Use this",
    elsewhere: false,
    why: "The only option here that is genuinely airgapped.",
  },
  {
    who: "Anyone whose institution forbids cloud upload",
    verdict: "Use this",
    elsewhere: false,
    why: "Self-hosted, on your keys or your own GPU.",
  },
  {
    who: "Someone whose output has to survive scrutiny",
    verdict: "Use this",
    elsewhere: false,
    why: "The offline verifier exists for exactly this.",
  },
  {
    who: "Reading five PDFs you already have",
    verdict: "Use NotebookLM",
    elsewhere: true,
    why: "Better at it, free, no setup, and the audio overviews are excellent.",
  },
  {
    who: "Just trying to find papers",
    verdict: "Use Scholar",
    elsewhere: true,
    why: "It is search. This is not.",
  },
  {
    who: "Want a quick answer with links",
    verdict: "Use Perplexity",
    elsewhere: true,
    why: "Faster, and there is nothing to install.",
  },
  {
    who: "Non-technical, no Docker, no API keys",
    verdict: "Not yet",
    elsewhere: true,
    why: "The setup cost is real and it is the loudest weakness here.",
  },
];

export const LOSSES: string[] = [
  "Setup is a real barrier. NotebookLM is a URL; this is Docker or a desktop app plus API keys.",
  "No audio overviews, no mobile app, no collaboration. NotebookLM's polish is far ahead.",
  "Small and new — no ecosystem, no team features, one maintainer's budget.",
  "The headline metric is interim: citation support is 90%, measured once on a local model. One cited sentence in ten did not hold up. It is published rather than hidden, but it deserves re-measuring before it is leaned on.",
  "Quality tracks the models you route it at. Point it at a weak local model and you get weak research — the verification machinery will report that honestly rather than paper over it.",
];
