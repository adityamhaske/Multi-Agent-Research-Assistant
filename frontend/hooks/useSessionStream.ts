"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import type { AgentEvent } from "@/lib/types";

import { queryKeys } from "./queries";

export type StreamState = "idle" | "connecting" | "open" | "reconnecting" | "closed";

/**
 * SSE lifecycle for the session monitor (docs/07 §3).
 *
 * Uses native `EventSource`: same-origin so the httpOnly cookie authenticates it, and
 * on a dropped connection the browser auto-reconnects **with `Last-Event-ID`** — the
 * backend replays the durable agent_logs after that id, so nothing is lost. On mount
 * (and again after approve/rework flips the session back to RUNNING) `enabled` re-runs
 * this one connect path, so reconnects always carry the full set of handlers.
 *
 * A terminal event (HITL_READY / COMPLETED / FAILED) pulls the authoritative session
 * row into the query cache and closes the stream. When the stream is degraded, the
 * caller polls the session as a fallback (see the session page).
 */
export function useSessionStream(sessionId: string, enabled: boolean) {
  const qc = useQueryClient();
  const [events, setEvents] = useState<AgentEvent[]>([]);
  const [state, setState] = useState<StreamState>("idle");
  const seenIds = useRef<Set<number>>(new Set());

  // Reset the feed + dedupe set the moment the subscription target changes — React's
  // "reset state when a prop changes" pattern (setState during render, guarded), not an
  // effect. The backend replays the full backlog on (re)connect, so a clean slate is
  // correct; we de-dup replayed rows by durable event id in onmessage.
  const subKey = enabled && sessionId ? sessionId : null;
  const [prevSubKey, setPrevSubKey] = useState<string | null>(null);
  if (subKey !== prevSubKey) {
    setPrevSubKey(subKey);
    setEvents([]);
    setState(subKey ? "connecting" : "idle");
  }

  useEffect(() => {
    if (!enabled || !sessionId) return;

    // Fresh dedupe set for this subscription (ref writes belong in the effect, not render).
    seenIds.current = new Set();

    const es = new EventSource(`/api/v1/research/${sessionId}/stream`, {
      withCredentials: true,
    });

    es.onopen = () => setState("open");

    es.onmessage = (e: MessageEvent<string>) => {
      let payload: AgentEvent;
      try {
        payload = JSON.parse(e.data);
      } catch {
        return;
      }

      if (payload.type === "connected") {
        setState("open");
        return;
      }

      if (typeof payload.id === "number") {
        if (seenIds.current.has(payload.id)) return; // already replayed
        seenIds.current.add(payload.id);
      }

      if (payload.type === "agent_log") {
        setEvents((prev) => [...prev, payload]);
        return;
      }

      if (payload.type === "HITL_READY" || payload.type === "COMPLETED" || payload.type === "FAILED") {
        // Authoritative status/draft/report/cost live on the session row.
        qc.invalidateQueries({ queryKey: queryKeys.session(sessionId) });
        es.close();
        setState("closed");
      }
    };

    es.onerror = () => {
      // We proactively close on terminal events, so a CLOSED socket here is expected
      // and final. Otherwise the browser is mid-reconnect — surface the degraded state
      // so the page falls back to polling.
      setState(es.readyState === EventSource.CLOSED ? "closed" : "reconnecting");
    };

    return () => es.close();
  }, [sessionId, enabled, qc]);

  return { events, state };
}
