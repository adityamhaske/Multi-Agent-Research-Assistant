/**
 * Fixture payloads for the offline UI QA pass (`e2e/uiqa.mjs`).
 *
 * Not part of the test suite and not shipped: this is a stand-in backend used to *look at*
 * every run surface — including the states that are awkward to reach against a real stack
 * (a failed run, an unresolved citation, a conflicting pair, an empty project). Shapes are
 * copied from `lib/types.ts`, so a drift there shows up here as a screenshot that is wrong
 * rather than as a page that silently renders nothing.
 */

const PROJECT_ID = "11111111-1111-4111-8111-111111111111";
const RUN_ID = "22222222-2222-4222-8222-222222222222";
const RUN_RUNNING = "33333333-3333-4333-8333-333333333333";
const RUN_FAILED = "44444444-4444-4444-8444-444444444444";
const RUN_PLAN = "55555555-5555-4555-8555-555555555555";

export const IDS = { PROJECT_ID, RUN_ID, RUN_RUNNING, RUN_FAILED, RUN_PLAN };

export const user = {
  id: "u1",
  email: "researcher@example.com",
  is_active: true,
  created_at: "2026-07-01T09:00:00Z",
  display_name: "Ada Researcher",
  avatar_url: null,
  monthly_token_limit: 0,
  api_key_provider: "anthropic",
  api_key_hint: "sk-…9f2c",
  api_key_set_at: "2026-07-01T09:05:00Z",
  preferences: { density: "comfortable" },
};

export const projects = {
  projects: [
    {
      id: PROJECT_ID,
      name: "Agent Memory",
      description: "Long-term memory architectures for LLM agents.",
      archived_at: null,
      created_at: "2026-07-01T09:00:00Z",
      session_count: 3,
    },
    {
      id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
      name: "Retrieval Benchmarks",
      description: null,
      archived_at: null,
      created_at: "2026-07-11T09:00:00Z",
      session_count: 0,
    },
  ],
  total: 2,
};

const QUESTION =
  "What are the leading approaches to long-term memory in LLM agents, and their trade-offs?";

export const runs = {
  runs: [
    {
      id: RUN_ID,
      project_id: PROJECT_ID,
      question: QUESTION,
      status: "AWAITING_REVIEW",
      depth: "balanced",
      demo: false,
      cost_usd: 0.4271,
      citation_resolution_rate: 0.83,
      has_artifact: false,
      created_at: "2026-08-18T10:12:00Z",
    },
    {
      id: RUN_PLAN,
      project_id: PROJECT_ID,
      question: "Which vector index families hold up beyond a billion vectors?",
      status: "AWAITING_PLAN",
      depth: "comprehensive",
      demo: false,
      cost_usd: 0,
      citation_resolution_rate: null,
      has_artifact: false,
      created_at: "2026-08-19T06:02:00Z",
    },
    {
      id: RUN_RUNNING,
      project_id: PROJECT_ID,
      question: "How do episodic and semantic memory split in current agent frameworks?",
      status: "RUNNING",
      depth: "fast",
      demo: true,
      cost_usd: 0.0031,
      citation_resolution_rate: null,
      has_artifact: false,
      created_at: "2026-08-19T06:30:00Z",
    },
    {
      id: RUN_FAILED,
      project_id: PROJECT_ID,
      question: "Do memory-augmented agents beat long-context models on multi-session tasks?",
      status: "FAILED",
      depth: "balanced",
      demo: false,
      cost_usd: 0.02,
      citation_resolution_rate: null,
      has_artifact: false,
      created_at: "2026-08-17T14:00:00Z",
    },
  ],
};

const REPORT = `# Long-term memory in LLM agents

Three families dominate current practice, and they trade off along different axes.

## Retrieval-augmented memory

Most deployed systems store interaction history as embedded chunks and retrieve the
top *k* at inference time [1]. This is cheap and requires no retraining, but recall
degrades as the store grows past a few hundred thousand entries [2].

| Approach | Write cost | Read cost | Degrades on |
| --- | --- | --- | --- |
| Retrieval | low | low | store size |
| Summarisation | medium | low | detail loss |
| Parametric | very high | none | staleness |

## Hierarchical summarisation

Rolling summaries keep the context window small, at the cost of detail that cannot be
recovered later [1, 3]. Two evaluations disagree sharply about how much is lost [4].

\`\`\`python
memory.write(summarize(window), scope="episodic")   # a very long line that has to scroll horizontally rather than break the page layout in half
\`\`\`

## Parametric memory

Fine-tuning weights on interaction traces removes the read cost entirely but makes
updates expensive and forgetting hard to audit [7].

See https://example.invalid/a-very-long-url-that-must-not-break-the-layout-when-it-is-rendered-inline-in-prose for the full comparison.
`;

const SOURCES = [
  {
    id: "s1",
    url: "https://arxiv.invalid/abs/2401.00001",
    title: "Retrieval-Augmented Agent Memory at Scale",
    kind: "WEB",
    retrieval_status: "FETCHED",
    citation_index: 1,
    corpus_document_id: null,
  },
  {
    id: "s2",
    url: "https://blog.invalid/posts/memory-recall-degradation",
    title: "Recall degradation past 100k entries",
    kind: "WEB",
    retrieval_status: "FETCHED",
    citation_index: 2,
    corpus_document_id: null,
  },
  {
    id: "s3",
    url: "corpus://doc-7#chars=1200-1480&page=4",
    title: "internal-memo-2026.pdf",
    kind: "CORPUS",
    retrieval_status: "CORPUS_DOCUMENT",
    citation_index: 3,
    corpus_document_id: "doc-7",
  },
  {
    id: "s4",
    url: "https://news.invalid/very/long/path/segment/that/keeps/going/and/going/to/test/truncation",
    title: "Two evaluations of summarisation loss",
    kind: "WEB",
    retrieval_status: "FETCHED",
    citation_index: 4,
    corpus_document_id: null,
  },
  {
    id: "s5",
    url: "https://unused.invalid/never-cited",
    title: null,
    kind: "WEB",
    retrieval_status: "FETCHED",
    citation_index: null,
    corpus_document_id: null,
  },
];

const EVIDENCE = [
  {
    id: "e1",
    source_id: "s1",
    sequence: 1,
    task_id: "1",
    snippet:
      "Systems in production overwhelmingly store interaction history as embedded chunks and retrieve the top k at inference time.",
    content_hash: "a".repeat(64),
    key_fact: "Retrieval is the default deployed approach.",
    provenance_state: "ATTESTED",
    attested_against: "FETCHED_BODY",
    attestation_run_at: "2026-08-18T10:20:00Z",
  },
  {
    id: "e2",
    source_id: "s2",
    sequence: 2,
    task_id: "1",
    snippet:
      "Recall@10 fell from 0.91 to 0.62 as the store grew from 10,000 to 500,000 entries, with no change to the retriever or the embedding model. " +
      "The authors attribute the drop to nearest-neighbour crowding rather than to embedding quality, and note that the effect appears in every index family they tested, including HNSW, IVF-PQ and a flat baseline. " +
      "They caution that the absolute numbers are dataset-specific and that the trend, not the value, is the finding.",
    content_hash: "b".repeat(64),
    key_fact: "Recall@10 0.91 → 0.62 from 10k to 500k entries.",
    provenance_state: "ATTESTED",
    attested_against: "FETCHED_BODY",
    attestation_run_at: "2026-08-18T10:20:00Z",
  },
  {
    id: "e3",
    source_id: "s3",
    sequence: 3,
    task_id: "2",
    snippet: "Our own rollout saw the same crowding effect at roughly 200,000 entries.",
    content_hash: "c".repeat(64),
    key_fact: null,
    provenance_state: "UNCHECKED",
    attested_against: null,
    attestation_run_at: null,
  },
  {
    id: "e4",
    source_id: "s4",
    sequence: 4,
    task_id: "2",
    snippet: "",
    content_hash: "d".repeat(64),
    key_fact: null,
    provenance_state: "UNATTESTED",
    attested_against: "SEARCH_SNIPPET",
    attestation_run_at: "2026-08-18T10:21:00Z",
  },
];

const CLAIMS = [
  {
    id: "c1",
    revision_id: "r2",
    position: 0,
    text: "Most deployed systems store interaction history as embedded chunks and retrieve the top k at inference time [1].",
    extraction_method: "DERIVED_FROM_REPORT",
    verification_state: "SUPPORTED",
    verification_method: "MODEL_JUDGE",
    lineage_id: null,
  },
  {
    id: "c2",
    revision_id: "r2",
    position: 1,
    text: "Recall degrades as the store grows past a few hundred thousand entries [2].",
    extraction_method: "DERIVED_FROM_REPORT",
    verification_state: "SUPPORTED",
    verification_method: "NUMERIC_GROUNDING",
    lineage_id: null,
  },
  {
    id: "c3",
    revision_id: "r2",
    position: 2,
    text: "Rolling summaries keep the context window small, at the cost of detail that cannot be recovered later [1, 3].",
    extraction_method: "DERIVED_FROM_REPORT",
    verification_state: "INSUFFICIENT_EVIDENCE",
    verification_method: "MODEL_JUDGE",
    lineage_id: null,
  },
  {
    id: "c4",
    revision_id: "r2",
    position: 3,
    text: "Fine-tuning weights on interaction traces removes the read cost entirely but makes updates expensive and forgetting hard to audit [7].",
    extraction_method: "DERIVED_FROM_REPORT",
    verification_state: "UNCHECKED",
    verification_method: "NOT_RUN",
    lineage_id: null,
  },
];

export function graph(overrides = {}) {
  const base = {
    run: {
      id: RUN_ID,
      project_id: PROJECT_ID,
      question: QUESTION,
      status: "AWAITING_REVIEW",
      depth: "balanced",
      corpus_mode: false,
      demo: false,
      skip_plan_gate: false,
      model_routing: {
        planner: "anthropic:claude-sonnet-4-6",
        executor: "anthropic:claude-haiku-4-5",
        critic: "anthropic:claude-sonnet-4-6",
        synthesizer: "anthropic:claude-sonnet-4-6",
      },
      cost_usd: 0.4271,
      tokens_input: 184_233,
      tokens_output: 12_904,
      elapsed_seconds: 214.4,
      citation_resolution_rate: 0.83,
      error_message: null,
      cancelled_at: null,
      created_at: "2026-08-18T10:12:00Z",
      updated_at: "2026-08-18T10:16:00Z",
    },
    plans: [
      {
        id: "pl1",
        version: 1,
        tasks: [
          {
            id: 1,
            query: "Survey retrieval-augmented memory architectures for LLM agents",
            rationale: "Establishes the baseline every other approach is compared against.",
            subtopics: ["chunking", "index families", "recall at scale"],
            include: true,
            source_hint: null,
          },
          {
            id: 2,
            query: "Find measured recall degradation as a memory store grows",
            rationale: "The central trade-off claim needs a number behind it.",
            subtopics: ["recall@k", "store size"],
            include: true,
            source_hint: null,
          },
          {
            id: 3,
            query: "Compare hierarchical summarisation against parametric memory",
            rationale: "",
            subtopics: [],
            include: true,
            source_hint: null,
          },
        ],
        outline_sections: [
          { title: "Retrieval-augmented memory", description: "What is deployed today" },
          { title: "Hierarchical summarisation", description: "What it costs" },
          { title: "Parametric memory", description: "Why it is rare" },
        ],
        origin: "MODEL_PROPOSED",
        approved_at: "2026-08-18T10:13:00Z",
      },
    ],
    sources: SOURCES,
    evidence: EVIDENCE,
    revisions: [
      {
        id: "r1",
        version: 1,
        report_markdown: "# Draft\n\nAn earlier draft, kept.",
        report_hash: "e".repeat(64),
        evidence_watermark: 2,
        created_at: "2026-08-18T10:14:00Z",
      },
      {
        id: "r2",
        version: 2,
        report_markdown: REPORT,
        report_hash: "f0e1d2c3b4a5" + "9".repeat(52),
        evidence_watermark: 4,
        created_at: "2026-08-18T10:16:00Z",
      },
    ],
    claims: CLAIMS,
    claim_evidence_links: [
      { id: "l1", claim_id: "c1", evidence_id: "e1", stance: "SUPPORTS", origin: "CITATION_MARKER" },
      { id: "l2", claim_id: "c2", evidence_id: "e2", stance: "SUPPORTS", origin: "CITATION_MARKER" },
      { id: "l3", claim_id: "c3", evidence_id: "e3", stance: "CONTEXT", origin: "MODEL_ASSERTED" },
    ],
    contradictions: [
      {
        id: "x1",
        source_a_id: "s2",
        source_b_id: "s4",
        evidence_a_id: "e2",
        evidence_b_id: null,
        quote_a: "Recall@10 fell from 0.91 to 0.62 as the store grew to 500,000 entries.",
        quote_b: "We observed no measurable recall loss up to two million entries.",
        summary_a: "Recall collapses well before a million entries.",
        summary_b: "Recall holds past a million entries.",
        nature:
          "Both describe the same retriever family at overlapping store sizes, so they cannot both be describing the same effect.",
        dimension: "UNCLASSIFIED",
        detection_state: "DETECTED",
        review_state: "UNREVIEWED",
      },
      {
        id: "x2",
        source_a_id: null,
        source_b_id: null,
        evidence_a_id: null,
        evidence_b_id: null,
        quote_a: "A pair the detector could not anchor.",
        quote_b: "Its counterpart.",
        summary_a: null,
        summary_b: null,
        nature: null,
        dimension: "UNCLASSIFIED",
        detection_state: "NOT_RUN",
        review_state: "UNREVIEWED",
      },
    ],
    reviews: [
      {
        id: "rv1",
        sequence: 1,
        gate: "PLAN",
        decision: "APPROVED",
        revision_id: null,
        plan_version_id: "pl1",
        feedback: null,
        reviewed_hash: "1".repeat(64),
        created_at: "2026-08-18T10:13:00Z",
      },
      {
        id: "rv2",
        sequence: 2,
        gate: "REPORT",
        decision: "REWORK_REQUESTED",
        revision_id: "r1",
        plan_version_id: null,
        feedback: "Say which benchmark the recall numbers come from.",
        reviewed_hash: "e".repeat(64),
        created_at: "2026-08-18T10:15:00Z",
      },
    ],
    artifact: null,
  };
  return { ...base, ...overrides };
}

export const verification = {
  assembled: true,
  reason: null,
  passed: false,
  bundle_hash: "9".repeat(64),
  frozen: false,
  checks: [
    { name: "bundle_integrity", passed: true, detail: null },
    { name: "report_integrity", passed: true, detail: null },
    { name: "evidence_integrity", passed: true, detail: null },
    {
      name: "citation_resolution",
      passed: false,
      detail: "marker [7] resolves to no source\nand a second line that must not be shown",
    },
    { name: "claim_evidence_linkage", passed: true, detail: null },
    { name: "approval_chain", passed: false, detail: "no approved REPORT review" },
  ],
};

export const verificationFrozen = {
  ...verification,
  passed: true,
  frozen: true,
  checks: verification.checks.map((c) => ({ ...c, passed: true, detail: null })),
};

export const artifact = {
  id: "art-1",
  artifact_hash: "7".repeat(64),
  format_version: 1,
  review_id: "rv3",
  review_gate: "REPORT",
  review_decision: "APPROVED",
  revision_id: "r2",
  demo: false,
  created_at: "2026-08-18T10:30:00Z",
};

export const sessions = {
  sessions: [
    {
      session_id: "sess-1",
      project_id: PROJECT_ID,
      status: "COMPLETED",
      prompt: "An older question, recorded as a session.",
      research_depth: "balanced",
      total_cost_usd: 0.19,
      total_tokens_input: 90_000,
      total_tokens_output: 8_000,
      elapsed_seconds: 130,
      rework_count: 0,
      created_at: "2026-07-20T10:00:00Z",
      archived_at: null,
      corpus_mode: false,
      demo: false,
      citation_resolution_rate: 1,
      model_routing: { planner: "anthropic:claude-sonnet-4-6" },
    },
  ],
  total: 1,
  page: 1,
  limit: 20,
};

export const corpusStatus = { documents: 4, chunks: 812 };
export const corpusDocuments = [
  {
    id: "doc-7",
    filename: "internal-memo-2026.pdf",
    size_bytes: 240_112,
    chunks: 88,
    created_at: "2026-07-15T10:00:00Z",
  },
];
export const memoryStatus = {
  available: true,
  chunk_count: 240,
  indexed_reports: 2,
  approved_reports: 3,
  pending_reports: 1,
  current_model: "openai:text-embedding-3-small",
  models: [],
  stale_models: [],
  last_ingest_at: "2026-08-10T10:00:00Z",
};
export const routing = {
  routing: {
    planner: "anthropic:claude-sonnet-4-6",
    executor: "anthropic:claude-haiku-4-5",
    critic: "anthropic:claude-sonnet-4-6",
    synthesizer: "anthropic:claude-sonnet-4-6",
    chat: "anthropic:claude-sonnet-4-6",
  },
  effective_routing: {},
};
export const readiness = { ready: true, local_reachable: false };
