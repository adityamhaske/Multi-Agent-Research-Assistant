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

export type ApiKeyProvider = "google" | "anthropic" | "openai";

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
  snippet: string;
}

export interface SessionSummary {
  session_id: string;
  status: SessionStatus;
  prompt: string;
  research_depth: string;
  total_cost_usd: number;
  total_tokens_input: number;
  total_tokens_output: number;
  elapsed_seconds: number | null;
  rework_count: number;
  created_at: string;
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
  session_id: string;
  role: "user" | "assistant";
  content: string;
  created_at: string;
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
