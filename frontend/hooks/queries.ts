"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ApiError, apiFetch } from "@/lib/api";
import { apiBase, authHeaders, isDesktop } from "@/lib/desktop";
import type {
  ApiKeyProvider,
  ChatMessage,
  ChatThread,
  ConnectionVerdict,
  CustomEndpointStatus,
  DesktopKeys,
  LocalLLMStatus,
  MemoryStatus,
  ModelCatalog,
  ModelRouting,
  OutlineSection,
  OutlineTemplate,
  PlanTask,
  Project,
  ProjectListResponse,
  ProfileUpdate,
  PullProgress,
  ResearchDepth,
  ResearchStartResponse,
  RoutingResponse,
  SessionDetail,
  SessionListResponse,
  SessionPlan,
  SessionSummary,
  ThreadListResponse,
  ThreadMessage,
  Usage,
  User,
} from "@/lib/types";

/**
 * TanStack Query owns every read/mutation (docs/03, docs/07 §7). SSE handlers write
 * directly into this cache (see hooks/useSessionStream) rather than keeping a parallel
 * hand-rolled state machine.
 */
export const queryKeys = {
  me: ["me"] as const,
  usage: ["usage"] as const,
  projects: (archived = false) => ["projects", archived] as const,
  sessions: (page: number, archived = false, projectId?: string | null) =>
    ["sessions", page, archived, projectId ?? null] as const,
  session: (id: string) => ["session", id] as const,
  plan: (id: string) => ["plan", id] as const,
  outlineTemplates: ["outline-templates"] as const,
  chat: (id: string) => ["chat", id] as const,
  threads: (projectId: string) => ["threads", projectId] as const,
  threadMessages: (threadId: string) => ["thread-messages", threadId] as const,
  memoryStatus: (projectId: string) => ["memory-status", projectId] as const,
  models: ["models"] as const,
  desktopKeys: ["desktop-keys"] as const,
  localLLM: ["local-llm-status"] as const,
};

// ─── Auth ────────────────────────────────────────────────────────────────────────

export function useMe() {
  return useQuery({
    queryKey: queryKeys.me,
    queryFn: () => apiFetch<User>("/auth/me"),
    // A 401 here means "not logged in" — don't spin retrying it.
    retry: (count, err) => !(err instanceof ApiError && err.status === 401) && count < 1,
    staleTime: 60_000,
  });
}

export function useLogin() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { email: string; password: string }) =>
      apiFetch<{ message: string }>("/auth/login", { method: "POST", body }),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.me }),
  });
}

export function useRegister() {
  return useMutation({
    mutationFn: (body: { email: string; password: string }) =>
      apiFetch<{ message: string }>("/auth/register", { method: "POST", body }),
  });
}

export function useUpdateProfile() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: ProfileUpdate) =>
      apiFetch<User>("/auth/me", { method: "PATCH", body }),
    onSuccess: (user) => qc.setQueryData(queryKeys.me, user),
  });
}

/**
 * Change the account password. The server revokes every other refresh token and
 * re-issues this device's cookies, so the caller stays signed in.
 */
export function useChangePassword() {
  return useMutation({
    mutationFn: (body: { current_password: string; new_password: string }) =>
      apiFetch<{ message: string }>("/auth/me/password", { method: "POST", body }),
  });
}

/** Store a BYOK provider key. The key is sent once and never returned. */
export function useSetApiKey() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { provider: ApiKeyProvider; api_key: string; api_base_url?: string }) =>
      apiFetch<User>("/auth/me/api-key", { method: "PUT", body }),
    onSuccess: (user) => qc.setQueryData(queryKeys.me, user),
  });
}

export function useDeleteApiKey() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => apiFetch<User>("/auth/me/api-key", { method: "DELETE" }),
    onSuccess: (user) => qc.setQueryData(queryKeys.me, user),
  });
}

/**
 * Nickname the active BYOK connection ("OmniRoute", "Work vLLM"). Deliberately
 * separate from `useSetApiKey` — a nickname does not require re-pasting the key, and
 * unlike saving, this never re-probes the provider (`PATCH /me/api-key/label`).
 */
export function useSetApiKeyLabel() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (label: string) =>
      apiFetch<User>("/auth/me/api-key/label", { method: "PATCH", body: { label } }),
    onSuccess: (user) => qc.setQueryData(queryKeys.me, user),
  });
}

/**
 * Probe a key BEFORE it is stored (docs/07 §2, Phase 2a) — the picker's "test
 * connection" action, separate from saving. Same request/response shape on both
 * hosts: `POST /models/providers/test`.
 */
export function useTestProviderKey() {
  return useMutation({
    mutationFn: (body: { provider: ApiKeyProvider; api_key: string; api_base_url?: string }) =>
      apiFetch<ConnectionVerdict>("/models/providers/test", { method: "POST", body }),
  });
}

/**
 * Re-probe a stored key on demand. The web host checks the current user's single BYOK
 * key (`GET /models/providers/health`); desktop can hold a key per provider at once,
 * so it is scoped by provider (`GET /models/providers/health/{provider}`). 404s when
 * nothing is stored — the caller should only enable this once a key exists.
 */
export function useProviderHealth(provider: ApiKeyProvider | null, enabled: boolean) {
  return useQuery({
    queryKey: ["provider-health", provider],
    queryFn: () =>
      apiFetch<ConnectionVerdict>(
        isDesktop ? `/models/providers/health/${provider}` : "/models/providers/health",
      ),
    enabled: enabled && !!provider,
    retry: false,
    staleTime: 30_000,
  });
}

export function useUsage() {
  return useQuery({
    queryKey: queryKeys.usage,
    queryFn: () => apiFetch<Usage>("/auth/me/usage"),
    staleTime: 15_000,
  });
}

export function useLogout() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => apiFetch<{ message: string }>("/auth/logout", { method: "POST" }),
    onSettled: () => qc.clear(),
  });
}

// ─── Desktop keys (OS keychain, docs/12 M9) ──────────────────────────────────────
//
// The desktop sidecar stores each provider's key in the OS keychain and only ever
// returns hints. Mutations invalidate the catalog too, since model availability is
// judged by which providers have a key.

export function useDesktopKeys() {
  return useQuery({
    queryKey: queryKeys.desktopKeys,
    queryFn: () => apiFetch<DesktopKeys>("/desktop/keys"),
  });
}

export function useSetDesktopKey() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ provider, key }: { provider: ApiKeyProvider; key: string }) =>
      apiFetch<void>(`/desktop/keys/${provider}`, { method: "PUT", body: { key } }),
    onSettled: () => {
      qc.invalidateQueries({ queryKey: queryKeys.desktopKeys });
      qc.invalidateQueries({ queryKey: queryKeys.models });
    },
  });
}

export function useDeleteDesktopKey() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (provider: ApiKeyProvider) =>
      apiFetch<void>(`/desktop/keys/${provider}`, { method: "DELETE" }),
    onSettled: () => {
      qc.invalidateQueries({ queryKey: queryKeys.desktopKeys });
      qc.invalidateQueries({ queryKey: queryKeys.models });
    },
  });
}

export function useDesktopCustomEndpoint() {
  return useQuery({
    queryKey: [...queryKeys.desktopKeys, "custom_endpoint"],
    queryFn: () => apiFetch<{ base_url: string | null }>("/desktop/keys/custom_endpoint"),
  });
}

export function useSetDesktopCustomEndpoint() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (base_url: string) =>
      apiFetch<void>("/desktop/keys/custom_endpoint", { method: "PUT", body: { base_url } }),
    onSettled: () => {
      qc.invalidateQueries({ queryKey: [...queryKeys.desktopKeys, "custom_endpoint"] });
      qc.invalidateQueries({ queryKey: queryKeys.models });
    },
  });
}

// ─── Research sessions ─────────────────────────────────────────────────────────────

export function useSessions(page = 1, limit = 20, archived = false, projectId?: string | null) {
  return useQuery({
    queryKey: queryKeys.sessions(page, archived, projectId),
    queryFn: () => {
      const scope = projectId ? `&project_id=${projectId}` : "";
      return apiFetch<SessionListResponse>(
        `/research?page=${page}&limit=${limit}&archived=${archived}${scope}`
      );
    },
    // Don't fetch an unscoped list while the active project is still loading — it
    // would flash every project's sessions before snapping to the right ones.
    enabled: projectId !== undefined,
  });
}

// ─── Projects (docs/14) ────────────────────────────────────────────────────────────

export function useProjects(archived = false) {
  return useQuery({
    queryKey: queryKeys.projects(archived),
    queryFn: () => apiFetch<ProjectListResponse>(`/projects?archived=${archived}`),
    staleTime: 30_000,
  });
}

export function useCreateProject() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { name: string; description?: string | null }) =>
      apiFetch<Project>("/projects", { method: "POST", body }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["projects"] }),
  });
}

export function useUpdateProject() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...body }: { id: string; name?: string; description?: string | null; archived?: boolean }) =>
      apiFetch<Project>(`/projects/${id}`, { method: "PATCH", body }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["projects"] }),
  });
}

/** Deleting a project deletes the research inside it — the UI must confirm first. */
export function useDeleteProject() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => apiFetch<void>(`/projects/${id}`, { method: "DELETE" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["projects"] });
      qc.invalidateQueries({ queryKey: ["sessions"] });
    },
  });
}

/**
 * Archive / unarchive / delete. All three invalidate every session list because a row
 * moves between the active and archived views (or disappears), and the counts on both
 * sides change — invalidating only the current page would leave the other list stale.
 */
export function useArchiveSession() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, archived }: { id: string; archived: boolean }) =>
      apiFetch<SessionSummary>(`/research/${id}/${archived ? "archive" : "unarchive"}`, {
        method: "POST",
      }),
    onSuccess: (_data, { id }) => {
      qc.invalidateQueries({ queryKey: ["sessions"] });
      qc.invalidateQueries({ queryKey: queryKeys.session(id) });
    },
  });
}

export function useDeleteSession() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => apiFetch<void>(`/research/${id}`, { method: "DELETE" }),
    onSuccess: (_data, id) => {
      qc.removeQueries({ queryKey: queryKeys.session(id) });
      qc.invalidateQueries({ queryKey: ["sessions"] });
    },
  });
}

export function useCancelSession() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) =>
      apiFetch<SessionSummary>(`/research/${id}/cancel`, { method: "POST" }),
    onSuccess: (_data, id) => {
      qc.invalidateQueries({ queryKey: queryKeys.session(id) });
      qc.invalidateQueries({ queryKey: ["sessions"] });
    },
  });
}

export function useSession(id: string) {
  return useQuery({
    queryKey: queryKeys.session(id),
    queryFn: () => apiFetch<SessionDetail>(`/research/${id}`),
    enabled: Boolean(id),
    // Poll until the session reaches a terminal state. SSE is the fast path for live
    // events; this is the safety net that guarantees the page converges if a terminal
    // event is ever missed (dropped stream, proxy hiccup, or a fast resume→COMPLETED
    // that races the re-subscribe). Polling through AWAITING_APPROVAL — not stopping at
    // it — means the interval is never torn down mid-run, so approve→finalize is always
    // caught even without SSE. Stops only on COMPLETED/FAILED (or before the first load).
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      if (!status) return false;
      return status === "COMPLETED" || status === "FAILED" ? false : 5000;
    },
    // The safety net must fire even when the tab is backgrounded — otherwise a run
    // that finishes while the user is on another tab is never reflected until they
    // refocus. (Default is to pause interval polling when hidden.)
    refetchIntervalInBackground: true,
  });
}

export function useStartResearch() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: {
      query: string;
      depth: ResearchDepth;
      /** Which project the research belongs to. Omit to use the default project. */
      project_id: string | null;
      model_routing?: Record<string, string> | null;
      corpus_mode?: boolean;
      /** Run on scripted models and fixture sources — no provider, no key (docs/17 §6.2). */
      demo?: boolean;
      /**
       * Research design gate (docs/07 §2, Phase 4). The API defaults this to `true`
       * (skip) so an un-updated caller keeps today's journey; the run form therefore
       * has to send `false` to *get* the gate, which is the product default here.
       */
      skip_plan_gate?: boolean;
      topic_seeds?: string[];
      outline_template?: string | null;
    }) => apiFetch<ResearchStartResponse>("/research", { method: "POST", body }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["sessions"] }),
  });
}

// ─── Research design gate (docs/07 §2, Phase 4) ───────────────────────────────────

export function useSessionPlan(id: string, enabled = true) {
  return useQuery({
    queryKey: queryKeys.plan(id),
    queryFn: () => apiFetch<SessionPlan>(`/research/${id}/plan`),
    enabled: enabled && Boolean(id),
    // A run that skipped the gate 404s here by design — that is an answer, not a
    // transient failure, so retrying it just delays the empty state.
    retry: false,
    staleTime: Infinity,
  });
}

export function useSubmitPlan(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { tasks?: PlanTask[] | null; outline?: OutlineSection[] | null }) =>
      apiFetch<SessionPlan>(`/research/${id}/plan`, { method: "POST", body }),
    onSuccess: (plan) => {
      qc.setQueryData(queryKeys.plan(id), plan);
      qc.invalidateQueries({ queryKey: queryKeys.session(id) });
    },
  });
}

export function useOutlineTemplates(enabled = true) {
  return useQuery({
    queryKey: queryKeys.outlineTemplates,
    queryFn: () => apiFetch<OutlineTemplate[]>("/research/outline-templates"),
    enabled,
    // Static engine data — it changes when the app is redeployed, not while it is open.
    staleTime: Infinity,
  });
}

export function useApprove(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { approved: boolean; feedback?: string | null }) =>
      apiFetch<{ message: string }>(`/research/${id}/approve`, { method: "POST", body }),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.session(id) }),
  });
}

// ─── Chat ──────────────────────────────────────────────────────────────────────────

export function useChatHistory(id: string, enabled = true) {
  return useQuery({
    queryKey: queryKeys.chat(id),
    queryFn: () => apiFetch<ChatMessage[]>(`/research/${id}/chat`),
    enabled: enabled && Boolean(id),
    staleTime: Infinity,
  });
}

// ─── Project chat threads & memory (docs/14 §8) ──────────────────────────────────

export function useThreads(projectId: string | undefined) {
  return useQuery({
    queryKey: queryKeys.threads(projectId ?? ""),
    queryFn: () => apiFetch<ThreadListResponse>(`/projects/${projectId}/threads`),
    // Same guard as useSessions: don't fetch before the active project is known, or the
    // list flashes the wrong project's threads.
    enabled: Boolean(projectId),
  });
}

export function useCreateThread(projectId: string | undefined) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { title?: string | null }) =>
      apiFetch<ChatThread>(`/projects/${projectId}/threads`, { method: "POST", body }),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.threads(projectId ?? "") }),
  });
}

export function useDeleteThread(projectId: string | undefined) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (threadId: string) =>
      apiFetch<void>(`/threads/${threadId}`, { method: "DELETE" }),
    onSuccess: (_data, threadId) => {
      qc.removeQueries({ queryKey: queryKeys.threadMessages(threadId) });
      qc.invalidateQueries({ queryKey: queryKeys.threads(projectId ?? "") });
    },
  });
}

export function useThreadMessages(threadId: string | undefined) {
  return useQuery({
    queryKey: queryKeys.threadMessages(threadId ?? ""),
    queryFn: () => apiFetch<ThreadMessage[]>(`/threads/${threadId}/messages`),
    enabled: Boolean(threadId),
    staleTime: Infinity,
  });
}

/**
 * Whether this project's memory is usable, and how complete it is.
 *
 * Not retried: "no embedding provider configured" is an answer the UI must show, not a
 * failure worth spinning on — the same reasoning as the local-LLM probe above.
 */
export function useMemoryStatus(projectId: string | undefined) {
  return useQuery({
    queryKey: queryKeys.memoryStatus(projectId ?? ""),
    queryFn: () => apiFetch<MemoryStatus>(`/projects/${projectId}/memory/status`),
    enabled: Boolean(projectId),
    retry: false,
    staleTime: 30_000,
  });
}

// ─── Models (docs/12 M8) ─────────────────────────────────────────────────────────

/**
 * The catalog rarely changes within a session, but a user adding an API key flips
 * `available` on a whole provider — so it's invalidated by the key mutations rather
 * than polled.
 */
export function useModelCatalog() {
  return useQuery({
    queryKey: queryKeys.models,
    queryFn: () => apiFetch<ModelCatalog>("/models"),
    staleTime: 60_000,
  });
}

/**
 * Live probe of the configured custom OpenAI-compatible endpoint.
 *
 * Split from `useModelCatalog` for the reason `useLocalLLMStatus` is: real network I/O
 * against an address that can legitimately be down, while the catalog must stay instant.
 * `enabled` is off until something actually needs the list — a gateway can advertise
 * thousands of ids, and there is no reason to fetch them for a form nobody has opened.
 */
export function useCustomEndpointStatus(enabled = true) {
  return useQuery({
    queryKey: [...queryKeys.models, "custom-endpoint"] as const,
    queryFn: () => apiFetch<CustomEndpointStatus>("/models/custom/status"),
    enabled,
    retry: false, // "nothing answered there" is an answer, not a failure
    staleTime: 30_000,
  });
}

/**
 * Live probe of the local model server (docs/12 M15). Kept out of `useModelCatalog`
 * because it does real network I/O and can legitimately time out — the catalog must
 * stay instant. Not retried: "nothing is running" is an answer, not a failure.
 */
export function useLocalLLMStatus(pollUntilReady = false) {
  return useQuery({
    queryKey: queryKeys.localLLM,
    queryFn: () => apiFetch<LocalLLMStatus>("/models/local/status"),
    retry: false,
    staleTime: 15_000,
    // "2s polling that flips to green the moment the server appears" (docs/07 §2,
    // Phase 2b) — only while opted in and not yet reachable; a card idly showing
    // "Connected" has no reason to keep polling every 2 seconds forever.
    refetchInterval: pollUntilReady
      ? (query) => (query.state.data?.install_state === "running" ? false : 2000)
      : undefined,
  });
}

/**
 * One-click local server (docs/07 §2, Phase 2b) — desktop only. The web build has no
 * counterpart: it cannot spawn a process on the user's machine, so `LocalLLMCard`
 * shows an OS-detected command to copy instead of a button that calls this.
 */
export function useStartLocalServer() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => apiFetch<{ started?: boolean; already_running?: boolean }>(
      "/models/local/start",
      { method: "POST" },
    ),
    onSettled: () => qc.invalidateQueries({ queryKey: queryKeys.localLLM }),
  });
}

export function useStopLocalServer() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () =>
      apiFetch<{ stopped: boolean }>("/models/local/stop", { method: "POST" }),
    onSettled: () => qc.invalidateQueries({ queryKey: queryKeys.localLLM }),
  });
}

/**
 * Pull a model with streaming progress (docs/07 §2, Phase 2b). Works on both hosts —
 * pulling is one HTTP call to an already-running Ollama, no local process access
 * needed, unlike starting the server. Newline-delimited JSON, not `EventSource`
 * (this is a POST with a body); read as a plain fetch stream instead.
 */
export async function pullLocalModel(
  model: string,
  onProgress: (p: PullProgress) => void,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch(`${apiBase()}/models/local/pull`, {
    method: "POST",
    credentials: isDesktop ? "omit" : "include",
    headers: { ...authHeaders(), "Content-Type": "application/json" },
    body: JSON.stringify({ model }),
    signal,
  });
  if (!res.ok || !res.body) {
    throw new ApiError(res.status, await res.text().catch(() => "Pull failed."));
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";
    for (const line of lines) {
      if (!line.trim()) continue;
      try {
        onProgress(JSON.parse(line) as PullProgress);
      } catch {
        // A stray non-JSON line is not fatal — skip it.
      }
    }
  }
}

/**
 * The saved per-role routing, and the routing that would actually be dialled.
 * `routing` is null when the user has never chosen one — the deployment default applies,
 * and `effective_routing` is what that resolves to. Read-only counterpart to the two
 * mutations below.
 */
export function useModelRouting() {
  return useQuery({
    queryKey: [...queryKeys.models, "routing"] as const,
    queryFn: () => apiFetch<RoutingResponse>("/models/routing"),
    staleTime: 60_000,
  });
}

export function useSetModelRouting() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (routing: ModelRouting) =>
      apiFetch<RoutingResponse>("/models/routing", { method: "PUT", body: { routing } }),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.models }),
  });
}

export function useResetModelRouting() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => apiFetch<RoutingResponse>("/models/routing", { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.models }),
  });
}

// ─── Corpus ────────────────────────────────────────────────────────────────────

export interface CorpusDocument {
  id: string;
  filename: string;
  chunks: number;
  created_at?: string;
  size_bytes?: number | null;
  /** False for documents ingested before originals were retained — no file to open. */
  downloadable?: boolean;
}

/** Same-origin URL for the stored original (docs/06 §6 — never a hardcoded backend host). */
export function corpusDownloadUrl(projectId: string, docId: string): string {
  return `${apiBase()}/projects/${projectId}/corpus/documents/${docId}/download`;
}

export interface CorpusStatus {
  documents: number;
  chunks: number;
  chunks_by_model: Record<string, number>;
  current_model: string;
}

export interface Readiness {
  /** Whether research can run at all right now — a key, or a local server with a chat model. */
  ready: boolean;
  has_cloud_key: boolean;
  local_reachable: boolean;
  local_chat_models: number;
}

/**
 * Can this user run research right now? (docs/17 §8a)
 *
 * Computed server-side on every request rather than stored, so it can never disagree with
 * reality: it stops being false the moment a key is added or Ollama starts, and it is not
 * a "has seen onboarding" flag that outlives the condition it described.
 */
export function useReadiness() {
  return useQuery({
    queryKey: ["readiness"],
    queryFn: () => apiFetch<Readiness>("/models/readiness"),
    // Cheap and worth being current: the answer changes the moment the user adds a key
    // in another tab or starts Ollama, and a stale "not ready" is a false accusation.
    staleTime: 30_000,
  });
}

export function useCorpusDocuments(projectId?: string | null) {
  return useQuery({
    queryKey: ["corpus", projectId, "documents"],
    queryFn: () => {
      if (!projectId) return Promise.resolve([]);
      return apiFetch<CorpusDocument[]>(`/projects/${projectId}/corpus/documents`);
    },
    enabled: !!projectId,
  });
}

export function useCorpusStatus(projectId?: string | null) {
  return useQuery({
    queryKey: ["corpus", projectId, "status"],
    queryFn: () => {
      if (!projectId) return Promise.reject(new Error("No active project"));
      return apiFetch<CorpusStatus>(`/projects/${projectId}/corpus/status`);
    },
    enabled: !!projectId,
  });
}


export function useUploadDocument() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ projectId, file }: { projectId: string; file: File }) => {
      const form = new FormData();
      form.append("file", file);
      
      const res = await fetch(`${apiBase()}/projects/${projectId}/corpus/documents`, {
        method: "POST",
        credentials: isDesktop ? "omit" : "include",
        headers: {
          ...authHeaders(),
        },
        body: form,
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new ApiError(res.status, err.detail || "Upload failed");
      }
      return res.json() as Promise<CorpusDocument>;
    },
    onSuccess: (_, { projectId }) => {
      qc.invalidateQueries({ queryKey: ["corpus", projectId] });
    },
  });
}

export function useDeleteDocument() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ projectId, docId }: { projectId: string; docId: string }) =>
      apiFetch<void>(`/projects/${projectId}/corpus/documents/${docId}`, { method: "DELETE" }),
    onSuccess: (_, { projectId }) => {
      qc.invalidateQueries({ queryKey: ["corpus", projectId] });
    },
  });
}
