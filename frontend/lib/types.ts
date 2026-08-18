/**
 * Shared types mirroring the backend contracts (backend/app/schemas/*, models/session.py).
 * Kept in sync by hand — the OpenAPI schema is the source of truth if these drift.
 */

export type SessionStatus =
  | "PENDING"
  | "RUNNING"
  /**
   * Paused at the research design gate (docs/07 §2, Phase 4) — the planner has proposed
   * subtopics and an outline and is waiting on the reviewer, before any search has spent
   * anything. Distinct from AWAITING_APPROVAL because the two resume with different
   * payloads: this one takes an edited plan, that one takes an approve/rework decision.
   */
  | "AWAITING_PLAN"
  | "AWAITING_APPROVAL"
  | "COMPLETED"
  | "FAILED";

export type ResearchDepth = "fast" | "balanced" | "comprehensive";

/**
 * What a follow-up question may read (docs/07 §2, Phase 5; req 8). Mirrors
 * `backend/app/services/chat_scope.py::ChatScope` — one word must mean one thing on both
 * chat surfaces, which is why the wire value is shared and only the *label* of `report`
 * differs between them ("This report" vs "My research").
 *
 * `report` is the default on both, and is exactly today's behaviour, so a client that
 * omits the field gets the answer it got before this existed.
 */
export type ChatScope = "report" | "corpus" | "web" | "everything";

export type AgentName = "planner" | "executor" | "critic" | "synthesizer";

export type ApiKeyProvider = "google" | "anthropic" | "openai" | "openrouter" | "custom";

/**
 * Desktop key status (docs/12 M9). Hints only — the key itself never leaves the OS
 * keychain. `keychain` is a pasted key stored locally; `environment` came from a
 * process env var and is read-only from the UI.
 */
export interface DesktopKeyStatus {
  keychain: boolean;
  environment: boolean;
}
export type DesktopKeys = Record<ApiKeyProvider, DesktopKeyStatus>;

/**
 * Three states, never a bare boolean (docs/07 §2, Phase 2a; AGENTS.md "Honest
 * three-state status"). `degraded` is load-bearing: "the server answered but rejected
 * the key" and "nothing answered at all" have different fixes.
 */
export type ConnectionState = "ok" | "degraded" | "failed";

export interface ConnectionVerdict {
  state: ConnectionState;
  reason: string;
  checked_at: string;
  model_count: number | null;
}

/**
 * The settings IA's customization surface (docs/07 §2, Phase 3). Every field is
 * optional — `undefined`/`null` means "use the default", the same behaviour a user
 * who has never opened Settings already gets.
 */
export interface UserPreferences {
  retrieval_k?: number | null;
  min_sources_per_task?: number | null;
  snippet_max_chars?: number | null;
  density?: "comfortable" | "compact" | null;
}

export interface User {
  id: string;
  email: string;
  is_active: boolean;
  created_at: string;
  // Profile
  display_name: string | null;
  avatar_url: string | null;
  monthly_token_limit: number;
  // BYOK status — the key itself is never sent to the client.
  api_key_provider: ApiKeyProvider | null;
  api_key_hint: string | null;
  api_key_set_at: string | null;
  // Set only by the response to PUT /me/api-key — saving a key tests it in the same
  // request. `null`/absent everywhere else this type is used.
  connection_verdict?: ConnectionVerdict | null;
  preferences: UserPreferences;
}

export interface ProfileUpdate {
  display_name?: string | null;
  avatar_url?: string | null;
  monthly_token_limit?: number;
  /** Merged into stored preferences server-side, never replaced (docs/07 §2). */
  preferences?: UserPreferences;
}

export interface UsageWindow {
  tokens_input: number;
  tokens_output: number;
  tokens_total: number;
  cost_usd: number;
  sessions: number;
}

export interface Usage {
  month: UsageWindow;
  week: UsageWindow;
  last_session: UsageWindow;
  monthly_token_limit: number;
  limit_remaining: number | null;
  limit_reached: boolean;
}

export interface Source {
  index: number;
  url: string;
  title: string;
  /** First extracted snippet. Kept for sessions stored before `snippets` existed. */
  snippet: string;
  /**
   * Every verbatim snippet extracted from this source (docs/12 M5, defect D3).
   *
   * One page commonly backs several distinct facts and the same source is cited for ~8
   * different claims per report. Showing only the first snippet meant hovering a citation
   * could surface text unrelated to the sentence it was attached to. Optional because
   * sessions stored before the fix only carry `snippet`.
   */
  snippets?: string[];
}

/** A container for research (docs/14 §3). */
export interface Project {
  id: string;
  name: string;
  description: string | null;
  archived_at: string | null;
  created_at: string;
  session_count: number;
}

export interface ProjectListResponse {
  projects: Project[];
  total: number;
}

export interface SessionSummary {
  session_id: string;
  project_id: string;
  status: SessionStatus;
  prompt: string;
  research_depth: string;
  total_cost_usd: number;
  total_tokens_input: number;
  total_tokens_output: number;
  elapsed_seconds: number | null;
  rework_count: number;
  created_at: string;
  /** Set when the session is archived (out of the active list, fully recoverable). */
  archived_at: string | null;
  corpus_mode: boolean;
  /**
   * Produced with scripted models and fixture sources rather than a real provider
   * (docs/17 §6.2). Present on the summary, not just the detail, because history lists
   * sessions side by side and an unmarked demo sitting next to real work is the exact
   * confusion the flag exists to prevent.
   */
  demo: boolean;
  /**
   * Fraction of this report's in-text `[n]` markers that resolve to a real source.
   *
   * **`null` means not measured** — the report made no citable claims, or it finished
   * before this was recorded. Never render it as 0, which means the opposite: every
   * marker it did make points at nothing.
   */
  citation_resolution_rate: number | null;
  /** Which models produced this report. `null` when a run failed before routing
   *  resolved — on the summary so History can filter by model. */
  model_routing: Record<string, string> | null;
}

export interface SessionDetail extends SessionSummary {
  draft_report: string | null;
  final_report: string | null;
  sources: Source[] | null;
  error_message: string | null;
  updated_at: string;
}

export interface SessionListResponse {
  sessions: SessionSummary[];
  total: number;
  page: number;
  limit: number;
}

export interface ResearchStartResponse {
  session_id: string;
  status: SessionStatus;
}

export interface ChatMessage {
  id: string;
  /** Null for project-thread messages — a message has one parent, never both (docs/14 §3). */
  session_id: string | null;
  role: "user" | "assistant";
  content: string;
  created_at: string;
}

// ─── Project memory & chat threads (docs/14) ─────────────────────────────────────

/** A conversation scoped to a project rather than to one report. */
export interface ChatThread {
  id: string;
  project_id: string;
  title: string;
  message_count: number;
  created_at: string;
  last_message_at: string;
}

export interface ThreadListResponse {
  threads: ChatThread[];
  total: number;
}

/**
 * One `[R{n}]` marker resolved to the approved report it came from.
 *
 * `excerpt` is the retrieved chunk verbatim, so a reader can check the claim against the
 * exact text behind it — the same standard report citations meet with their snippets.
 */
export interface MemoryCitation {
  marker: string;
  session_id: string;
  title: string;
  created_at: string;
  excerpt: string;
}

export interface ThreadMessage {
  id: string;
  thread_id: string | null;
  role: "user" | "assistant";
  content: string;
  citations: MemoryCitation[] | null;
  created_at: string;
}

export interface MemoryModelBreakdown {
  embedding_model: string;
  chunks: number;
  reports: number;
}

/**
 * What a project remembers, and what it is missing (docs/14 §8).
 *
 * `pending_reports` and `stale_models` are the two ways memory can quietly be
 * incomplete — an ingestion that failed, and chunks written by an embedding model that
 * is no longer configured. Both are surfaced rather than left to be discovered as
 * "chat can't find my research".
 */
export interface MemoryStatus {
  available: boolean;
  chunk_count: number;
  indexed_reports: number;
  approved_reports: number;
  pending_reports: number;
  current_model: string;
  models: MemoryModelBreakdown[];
  stale_models: string[];
  last_ingest_at: string | null;
}

/**
 * A pipeline event as emitted by the backend (backend/app/agent/events.py). The SSE
 * `id:` line carries the durable agent_logs row id used for Last-Event-ID replay.
 */
export interface AgentEvent {
  type:
    | "connected"
    | "agent_log"
    | "PLAN_READY"
    | "HITL_READY"
    | "COMPLETED"
    | "FAILED"
    | string;
  id?: number;
  ts?: string | null;
  agent?: AgentName | null;
  message?: string | null;
  detail?: Record<string, unknown> | null;
  data?: Record<string, unknown> | null;
}

// ─── Model catalog & routing (docs/12 M8) ────────────────────────────────────────

export type AgentRole = "planner" | "executor" | "critic" | "synthesizer" | "chat";

/** A per-role map of "provider:model" routes. */
export type ModelRouting = Record<AgentRole, string>;

export interface ModelInfo {
  route: string;
  provider: string;
  model_id: string;
  display_name: string;
  /** null means the deployment must supply a price — such models can't be routed to. */
  input_per_mtok: number | null;
  output_per_mtok: number | null;
  context_window: number | null;
  max_output_tokens: number | null;
  supports_tools: boolean;
  supports_structured_output: boolean;
  notes: string;
  /** False when this user has no usable key for the provider. Shown disabled, not hidden. */
  available: boolean;
}

export interface ModelCatalog {
  roles: AgentRole[];
  models: ModelInfo[];
  presets: Record<string, Record<string, ModelRouting>>;
  preset_names: string[];
  available_providers: string[];
  effective_routing: ModelRouting;
  user_routing: ModelRouting | null;
  deployment_routing: ModelRouting;
}

export interface RoutingResponse {
  routing: ModelRouting | null;
  effective_routing: ModelRouting;
}

/** One model installed on the user's local Ollama server (docs/12 M15). */
export interface LocalModelInfo {
  name: string;
  size_bytes: number | null;
  /** The "provider:model" route to select this model in the picker. */
  route: string | null;
  in_catalog: boolean;
  /** Name suggests a parameter count the research pipeline handles poorly. */
  likely_underpowered: boolean;
  /** Embedding model — powers retrieval, cannot fill an agent role. */
  is_embedding: boolean;
  /** Parameter count in billions, when the tag states one. */
  params_b: number | null;
}

/**
 * "Not detected" used to conflate two states with different fixes (docs/07 §2, Phase
 * 2b): `not_installed` needs the installer link, `installed_not_running` needs the
 * one-click Start button.
 */
export type LocalLLMInstallState = "running" | "installed_not_running" | "not_installed";

export interface LocalLLMStatus {
  configured_base_url: string;
  reachable: boolean;
  /** Reachable AND has at least one model. */
  usable: boolean;
  models: LocalModelInfo[];
  error: string | null;
  hint: string | null;
  install_state: LocalLLMInstallState;
}

/** One line of Ollama's streaming pull response (docs/07 §2, Phase 2b). */
export interface PullProgress {
  status: string;
  completed: number | null;
  total: number | null;
  error: string | null;
}

/**
 * The research design gate (docs/07 §2, Phase 4). Mirrors
 * `backend/app/schemas/research.py::PlanTaskSchema` — the reviewer-facing shape of a
 * research task, which is deliberately not the engine's `ResearchTask`: run state like
 * `status` never crosses to the client, and `include` never crosses back into the graph.
 */
export interface PlanTask {
  id: number;
  query: string;
  rationale: string;
  subtopics: string[];
  /** False drops this task from the run. The gate filters on it before the executor. */
  include: boolean;
  source_hint: string | null;
}

export interface OutlineSection {
  title: string;
  description: string;
}

export interface SessionPlan {
  session_id: string;
  status: SessionStatus;
  tasks: PlanTask[];
  outline: OutlineSection[];
  /** Null while still AWAITING_PLAN — the reviewer has not decided yet. */
  approved_at: string | null;
}

/**
 * One report structure offered at the gate, served by `GET /research/outline-templates`.
 * The sections come from `research_engine/outlines.py` rather than being duplicated
 * here, so what the picker previews is what the synthesizer is actually handed.
 */
export interface OutlineTemplate {
  id: string;
  label: string;
  summary: string;
  sections: OutlineSection[];
}

/* ── V2 run graph ──────────────────────────────────────────────────────────────
 *
 * The contract served by `GET /v2/runs/{id}` on both hosts. Written now, ahead of the UI
 * milestone, because the shapes are the part that is expensive to change once nine
 * surfaces read them.
 *
 * Every three-valued vocabulary is a union of literals rather than a boolean. That is the
 * whole point: a reader must be able to tell "we checked and it failed" from "we never
 * checked", and a `verified: boolean` would make the product's central claim unrepresentable
 * in its own types.
 */

/** `UNCHECKED` is not `UNATTESTED`. Never collapse these. */
export type ProvenanceState = 'ATTESTED' | 'UNATTESTED' | 'UNCHECKED';
export type AttestationGrade = 'FETCHED_BODY' | 'SEARCH_SNIPPET' | 'CORPUS_DOCUMENT';
export type ClaimVerificationState =
  | 'SUPPORTED'
  | 'UNSUPPORTED'
  | 'INSUFFICIENT_EVIDENCE'
  | 'UNCHECKED';
/** `NOT_RUN` and `DETECTOR_UNAVAILABLE` are different findings from "none found". */
export type ContradictionDetectionState = 'DETECTED' | 'NOT_RUN' | 'DETECTOR_UNAVAILABLE';
export type ReviewGate = 'PLAN' | 'REPORT';
export type ReviewDecision = 'APPROVED' | 'REWORK_REQUESTED' | 'REJECTED';
export type RunStatusV2 =
  | 'PENDING'
  | 'RUNNING'
  | 'AWAITING_PLAN'
  | 'AWAITING_REVIEW'
  | 'COMPLETED'
  | 'FAILED'
  | 'CANCELLED';

export interface V2Run {
  id: string;
  project_id: string;
  question: string;
  status: RunStatusV2;
  depth: string;
  corpus_mode: boolean;
  demo: boolean;
  skip_plan_gate: boolean;
  model_routing: Record<string, string> | null;
  cost_usd: number;
  tokens_input: number;
  tokens_output: number;
  elapsed_seconds: number | null;
  /** Null means UNMEASURED. Rendering it as 0 is the bug this field exists to prevent. */
  citation_resolution_rate: number | null;
  error_message: string | null;
  cancelled_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface V2Plan {
  id: string;
  version: number;
  tasks: PlanTask[];
  outline_sections: unknown[];
  /** `UNKNOWN` appears only on plans migrated from V1, which could not tell the model's
   *  proposal from a human's edit. A native run always knows. */
  origin: 'MODEL_PROPOSED' | 'HUMAN_EDITED' | 'TEMPLATE' | 'UNKNOWN';
  approved_at: string | null;
}

export interface V2Source {
  id: string;
  url: string;
  title: string | null;
  kind: 'WEB' | 'CORPUS';
  retrieval_status: string;
  /** Null means retrieved but never cited. Do not number it. */
  citation_index: number | null;
  corpus_document_id: string | null;
}

export interface V2Evidence {
  id: string;
  source_id: string;
  sequence: number;
  task_id: string | null;
  snippet: string;
  content_hash: string;
  key_fact: string | null;
  provenance_state: ProvenanceState;
  attested_against: AttestationGrade | null;
  attestation_run_at: string | null;
}

export interface V2Revision {
  id: string;
  version: number;
  report_markdown: string;
  report_hash: string;
  /** The last evidence sequence visible at synthesis. A threshold, not a count. */
  evidence_watermark: number;
  created_at: string;
}

export interface V2Claim {
  id: string;
  revision_id: string;
  position: number;
  text: string;
  extraction_method: 'DERIVED_FROM_REPORT' | 'MODEL_STRUCTURED' | 'HUMAN_EDITED';
  verification_state: ClaimVerificationState;
  verification_method: 'NUMERIC_GROUNDING' | 'MODEL_JUDGE' | 'NOT_RUN';
  /** Reserved and always null today: nothing has observed claim identity across revisions. */
  lineage_id: string | null;
}

export interface V2ClaimEvidenceLink {
  id: string;
  claim_id: string;
  evidence_id: string;
  stance: 'SUPPORTS' | 'CONTRADICTS' | 'CONTEXT';
  origin: 'CITATION_MARKER' | 'MODEL_ASSERTED' | 'HUMAN_ASSERTED';
}

/**
 * A conflict between two ATTRIBUTED QUOTATIONS. The source anchors are what the detector
 * observed; the evidence anchors are a refinement and are often null, because a quotation
 * that matches two evidence rows must not be resolved to one of them.
 */
export interface V2Contradiction {
  id: string;
  source_a_id: string | null;
  source_b_id: string | null;
  evidence_a_id: string | null;
  evidence_b_id: string | null;
  quote_a: string | null;
  quote_b: string | null;
  summary_a: string | null;
  summary_b: string | null;
  nature: string | null;
  dimension: string | null;
  detection_state: ContradictionDetectionState;
  review_state: 'UNREVIEWED' | 'ACKNOWLEDGED' | 'DISMISSED';
}

export interface V2Review {
  id: string;
  /** Explicit position within the run. Do not sort by `created_at`. */
  sequence: number;
  gate: ReviewGate;
  decision: ReviewDecision;
  /** Null for a PLAN review — its subject is the plan version. */
  revision_id: string | null;
  plan_version_id: string | null;
  feedback: string | null;
  reviewed_hash: string;
  created_at: string;
}

export interface V2Artifact {
  id: string;
  artifact_hash: string;
  format_version: number;
  review_id: string | null;
  /** Always `REPORT`: a plan approval cannot authorize an artifact. */
  review_gate: ReviewGate;
  review_decision: ReviewDecision;
  revision_id: string | null;
  demo: boolean;
  created_at: string;
}

/** The whole graph, as one response. See `app/api/v1/v2_runs.py` for why it is aggregate. */
export interface V2RunGraph {
  run: V2Run;
  plans: V2Plan[];
  sources: V2Source[];
  evidence: V2Evidence[];
  revisions: V2Revision[];
  claims: V2Claim[];
  claim_evidence_links: V2ClaimEvidenceLink[];
  contradictions: V2Contradiction[];
  reviews: V2Review[];
  artifact: V2Artifact | null;
}

/**
 * `GET /v2/runs/{id}/verification` — every check the standalone verifier ran.
 *
 * `assembled: false` means the verifier was NOT run, and `passed` is then null. That is not
 * the same as a failure, and a UI must not render it as one.
 */
export interface V2Verification {
  assembled: boolean;
  reason: string | null;
  passed: boolean | null;
  bundle_hash?: string;
  frozen?: boolean;
  checks: { name: string; passed: boolean; detail: string | null }[];
}

/** One row of `GET /v2/runs` — the History list. */
export interface V2RunSummary {
  id: string;
  project_id: string;
  question: string;
  status: RunStatusV2;
  depth: string;
  demo: boolean;
  cost_usd: number;
  citation_resolution_rate: number | null;
  has_artifact: boolean;
  created_at: string;
}
