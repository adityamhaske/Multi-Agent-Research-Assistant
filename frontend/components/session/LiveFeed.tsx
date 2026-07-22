"use client";

import { useEffect, useRef, useState } from "react";

import type { StreamState } from "@/hooks/useSessionStream";
import { AGENT_TOKEN } from "@/lib/pipeline";
import type { AgentEvent, AgentName } from "@/lib/types";

function agentColor(agent?: AgentName | null): string {
  if (agent && agent in AGENT_TOKEN) return `var(--${AGENT_TOKEN[agent]})`;
  return "var(--text-muted)";
}

function ConnectionPill({ state }: { state: StreamState }) {
  if (state === "reconnecting") {
    return (
      <span
        className="inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-[0.7rem] font-medium"
        style={{ color: "var(--warning)", backgroundColor: "color-mix(in srgb, var(--warning) 14%, transparent)" }}
      >
        <span className="spinner" style={{ width: 10, height: 10 }} /> Reconnecting…
      </span>
    );
  }
  if (state === "connecting") {
    return <span className="text-[0.7rem] text-text-muted">Connecting…</span>;
  }
  if (state === "open") {
    return (
      <span className="inline-flex items-center gap-1.5 text-[0.7rem] text-text-muted">
        <span className="h-1.5 w-1.5 rounded-full" style={{ backgroundColor: "var(--success)" }} /> Live
      </span>
    );
  }
  return null;
}

export function LiveFeed({ events, state }: { events: AgentEvent[]; state: StreamState }) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const [atBottom, setAtBottom] = useState(true);

  // Auto-scroll only while the user is already at the bottom — never fight their scroll.
  useEffect(() => {
    const el = scrollRef.current;
    if (atBottom && el) el.scrollTop = el.scrollHeight;
  }, [events, atBottom]);

  const onScroll = () => {
    const el = scrollRef.current;
    if (!el) return;
    setAtBottom(el.scrollHeight - el.scrollTop - el.clientHeight < 40);
  };

  const jumpToLatest = () => {
    const el = scrollRef.current;
    if (el) {
      el.scrollTop = el.scrollHeight;
      setAtBottom(true);
    }
  };

  return (
    <div className="card relative flex h-full flex-col p-0">
      <div className="flex items-center justify-between border-b border-border px-4 py-2.5">
        <h3 className="text-sm font-semibold text-text-primary">Activity</h3>
        <ConnectionPill state={state} />
      </div>

      <div
        ref={scrollRef}
        onScroll={onScroll}
        className="min-h-0 flex-1 overflow-y-auto px-4 py-3 font-mono text-xs leading-relaxed"
        aria-live="polite"
        aria-label="Agent activity log"
      >
        {events.length === 0 ? (
          <p className="text-text-muted">Waiting for the pipeline to start…</p>
        ) : (
          <ul className="space-y-1.5">
            {events.map((e, i) => (
              <li key={e.id ?? i} className="flex gap-2">
                <span className="shrink-0 text-text-muted">{(e.ts ?? "").slice(11, 19)}</span>
                {e.agent && (
                  <span className="shrink-0 font-semibold" style={{ color: agentColor(e.agent) }}>
                    {e.agent}
                  </span>
                )}
                <span className="min-w-0 text-text-secondary">{e.message}</span>
              </li>
            ))}
          </ul>
        )}
      </div>

      {!atBottom && (
        <button
          type="button"
          onClick={jumpToLatest}
          className="btn btn-secondary absolute bottom-3 left-1/2 -translate-x-1/2 px-3 py-1 text-xs shadow-md"
        >
          ↓ Jump to latest
        </button>
      )}
    </div>
  );
}
