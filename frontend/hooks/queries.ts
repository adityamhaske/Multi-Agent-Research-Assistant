"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ApiError, apiFetch } from "@/lib/api";
import { apiBase, authHeaders, isDesktop } from "@/lib/desktop";
import type {
  ApiKeyProvider,
  ChatMessage,
  ChatThread,
  DesktopKeys,
  LocalLLMStatus,
  MemoryStatus,
  ModelCatalog,
  ModelRouting,
  Project,
  ProjectListResponse,
  ProfileUpdate,
  ResearchDepth,
  ResearchStartResponse,
  RoutingResponse,
  SessionDetail,
  SessionListResponse,
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
    }) => apiFetch<ResearchStartResponse>("/research", { method: "POST", body }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["sessions"] }),
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
 * Live probe of the local model server (docs/12 M15). Kept out of `useModelCatalog`
 * because it does real network I/O and can legitimately time out — the catalog must
 * stay instant. Not retried: "nothing is running" is an answer, not a failure.
 */
export function useLocalLLMStatus() {
  return useQuery({
    queryKey: queryKeys.localLLM,
    queryFn: () => apiFetch<LocalLLMStatus>("/models/local/status"),
    retry: false,
    staleTime: 15_000,
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
}

export interface CorpusStatus {
  documents: number;
  chunks: number;
  chunks_by_model: Record<string, number>;
  current_model: string;
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
