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
        className="badge font-mono text-[0.6875rem] font-semibold"
        style={{ color: "var(--warning)", backgroundColor: "color-mix(in srgb, var(--warning) 10%, var(--bg-surface))", borderColor: "color-mix(in srgb, var(--warning) 30%, var(--border))" }}
      >
        <span className="spinner" style={{ width: 8, height: 8 }} /> Reconnecting…
      </span>
    );
  }
  if (state === "connecting") {
    return <span className="font-mono text-[0.6875rem] text-text-muted">Connecting…</span>;
  }
  if (state === "open") {
    return (
      <span className="badge font-mono text-[0.6875rem] text-text-muted border-border">
        <span className="status-marker" style={{ backgroundColor: "var(--success)" }} /> Live
      </span>
    );
  }
  return null;
}

export function LiveFeed({ events, state }: { events: AgentEvent[]; state: StreamState }) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const [atBottom, setAtBottom] = useState(true);
  const [expandedIds, setExpandedIds] = useState<Set<string | number>>(new Set());

  const toggleExpand = (id: string | number) => {
    setExpandedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  };

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

  const toggleAll = () => {
    if (expandedIds.size > 0) {
      setExpandedIds(new Set());
    } else {
      const allIds = new Set(
        events
          .filter((e) => e.detail && Object.keys(e.detail).length > 0)
          .map((e, idx) => e.id ?? idx)
      );
      setExpandedIds(allIds);
    }
  };

  return (
    <div className="card relative flex h-full flex-col p-0">
      <div className="flex items-center justify-between border-b border-border px-4 py-2.5">
        <div className="flex items-center gap-3">
          <h3 className="text-sm font-serif font-semibold text-text-primary">Activity Log</h3>
          <span className="text-[0.6875rem] font-mono text-text-muted">
            ({events.length} event{events.length === 1 ? "" : "s"})
          </span>
          {events.some((e) => e.detail && Object.keys(e.detail).length > 0) && (
            <button
              type="button"
              onClick={toggleAll}
              className="text-[0.6875rem] font-mono text-accent hover:underline cursor-pointer"
            >
              {expandedIds.size > 0 ? "Collapse all" : "Expand all"}
            </button>
          )}
        </div>
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
          <ul className="space-y-2">
            {events.map((e, i) => {
              const eventKey = e.id ?? i;
              const hasDetail = !!(e.detail && Object.keys(e.detail).length > 0);
              const isExpanded = expandedIds.has(eventKey);
              const detail = e.detail as Record<string, unknown> | undefined;

              return (
                <li
                  key={eventKey}
                  className={`rounded border transition-colors p-2 ${
                    isExpanded
                      ? "border-accent/40 bg-bg-surface"
                      : "border-transparent hover:border-border/60 hover:bg-bg-surface/50"
                  }`}
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="flex items-baseline gap-2 min-w-0 flex-1">
                      <span className="w-16 shrink-0 text-text-muted font-mono tabular-nums">
                        {(e.ts ?? "").slice(11, 19)}
                      </span>
                      {e.agent && (
                        <span
                          className="w-24 shrink-0 font-mono text-[0.6875rem] font-semibold uppercase tracking-wider"
                          style={{ color: agentColor(e.agent) }}
                        >
                          {e.agent}
                        </span>
                      )}
                      <span className="min-w-0 text-text-secondary break-words font-medium">
                        {e.message}
                      </span>
                    </div>

                    {hasDetail && (
                      <button
                        type="button"
                        onClick={() => toggleExpand(eventKey)}
                        className="shrink-0 font-mono text-[0.6875rem] px-1.5 py-0.5 border border-border bg-bg-elevated hover:bg-bg-surface text-text-secondary hover:text-text-primary transition-colors rounded"
                        title={isExpanded ? "Collapse thoughts & details" : "Expand thoughts & details"}
                      >
                        {isExpanded ? "▲ Hide" : "▼ Details"}
                      </button>
                    )}
                  </div>

                  {hasDetail && isExpanded && detail && (
                    <div className="mt-2.5 pt-2 border-t border-border/70 space-y-2.5 text-[0.6875rem]">
                      {/* Thought Process */}
                      {Boolean(detail.thought && typeof detail.thought === "string") && (
                        <div className="rounded bg-bg-elevated/70 p-2.5 border border-border/50">
                          <span className="block font-semibold uppercase tracking-wider text-text-muted text-[0.625rem] mb-1">
                            💭 Thought Process
                          </span>
                          <p className="whitespace-pre-wrap font-mono text-text-secondary leading-relaxed">
                            {String(detail.thought)}
                          </p>
                        </div>
                      )}

                      {/* Targeted Research Query */}
                      {Boolean(detail.query && typeof detail.query === "string") && (
                        <div className="rounded bg-bg-elevated/70 p-2.5 border border-border/50">
                          <span className="block font-semibold uppercase tracking-wider text-text-muted text-[0.625rem] mb-0.5">
                            🎯 Research Query
                          </span>
                          <p className="text-text-primary font-medium">{String(detail.query)}</p>
                        </div>
                      )}

                      {/* Tool and Arguments / Query */}
                      {Boolean(detail.args && typeof detail.args === "object") && (
                        <div className="rounded bg-bg-elevated/70 p-2.5 border border-border/50">
                          <span className="block font-semibold uppercase tracking-wider text-text-muted text-[0.625rem] mb-1">
                            🔍 Search / Tool Parameters
                          </span>
                          <pre className="overflow-x-auto text-text-primary whitespace-pre-wrap">
                            {JSON.stringify(detail.args, null, 2)}
                          </pre>
                        </div>
                      )}

                      {/* Planned Tasks */}
                      {Boolean(Array.isArray(detail.tasks) && (detail.tasks as unknown[]).length > 0) && (
                        <div className="rounded bg-bg-elevated/70 p-2.5 border border-border/50">
                          <span className="block font-semibold uppercase tracking-wider text-text-muted text-[0.625rem] mb-1.5">
                            📋 Planned Sub-tasks ({(detail.tasks as unknown[]).length})
                          </span>
                          <ul className="space-y-1.5 pl-1">
                            {(detail.tasks as unknown[]).map((t, idx) => {
                              const queryText =
                                typeof t === "object" && t !== null && "query" in t
                                  ? String((t as Record<string, unknown>).query)
                                  : String(t);
                              const taskId =
                                typeof t === "object" && t !== null && "id" in t
                                  ? String((t as Record<string, unknown>).id)
                                  : null;
                              return (
                                <li key={idx} className="flex items-start gap-2 text-text-secondary text-[0.6875rem]">
                                  <span className="badge font-mono text-[0.625rem] py-0 px-1 shrink-0 mt-0.5">
                                    {taskId ?? `#${idx + 1}`}
                                  </span>
                                  <span className="text-text-primary font-medium">{queryText}</span>
                                </li>
                              );
                            })}
                          </ul>
                        </div>
                      )}

                      {/* Observations / Output / Webpage Content */}
                      {Boolean(detail.observation) && (
                        <div className="rounded bg-bg-elevated/70 p-2.5 border border-border/50">
                          <span className="block font-semibold uppercase tracking-wider text-text-muted text-[0.625rem] mb-1">
                            {detail.tool === "read_webpage"
                              ? "📖 Page Content Read by Agent"
                              : detail.tool === "web_search"
                              ? "🌐 Search Engine Results"
                              : "📄 Tool Result / Retrieved Content"}
                          </span>
                          <pre className="max-h-60 overflow-y-auto overflow-x-auto text-text-secondary whitespace-pre-wrap leading-relaxed text-[0.6875rem] bg-bg-surface p-2 border border-border/40 rounded">
                            {typeof detail.observation === "string"
                              ? detail.observation
                              : JSON.stringify(detail.observation, null, 2)}
                          </pre>
                        </div>
                      )}

                      {/* Submitted Evidence & Collected Facts */}
                      {Boolean(Array.isArray(detail.evidence) && (detail.evidence as unknown[]).length > 0) && (
                        <div className="rounded bg-bg-elevated/70 p-2.5 border border-border/50">
                          <span className="block font-semibold uppercase tracking-wider text-text-muted text-[0.625rem] mb-2">
                            📚 Evidence & Collected Facts ({(detail.evidence as unknown[]).length})
                          </span>
                          <div className="space-y-2">
                            {(detail.evidence as Array<Record<string, unknown>>).map((ev, idx) => (
                              <div
                                key={idx}
                                className="p-2.5 rounded bg-bg-surface border border-border/50 text-[0.6875rem] space-y-1.5"
                              >
                                <div className="flex items-baseline justify-between gap-2">
                                  <span className="font-semibold text-text-primary">
                                    {String(ev.title || ev.key_fact || `Source #${idx + 1}`)}
                                  </span>
                                  {ev.source_url ? (
                                    <a
                                      href={String(ev.source_url)}
                                      target="_blank"
                                      rel="noreferrer"
                                      className="text-accent underline text-[0.625rem] truncate max-w-[240px]"
                                    >
                                      {String(ev.source_url)}
                                    </a>
                                  ) : null}
                                </div>
                                {Boolean(ev.key_fact && ev.key_fact !== ev.title) && (
                                  <p className="text-text-secondary font-sans text-xs">
                                    <strong className="text-text-primary font-mono text-[0.6875rem]">Fact:</strong>{" "}
                                    {String(ev.key_fact)}
                                  </p>
                                )}
                                {Boolean(ev.snippet) && (
                                  <blockquote className="border-l-2 border-accent/60 pl-2 text-text-muted italic text-[0.625rem] whitespace-pre-wrap">
                                    &ldquo;{String(ev.snippet)}&rdquo;
                                  </blockquote>
                                )}
                              </div>
                            ))}
                          </div>
                        </div>
                      )}

                      {/* Critic Evaluation Reasons & Feedback */}
                      {Boolean(Array.isArray(detail.reasons) && (detail.reasons as unknown[]).length > 0) && (
                        <div className="rounded bg-bg-elevated/70 p-2.5 border border-border/50">
                          <span className="block font-semibold uppercase tracking-wider text-text-muted text-[0.625rem] mb-1">
                            ⚖️ Evaluation Reasons
                          </span>
                          <ul className="list-disc pl-4 space-y-0.5 text-text-secondary">
                            {(detail.reasons as unknown[]).map((r, idx) => (
                              <li key={idx}>{String(r)}</li>
                            ))}
                          </ul>
                        </div>
                      )}
                      {Boolean(detail.feedback_for_executor) && (
                        <div className="rounded bg-bg-elevated/70 p-2.5 border border-border/50 text-warning">
                          <span className="block font-semibold uppercase tracking-wider text-[0.625rem] mb-1">
                            ⚠️ Critic Feedback For Rework
                          </span>
                          <p>{String(detail.feedback_for_executor)}</p>
                        </div>
                      )}

                      {/* Report Synthesis Preview */}
                      {Boolean(detail.preview) && (
                        <div className="rounded bg-bg-elevated/70 p-2.5 border border-border/50">
                          <span className="block font-semibold uppercase tracking-wider text-text-muted text-[0.625rem] mb-1">
                            📝 Draft Report Preview ({String(detail.word_count ?? "")} words, {String(detail.sources_count ?? "")} sources)
                          </span>
                          <pre className="max-h-48 overflow-y-auto overflow-x-auto text-text-secondary whitespace-pre-wrap leading-relaxed text-[0.6875rem] bg-bg-surface p-2 border border-border/40 rounded">
                            {String(detail.preview)}
                          </pre>
                        </div>
                      )}
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </div>

      {!atBottom && (
        <button
          type="button"
          onClick={jumpToLatest}
          className="btn btn-secondary absolute bottom-3 left-1/2 -translate-x-1/2 px-3 py-1 text-xs shadow-lg"
        >
          ↓ Jump to latest
        </button>
      )}
    </div>
  );
}
