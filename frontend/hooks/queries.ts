"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ApiError, apiFetch } from "@/lib/api";
import type {
  ApiKeyProvider,
  ChatMessage,
  ModelCatalog,
  ModelRouting,
  ProfileUpdate,
  ResearchDepth,
  ResearchStartResponse,
  RoutingResponse,
  SessionDetail,
  SessionListResponse,
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
  sessions: (page: number) => ["sessions", page] as const,
  session: (id: string) => ["session", id] as const,
  chat: (id: string) => ["chat", id] as const,
  models: ["models"] as const,
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
    mutationFn: (body: { provider: ApiKeyProvider; api_key: string }) =>
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

// ─── Research sessions ─────────────────────────────────────────────────────────────

export function useSessions(page = 1, limit = 20) {
  return useQuery({
    queryKey: queryKeys.sessions(page),
    queryFn: () => apiFetch<SessionListResponse>(`/research?page=${page}&limit=${limit}`),
  });
}

export function useSession(id: string) {
  return useQuery({
    queryKey: queryKeys.session(id),
    queryFn: () => apiFetch<SessionDetail>(`/research/${id}`),
    enabled: Boolean(id),
    // Poll only while a run is in flight. SSE is the fast path for live events;
    // this guarantees the page still converges if a terminal event is ever missed
    // (dropped stream, proxy hiccup) instead of hanging on the monitor forever.
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === "PENDING" || status === "RUNNING" ? 5000 : false;
    },
  });
}

export function useStartResearch() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { query: string; depth: ResearchDepth }) =>
      apiFetch<ResearchStartResponse>("/research", { method: "POST", body }),
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
