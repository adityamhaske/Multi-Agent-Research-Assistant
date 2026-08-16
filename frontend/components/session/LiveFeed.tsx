"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";

import type { StreamState } from "@/hooks/useSessionStream";
import { AGENT_TOKEN } from "@/lib/pipeline";
import type { AgentEvent, AgentName } from "@/lib/types";

import {
  IconBookOpen,
  IconEdit,
  IconFileText,
  IconGlobe,
  IconLibrary,
  IconList,
  IconScale,
  IconSearch,
  IconTarget,
  IconThought,
  IconWarningTriangle,
} from "@/components/icons";
import { StatusDot } from "@/components/ui/StatusDot";
import { Toolbar } from "@/components/ui/Toolbar";

function agentColor(agent?: AgentName | null): string {
  if (agent && agent in AGENT_TOKEN) return `var(--${AGENT_TOKEN[agent]})`;
  return "var(--text-muted)";
}

function ConnectionPill({ state }: { state: StreamState }) {
  if (state === "reconnecting") {
    return (
      <span
        className="badge font-mono text-[length:var(--text-micro)] font-semibold"
        style={{
          color: "var(--warning)",
          backgroundColor: "color-mix(in srgb, var(--warning) 10%, var(--bg-surface))",
          borderColor: "color-mix(in srgb, var(--warning) 30%, var(--border))",
        }}
      >
        <span className="spinner" style={{ width: 8, height: 8 }} /> Reconnecting…
      </span>
    );
  }
  if (state === "connecting") {
    return (
      <span className="font-mono text-[length:var(--text-micro)] text-text-muted">
        Connecting…
      </span>
    );
  }
  if (state === "open") {
    return <StatusDot tone="success">Live</StatusDot>;
  }
  return null;
}

/**
 * One label + body pattern, reused across the nine detail kinds below instead
 * of nine near-identical `bg-bg-elevated/70 border p-2.5` blocks each with its
 * own emoji and its own margin. Square, not rounded — the app's identity
 * (`--radius: 0`) rather than the `rounded` utility this block used to carry.
 */
function DetailBlock({
  icon,
  label,
  tone = "muted",
  children,
}: {
  icon: ReactNode;
  label: ReactNode;
  tone?: "muted" | "warning";
  children: ReactNode;
}) {
  return (
    <div className="border border-border/50 bg-bg-elevated/70 p-2.5">
      <span
        className="mb-1.5 flex items-center gap-1.5 text-[length:var(--text-micro)] font-semibold uppercase tracking-wider"
        style={{ color: tone === "warning" ? "var(--warning)" : "var(--text-muted)" }}
      >
        <span aria-hidden className="shrink-0">
          {icon}
        </span>
        {label}
      </span>
      {children}
    </div>
  );
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
      <Toolbar
        title="Activity Log"
        meta={
          <>
            <span className="text-[length:var(--text-micro)] font-mono text-text-muted">
              ({events.length} event{events.length === 1 ? "" : "s"})
            </span>
            {events.some((e) => e.detail && Object.keys(e.detail).length > 0) && (
              <button
                type="button"
                onClick={toggleAll}
                className="text-[length:var(--text-micro)] font-mono text-accent hover:underline cursor-pointer"
              >
                {expandedIds.size > 0 ? "Collapse all" : "Expand all"}
              </button>
            )}
          </>
        }
        actions={<ConnectionPill state={state} />}
      />

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
                  className={`border transition-colors p-2 ${
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
                          className="w-24 shrink-0 font-mono text-[length:var(--text-micro)] font-semibold uppercase tracking-wider"
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
                        className="shrink-0 font-mono text-[length:var(--text-micro)] px-1.5 py-0.5 border border-border bg-bg-elevated hover:bg-bg-surface text-text-secondary hover:text-text-primary transition-colors"
                        title={isExpanded ? "Collapse thoughts & details" : "Expand thoughts & details"}
                      >
                        {isExpanded ? "▲ Hide" : "▼ Details"}
                      </button>
                    )}
                  </div>

                  {hasDetail && isExpanded && detail && (
                    <div className="mt-2.5 pt-2 border-t border-border/70 space-y-2.5 text-[length:var(--text-micro)]">
                      {/* Thought Process */}
                      {Boolean(detail.thought && typeof detail.thought === "string") && (
                        <DetailBlock icon={<IconThought />} label="Thought Process">
                          <p className="whitespace-pre-wrap font-mono text-text-secondary leading-relaxed">
                            {String(detail.thought)}
                          </p>
                        </DetailBlock>
                      )}

                      {/* Targeted Research Query */}
                      {Boolean(detail.query && typeof detail.query === "string") && (
                        <DetailBlock icon={<IconTarget />} label="Research Query">
                          <p className="text-text-primary font-medium">{String(detail.query)}</p>
                        </DetailBlock>
                      )}

                      {/* Tool and Arguments / Query */}
                      {Boolean(detail.args && typeof detail.args === "object") && (
                        <DetailBlock icon={<IconSearch />} label="Search / Tool Parameters">
                          <pre className="overflow-x-auto text-text-primary whitespace-pre-wrap">
                            {JSON.stringify(detail.args, null, 2)}
                          </pre>
                        </DetailBlock>
                      )}

                      {/* Planned Tasks */}
                      {Boolean(Array.isArray(detail.tasks) && (detail.tasks as unknown[]).length > 0) && (
                        <DetailBlock
                          icon={<IconList />}
                          label={`Planned Sub-tasks (${(detail.tasks as unknown[]).length})`}
                        >
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
                                <li key={idx} className="flex items-start gap-2 text-text-secondary text-[length:var(--text-micro)]">
                                  <span className="badge font-mono text-[0.625rem] py-0 px-1 shrink-0 mt-0.5">
                                    {taskId ?? `#${idx + 1}`}
                                  </span>
                                  <span className="text-text-primary font-medium">{queryText}</span>
                                </li>
                              );
                            })}
                          </ul>
                        </DetailBlock>
                      )}

                      {/* Observations / Output / Webpage Content */}
                      {Boolean(detail.observation) && (
                        <DetailBlock
                          icon={
                            detail.tool === "read_webpage" ? (
                              <IconBookOpen />
                            ) : detail.tool === "web_search" ? (
                              <IconGlobe />
                            ) : (
                              <IconFileText />
                            )
                          }
                          label={
                            detail.tool === "read_webpage"
                              ? "Page Content Read by Agent"
                              : detail.tool === "web_search"
                              ? "Search Engine Results"
                              : "Tool Result / Retrieved Content"
                          }
                        >
                          <pre className="max-h-60 overflow-y-auto overflow-x-auto text-text-secondary whitespace-pre-wrap leading-relaxed text-[length:var(--text-micro)] bg-bg-surface p-2 border border-border/40">
                            {typeof detail.observation === "string"
                              ? detail.observation
                              : JSON.stringify(detail.observation, null, 2)}
                          </pre>
                        </DetailBlock>
                      )}

                      {/* Submitted Evidence & Collected Facts */}
                      {Boolean(Array.isArray(detail.evidence) && (detail.evidence as unknown[]).length > 0) && (
                        <DetailBlock
                          icon={<IconLibrary />}
                          label={`Evidence & Collected Facts (${(detail.evidence as unknown[]).length})`}
                        >
                          <div className="space-y-2">
                            {(detail.evidence as Array<Record<string, unknown>>).map((ev, idx) => (
                              <div
                                key={idx}
                                className="p-2.5 bg-bg-surface border border-border/50 text-[length:var(--text-micro)] space-y-1.5"
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
                                    <strong className="text-text-primary font-mono text-[length:var(--text-micro)]">
                                      Fact:
                                    </strong>{" "}
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
                        </DetailBlock>
                      )}

                      {/* Critic Evaluation Reasons & Feedback */}
                      {Boolean(Array.isArray(detail.reasons) && (detail.reasons as unknown[]).length > 0) && (
                        <DetailBlock icon={<IconScale />} label="Evaluation Reasons">
                          <ul className="list-disc pl-4 space-y-0.5 text-text-secondary">
                            {(detail.reasons as unknown[]).map((r, idx) => (
                              <li key={idx}>{String(r)}</li>
                            ))}
                          </ul>
                        </DetailBlock>
                      )}
                      {Boolean(detail.feedback_for_executor) && (
                        <DetailBlock
                          icon={<IconWarningTriangle />}
                          label="Critic Feedback For Rework"
                          tone="warning"
                        >
                          <p className="text-warning">{String(detail.feedback_for_executor)}</p>
                        </DetailBlock>
                      )}

                      {/* Report Synthesis Preview */}
                      {Boolean(detail.preview) && (
                        <DetailBlock
                          icon={<IconEdit />}
                          label={`Draft Report Preview (${String(detail.word_count ?? "")} words, ${String(
                            detail.sources_count ?? ""
                          )} sources)`}
                        >
                          <pre className="max-h-48 overflow-y-auto overflow-x-auto text-text-secondary whitespace-pre-wrap leading-relaxed text-[length:var(--text-micro)] bg-bg-surface p-2 border border-border/40">
                            {String(detail.preview)}
                          </pre>
                        </DetailBlock>
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
