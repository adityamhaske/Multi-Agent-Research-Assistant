"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ApiError, apiFetch } from "@/lib/api";
import type {
  ChatMessage,
  ResearchDepth,
  ResearchStartResponse,
  SessionDetail,
  SessionListResponse,
  User,
} from "@/lib/types";

/**
 * TanStack Query owns every read/mutation (docs/03, docs/07 §7). SSE handlers write
 * directly into this cache (see hooks/useSessionStream) rather than keeping a parallel
 * hand-rolled state machine.
 */
export const queryKeys = {
  me: ["me"] as const,
  sessions: (page: number) => ["sessions", page] as const,
  session: (id: string) => ["session", id] as const,
  chat: (id: string) => ["chat", id] as const,
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

export function useSession(id: string, opts?: { refetchInterval?: number | false }) {
  return useQuery({
    queryKey: queryKeys.session(id),
    queryFn: () => apiFetch<SessionDetail>(`/research/${id}`),
    refetchInterval: opts?.refetchInterval ?? false,
    enabled: Boolean(id),
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
