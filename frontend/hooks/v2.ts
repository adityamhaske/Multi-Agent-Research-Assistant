"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { apiFetch } from "@/lib/api";
import { isDesktop, streamUrl } from "@/lib/desktop";
import type { AgentEvent, V2RunGraph, V2RunSummary, V2Verification } from "@/lib/types";

/**
 * Data access for the V2 research workspace.
 *
 * One aggregate query per run, matching the one aggregate endpoint: every surface —
 * Evidence, Claims, Sources, Contradictions, Report, Review, Artifact — reads a slice of
 * the same `V2RunGraph`, so switching tabs costs nothing and no two tabs can disagree about
 * the run they are describing.
 *
 * Verification is a **separate** query on purpose. It runs the standalone verifier, which is
 * a different question from "what does this run contain", and folding it into the graph
 * would make every tab switch re-verify a bundle.
 */

/** Statuses where the server still has something to say. */
export function isLive(status?: string | null): boolean {
  return status === "PENDING" || status === "RUNNING";
}

export const v2Keys = {
  runs: (projectId?: string | null) => ["v2-runs", projectId ?? null] as const,
  run: (id: string) => ["v2-run", id] as const,
  verification: (id: string) => ["v2-verification", id] as const,
};

export function useV2Runs(projectId?: string | null) {
  return useQuery({
    queryKey: v2Keys.runs(projectId),
    queryFn: () =>
      apiFetch<{ runs: V2RunSummary[] }>(
        `/v2/runs${projectId ? `?project_id=${encodeURIComponent(projectId)}` : ""}`,
      ),
    select: (d) => d.runs,
  });
}

export function useV2Run(runId: string | null) {
  return useQuery({
    queryKey: v2Keys.run(runId ?? ""),
    queryFn: () => apiFetch<V2RunGraph>(`/v2/runs/${runId}`),
    enabled: Boolean(runId),
    // Fallback polling while the run is live. The event stream is the primary channel and
    // stays so — this only covers the window where it is not delivering: a connection that
    // never opened, one dropped before the browser's own reconnect, or a run that finished
    // between the refetch and the subscribe. Without it the workspace could sit on RUNNING
    // for a run the server had already parked at the review gate, which the plan-gate
    // journey caught. Off entirely once the run stops being live, so a finished run costs
    // no requests.
    refetchInterval: (query) =>
      isLive((query.state.data as V2RunGraph | undefined)?.run.status) ? 3_000 : false,
  });
}

export function useV2Verification(runId: string | null, enabled = true) {
  return useQuery({
    queryKey: v2Keys.verification(runId ?? ""),
    queryFn: () => apiFetch<V2Verification>(`/v2/runs/${runId}/verification`),
    enabled: Boolean(runId) && enabled,
  });
}

export function useStartV2Research() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: {
      project_id: string;
      question: string;
      depth?: string;
      corpus_mode?: boolean;
      skip_plan_gate?: boolean;
    }) => apiFetch<{ run_id: string; status: string }>("/v2/runs", { method: "POST", body }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["v2-runs"] }),
  });
}

export function useV2ReportReview(runId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { decision: string; feedback?: string | null }) =>
      apiFetch<{ review_id: string; decision: string; artifact_id: string | null }>(
        `/v2/runs/${runId}/report-review`,
        { method: "POST", body },
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: v2Keys.run(runId) });
      qc.invalidateQueries({ queryKey: v2Keys.verification(runId) });
      qc.invalidateQueries({ queryKey: ["v2-runs"] });
    },
  });
}

export function useV2PlanReview(runId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { decision: string; feedback?: string | null }) =>
      apiFetch<{ review_id: string; decision: string }>(`/v2/runs/${runId}/plan-review`, {
        method: "POST",
        body,
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: v2Keys.run(runId) }),
  });
}

export function useV2Cancel(runId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () =>
      apiFetch<{ status: string; advisory: boolean; detail: string }>(
        `/v2/runs/${runId}/cancel`,
        { method: "POST" },
      ),
    onSuccess: () => qc.invalidateQueries({ queryKey: v2Keys.run(runId) }),
  });
}

/**
 * The run's live event stream.
 *
 * Native `EventSource`, so a dropped connection reconnects with `Last-Event-ID` and the
 * backend replays the durable `agent_logs` after that id — nothing is lost, and no polling
 * loop is needed to cover the gap. The same mechanism the V1 monitor uses; this is a second
 * *subscriber*, not a second event system.
 *
 * A terminal event refreshes the run graph and closes the stream, because the graph is
 * suspended at that point and holding the socket open waits on no one. `degraded` is exposed
 * so the caller can fall back to slow polling rather than pretending the stream is fine.
 */
export function useV2RunStream(runId: string, enabled: boolean, runKey?: string | null) {
  const qc = useQueryClient();
  const [events, setEvents] = useState<AgentEvent[]>([]);
  const [degraded, setDegraded] = useState(false);
  // Reset when the subscription target changes — including on a rework, which flips the
  // run back to RUNNING under the same id. State during render, per the codebase's
  // "no setState in an effect to derive state" rule; the dedupe set is rebuilt inside the
  // effect instead of during render, because a ref must not be touched while rendering.
  const subKey = enabled && runId ? `${runId}:${runKey ?? ""}` : null;
  const [prevKey, setPrevKey] = useState<string | null>(null);
  if (subKey !== prevKey) {
    setPrevKey(subKey);
    setEvents([]);
  }

  useEffect(() => {
    if (!subKey) return;
    // The backend replays the full backlog on every (re)connect, so a clean slate is
    // correct here; replayed rows are de-duped by their durable event id below.
    const seen = new Set<number>();
    const url = streamUrl(`/api/v1/v2/runs/${runId}/stream`);
    const source = new EventSource(url, isDesktop ? undefined : { withCredentials: true });

    source.onopen = () => setDegraded(false);
    source.onmessage = (message) => {
      let payload: AgentEvent;
      try {
        payload = JSON.parse(message.data) as AgentEvent;
      } catch {
        return;
      }
      const id = Number(message.lastEventId);
      if (!Number.isNaN(id) && id > 0) {
        if (seen.has(id)) return;
        seen.add(id);
      }
      setEvents((prev) => [...prev, payload]);
      if (
        payload.type === "COMPLETED" ||
        payload.type === "FAILED" ||
        payload.type === "HITL_READY" ||
        payload.type === "PLAN_READY"
      ) {
        // The authoritative row, not the event's summary of it.
        qc.invalidateQueries({ queryKey: v2Keys.run(runId) });
        qc.invalidateQueries({ queryKey: ["v2-runs"] });
        source.close();
      }
    };
    source.onerror = () => setDegraded(true);

    return () => source.close();
  }, [subKey, runId, qc]);

  return { events, degraded };
}
