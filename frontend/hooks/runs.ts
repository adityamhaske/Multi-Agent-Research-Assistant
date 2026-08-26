"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { apiFetch } from "@/lib/api";
import { isDesktop, streamUrl } from "@/lib/desktop";
import type {
  AgentEvent,
  ModelRouting,
  PlanTask,
  RunGraph,
  RunSummary,
  RunVerification,
} from "@/lib/types";

/**
 * Data access for the research workspace.
 *
 * One aggregate query per run, matching the one aggregate endpoint: every surface —
 * Evidence, Claims, Sources, Contradictions, Report, Review, Artifact — reads a slice of
 * the same `RunGraph`, so switching tabs costs nothing and no two tabs can disagree about
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
  runs: (projectId?: string | null, archived: boolean = false) =>
    ["v2-runs", projectId ?? null, archived] as const,
  run: (id: string) => ["v2-run", id] as const,
  verification: (id: string) => ["v2-verification", id] as const,
};

export function useRuns(projectId?: string | null, archived: boolean = false) {
  return useQuery({
    queryKey: v2Keys.runs(projectId, archived),
    queryFn: () => {
      const params = new URLSearchParams();
      if (projectId) params.set("project_id", projectId);
      if (archived) params.set("archived", "true");
      const qs = params.toString();
      return apiFetch<{ runs: RunSummary[] }>(`/runs${qs ? `?${qs}` : ""}`);
    },
    select: (d) => d.runs,
  });
}

export function useArchiveRun() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, archived }: { id: string; archived: boolean }) =>
      apiFetch<{ status: string; archived: boolean }>(
        `/runs/${id}/${archived ? "archive" : "unarchive"}`,
        { method: "POST" },
      ),
    onSuccess: (_data, { id }) => {
      qc.invalidateQueries({ queryKey: ["v2-runs"] });
      qc.invalidateQueries({ queryKey: v2Keys.run(id) });
    },
  });
}

export function useDeleteRun() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => apiFetch<void>(`/runs/${id}`, { method: "DELETE" }),
    onSuccess: (_data, id) => {
      qc.removeQueries({ queryKey: v2Keys.run(id) });
      qc.removeQueries({ queryKey: v2Keys.verification(id) });
      qc.invalidateQueries({ queryKey: ["v2-runs"] });
    },
  });
}


export function useRun(runId: string | null) {
  return useQuery({
    queryKey: v2Keys.run(runId ?? ""),
    queryFn: () => apiFetch<RunGraph>(`/runs/${runId}`),
    enabled: Boolean(runId),
    // Fallback polling while the run is live. The event stream is the primary channel and
    // stays so — this only covers the window where it is not delivering: a connection that
    // never opened, one dropped before the browser's own reconnect, or a run that finished
    // between the refetch and the subscribe. Without it the workspace could sit on RUNNING
    // for a run the server had already parked at the review gate, which the plan-gate
    // journey caught. Off entirely once the run stops being live, so a finished run costs
    // no requests.
    refetchInterval: (query) =>
      isLive((query.state.data as RunGraph | undefined)?.run.status) ? 3_000 : false,
  });
}

export function useV2Verification(runId: string | null, enabled = true) {
  return useQuery({
    queryKey: v2Keys.verification(runId ?? ""),
    queryFn: () => apiFetch<RunVerification>(`/runs/${runId}/verification`),
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
      /** One `provider:model` per role. Omitted entirely to use saved settings — an
       *  explicit `null` would be a routing the server then has to interpret. */
      model_routing?: ModelRouting;
    }) => apiFetch<{ run_id: string; status: string }>("/runs", { method: "POST", body }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["v2-runs"] }),
  });
}

export function useReportReview(runId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { decision: string; feedback?: string | null }) =>
      apiFetch<{ review_id: string; decision: string; artifact_id: string | null }>(
        `/runs/${runId}/report-review`,
        { method: "POST", body },
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: v2Keys.run(runId) });
      qc.invalidateQueries({ queryKey: v2Keys.verification(runId) });
      qc.invalidateQueries({ queryKey: ["v2-runs"] });
    },
  });
}

export function usePlanReview(runId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: {
      decision: string;
      feedback?: string | null;
      /** The reviewer's edited tasks. Omitted means "unedited, use the proposal" —
       *  which is not the same as an empty list, and the server refuses that. */
      tasks?: PlanTask[];
    }) =>
      apiFetch<{ review_id: string; decision: string }>(`/runs/${runId}/plan-review`, {
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
        `/runs/${runId}/cancel`,
        { method: "POST" },
      ),
    onSuccess: () => qc.invalidateQueries({ queryKey: v2Keys.run(runId) }),
  });
}

/** The run status at which each pause event is the live tail rather than history. */
const GATE_PARKS_AT: Record<string, string> = {
  PLAN_READY: "AWAITING_PLAN",
  HITL_READY: "AWAITING_REVIEW",
};

/** Events after which the backlog genuinely ends. Mirrors the server's replay stop-list. */
const TERMINAL_EVENTS = new Set(["COMPLETED", "FAILED"]);

/**
 * The run's live event stream.
 *
 * Native `EventSource`, so a dropped connection reconnects with `Last-Event-ID` and the
 * backend replays the durable `agent_logs` after that id — nothing is lost, and no polling
 * loop is needed to cover the gap. The same mechanism the session monitor uses; this is a second
 * *subscriber*, not a second event system.
 *
 * A terminal event refreshes the run graph and closes the stream, because the graph is
 * suspended at that point and holding the socket open waits on no one. `degraded` is exposed
 * so the caller can fall back to slow polling rather than pretending the stream is fine.
 */
export function useRunStream(runId: string, enabled: boolean, runKey?: string | null) {
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
    const url = streamUrl(`/api/v1/runs/${runId}/stream`);
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

      const gate = GATE_PARKS_AT[payload.type];
      const terminal = TERMINAL_EVENTS.has(payload.type);
      if (gate || terminal) {
        // The authoritative row, not the event's summary of it. Refreshed for a replayed
        // gate too: that is how a *live* gate is noticed at all. The event arrives while
        // this subscription still believes the run is RUNNING, so the refetch is what
        // moves the status on — and the resubscribe that follows sees the gate again with
        // the run parked at it, and closes then.
        qc.invalidateQueries({ queryKey: v2Keys.run(runId) });
        qc.invalidateQueries({ queryKey: ["v2-runs"] });
      }
      // Hang up only where there is genuinely nothing more to read.
      //
      // A gate closes the stream when the run is *parked* at it — a suspended graph
      // publishes nothing, so waiting waits on no one. A gate the run has already left is
      // just history, and closing on it discards everything the run did afterwards. That
      // was the defect: the backend replays past gates on purpose, and this handler undid
      // it on every reconnect, so a failed run rendered as a planner that never finished
      // while thirty executor and critic rows sat unread in `agent_logs`.
      if (terminal || gate === runKey) source.close();
    };
    source.onerror = () => setDegraded(true);

    return () => source.close();
    // `runKey` is already inside `subKey`; it is named here because the handler reads it
    // to tell a gate the run is parked at from one it has passed.
  }, [subKey, runId, runKey, qc]);

  return { events, degraded };
}
