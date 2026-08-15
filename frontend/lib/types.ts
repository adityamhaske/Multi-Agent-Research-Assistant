/**
 * Shared types mirroring the backend contracts (backend/app/schemas/*, models/session.py).
 * Kept in sync by hand — the OpenAPI schema is the source of truth if these drift.
 */

export type SessionStatus =
  | "PENDING"
  | "RUNNING"
  | "AWAITING_APPROVAL"
  | "COMPLETED"
  | "FAILED";

export type ResearchDepth = "fast" | "balanced" | "comprehensive";

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
}

export interface ProfileUpdate {
  display_name?: string | null;
  avatar_url?: string | null;
  monthly_token_limit?: number;
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
  type: "connected" | "agent_log" | "HITL_READY" | "COMPLETED" | "FAILED" | string;
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

export interface LocalLLMStatus {
  configured_base_url: string;
  reachable: boolean;
  /** Reachable AND has at least one model. */
  usable: boolean;
  models: LocalModelInfo[];
  error: string | null;
  hint: string | null;
}
