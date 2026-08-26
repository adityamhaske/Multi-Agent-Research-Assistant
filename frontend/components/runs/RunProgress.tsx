"use client";

import { useMemo, useState } from "react";

import { IconList, IconSearch, IconThought } from "@/components/icons";
import { AGENT_TOKEN } from "@/lib/pipeline";
import type { AgentEvent, RunGraph } from "@/lib/types";
import { deriveStages, type Stage, type StageState } from "@/lib/runProgress";

/**
 * What a run is doing right now, with live agent activity and reasoning disclosure.
 *
 * The run page renders each pipeline stage along with an expandable dropdown
 * displaying what each agent is doing and thinking in real-time.
 *
 * **No percentage, no bar, no elapsed-time extrapolation.** The backend publishes discrete
 * events and a status; it does not publish completion, so a bar would be the frontend
 * inventing a measurement — the one thing this product must never do. The derivation lives
 * in `lib/v2Progress.ts` and is tested there; this file only draws it.
 *
 * Colour is reinforcement, never the carrier: every stage states its own state in words
 * (and in an `sr-only` phrase for a screen reader), and the marker is redundant with it.
 */

const STAGE_COLOR: Record<string, string> = {
  planner: `var(--${AGENT_TOKEN.planner})`,
  executor: `var(--${AGENT_TOKEN.executor})`,
  critic: `var(--${AGENT_TOKEN.critic})`,
  synthesizer: `var(--${AGENT_TOKEN.synthesizer})`,
  "plan-gate": "var(--agent-hitl)",
  review: "var(--agent-hitl)",
};

const STATE_WORD: Record<StageState, string> = {
  pending: "Not started",
  active: "In progress",
  done: "Done",
  waiting: "Waiting for you",
  stopped: "Did not run",
};

function Marker({ state, color }: { state: StageState; color: string }) {
  if (state === "done") {
    return (
      <span aria-hidden style={{ color }} className="font-mono text-sm leading-none">
        ✓
      </span>
    );
  }
  if (state === "active") {
    return (
      <span
        aria-hidden
        className="spinner"
        style={{ color, width: "0.75rem", height: "0.75rem" }}
      />
    );
  }
  if (state === "waiting") {
    return (
      <span
        aria-hidden
        className="status-marker"
        style={{ backgroundColor: "var(--warning)" }}
      />
    );
  }
  // "Did not run" and "not started yet" are different findings, so they are different
  // marks. Drawn as a dash rather than a second empty box.
  if (state === "stopped") {
    return (
      <span aria-hidden className="font-mono text-sm leading-none text-text-muted">
        –
      </span>
    );
  }
  return (
    <span
      aria-hidden
      className="status-marker"
      style={{ backgroundColor: "transparent", border: "1px solid var(--border)" }}
    />
  );
}

function StageDetailDrawer({
  stage,
  events,
}: {
  stage: Stage;
  events: AgentEvent[];
}) {
  const agentEvents = useMemo(
    () => events.filter((e) => e.agent === stage.id),
    [events, stage.id],
  );

  // Extract thoughts from agent events
  const thoughts = useMemo(() => {
    const list: { thought: string; message?: string | null; ts?: string | null }[] = [];
    for (const e of agentEvents) {
      const detail = (e.detail ?? {}) as Record<string, unknown>;
      const thought = typeof detail.thought === "string" ? detail.thought.trim() : null;
      if (thought) {
        list.push({ thought, message: e.message, ts: e.ts });
      }
    }
    return list;
  }, [agentEvents]);

  // Extract latest tool invocations or actions
  const toolCalls = useMemo(() => {
    const calls: { tool: string; args?: unknown; observation?: string | null; message?: string | null }[] = [];
    for (const e of agentEvents) {
      const detail = (e.detail ?? {}) as Record<string, unknown>;
      if (typeof detail.tool === "string") {
        calls.push({
          tool: detail.tool,
          args: detail.args,
          observation: typeof detail.observation === "string" ? detail.observation : null,
          message: e.message,
        });
      }
    }
    return calls;
  }, [agentEvents]);

  const latestThought = thoughts.length > 0 ? thoughts[thoughts.length - 1] : null;
  const recentEvents = agentEvents.slice(-4);

  if (agentEvents.length === 0 && stage.state === "pending") {
    return (
      <div className="mt-2.5 border border-dashed border-border/60 bg-bg-surface/50 p-3 text-xs text-text-muted">
        This agent has not started yet. Its activity and reasoning will appear here as it executes.
      </div>
    );
  }

  if (agentEvents.length === 0 && stage.state === "active") {
    return (
      <div className="mt-2.5 border border-border bg-bg-surface/60 p-3 text-xs text-text-secondary">
        <div className="flex items-center gap-2">
          <span className="spinner" style={{ width: 10, height: 10 }} />
          <span>{stage.agentName} is currently initializing and reasoning...</span>
        </div>
      </div>
    );
  }

  return (
    <div className="mt-2.5 space-y-2.5 border border-border bg-bg-surface/80 p-3 text-xs">
      {/* Latest Agent Thinking & Reasoning */}
      {latestThought && (
        <div className="border-l-2 border-accent bg-bg-elevated/70 p-2.5">
          <div className="mb-1 flex items-center gap-1.5 font-mono text-[length:var(--text-micro)] font-semibold uppercase tracking-wider text-accent">
            <IconThought className="h-3.5 w-3.5" />
            <span>Agent Thinking & Reasoning</span>
          </div>
          <p className="whitespace-pre-wrap font-sans text-xs leading-relaxed text-text-primary">
            {latestThought.thought}
          </p>
        </div>
      )}

      {/* Latest Tool Actions (e.g. search queries, page fetches) */}
      {toolCalls.length > 0 && (
        <div className="space-y-1.5">
          <div className="flex items-center gap-1.5 font-mono text-[length:var(--text-micro)] font-semibold uppercase tracking-wider text-text-muted">
            <IconSearch className="h-3 w-3" />
            <span>Tools & Search Queries ({toolCalls.length})</span>
          </div>
          <div className="space-y-1">
            {toolCalls.slice(-3).map((call, idx) => (
              <div
                key={idx}
                className="flex items-start gap-2 border border-border/50 bg-bg-base px-2.5 py-1.5 font-mono text-[0.6875rem] text-text-secondary"
              >
                <span className="font-semibold text-accent">{call.tool}:</span>
                <span className="truncate">
                  {typeof call.args === "object" && call.args !== null
                    ? JSON.stringify(call.args)
                    : String(call.args ?? call.message ?? "")}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Activity Timeline */}
      {recentEvents.length > 0 && (
        <div className="space-y-1.5">
          <div className="flex items-center gap-1.5 font-mono text-[length:var(--text-micro)] font-semibold uppercase tracking-wider text-text-muted">
            <IconList className="h-3 w-3" />
            <span>Recent Agent Activity</span>
          </div>
          <ul className="space-y-1">
            {recentEvents.map((e, idx) => (
              <li
                key={idx}
                className="flex items-center justify-between gap-2 border-b border-border/20 py-0.5 text-xs text-text-secondary last:border-b-0"
              >
                <span>{e.message || "Agent state updated"}</span>
                {e.ts && (
                  <span className="font-mono text-[0.6875rem] text-text-muted">
                    {new Date(e.ts).toLocaleTimeString()}
                  </span>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function StageRow({
  stage,
  events,
  isExpanded,
  onToggle,
}: {
  stage: Stage;
  events: AgentEvent[];
  isExpanded: boolean;
  onToggle: () => void;
}) {
  const color = STAGE_COLOR[stage.id] ?? "var(--text-muted)";
  const dim = stage.state === "pending" || stage.state === "stopped";
  const isAgent = ["planner", "executor", "critic", "synthesizer"].includes(stage.id);

  return (
    <li className="py-2">
      <div className="flex items-start justify-between gap-2.5">
        <div className="flex items-start gap-2.5 min-w-0 flex-1">
          <span className="mt-0.5 flex h-3.5 w-3.5 shrink-0 items-center justify-center">
            <Marker state={stage.state} color={color} />
          </span>
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-1.5 text-[0.8125rem]">
              <span
                className="font-mono text-[length:var(--text-micro)] font-bold uppercase tracking-wider px-1.5 py-0.5"
                style={{
                  color: color,
                  backgroundColor: `color-mix(in srgb, ${color} 10%, var(--bg-surface))`,
                  border: `1px solid color-mix(in srgb, ${color} 25%, var(--border))`,
                }}
              >
                {stage.agentName}
              </span>
              <span
                className={`${dim ? "text-text-muted" : "text-text-primary"} ${
                  stage.state === "active" || stage.state === "waiting" ? "font-semibold" : ""
                }`}
              >
                {stage.actionLabel}
              </span>
            </div>
            {stage.detail && (
              <span className="block text-xs text-text-secondary mt-0.5">{stage.detail}</span>
            )}
            <span className="sr-only">{STATE_WORD[stage.state]}</span>
          </div>
        </div>

        {/* Dropdown toggle button for agent thinking and activity */}
        {isAgent && (
          <button
            type="button"
            onClick={onToggle}
            aria-expanded={isExpanded}
            aria-label={`${isExpanded ? "Collapse" : "Expand"} activity and thinking for ${stage.agentName}`}
            className="btn btn-ghost shrink-0 px-2 py-0.5 font-mono text-[length:var(--text-micro)] text-text-muted hover:text-text-primary"
          >
            <span className="flex items-center gap-1">
              <span>{isExpanded ? "Hide thoughts" : "Thoughts & activity"}</span>
              <span aria-hidden className="text-[0.625rem]">{isExpanded ? "▲" : "▼"}</span>
            </span>
          </button>
        )}
      </div>

      {/* Expanded detail drawer */}
      {isAgent && isExpanded && (
        <StageDetailDrawer stage={stage} events={events} />
      )}
    </li>
  );
}

export function RunProgress({
  graph,
  events,
  degraded,
}: {
  graph: RunGraph;
  events: AgentEvent[];
  /** The stream is not delivering. Said out loud rather than left to look like a stall. */
  degraded: boolean;
}) {
  const stages = useMemo(
    () =>
      deriveStages({
        status: graph.run.status,
        events,
        planGate: !graph.run.skip_plan_gate,
        planDecided: graph.reviews.some((r) => r.gate === "PLAN"),
      }),
    [graph.run.status, graph.run.skip_plan_gate, graph.reviews, events],
  );

  // Expanded state map for each stage ID
  const [expandedStages, setExpandedStages] = useState<Record<string, boolean>>({});
  const [expandAll, setExpandAll] = useState(false);

  const toggleStage = (stageId: string) => {
    setExpandedStages((prev) => ({
      ...prev,
      [stageId]: !prev[stageId],
    }));
  };

  const toggleAll = () => {
    const nextState = !expandAll;
    setExpandAll(nextState);
    const updated: Record<string, boolean> = {};
    for (const s of stages) {
      updated[s.id] = nextState;
    }
    setExpandedStages(updated);
  };

  // The last thing the pipeline actually said. Shown verbatim: a paraphrase here would be
  // the frontend narrating a run it cannot see.
  const lastMessage = [...events].reverse().find((e) => e.message)?.message ?? null;

  return (
    <section aria-labelledby="run-progress" className="card space-y-3">
      <div className="flex items-center justify-between border-b border-border pb-2.5">
        <h2
          id="run-progress"
          className="font-mono text-[length:var(--text-micro)] font-semibold uppercase tracking-wider text-text-muted"
        >
          Progress
        </h2>
        <button
          type="button"
          onClick={toggleAll}
          className="btn btn-ghost px-2 py-0.5 font-mono text-[length:var(--text-micro)] text-text-secondary hover:text-text-primary"
        >
          <span className="flex items-center gap-1.5">
            <IconThought className="h-3 w-3 text-accent" />
            <span>{expandAll ? "Collapse all agent thoughts" : "Expand all agent thoughts"}</span>
            <span aria-hidden className="text-[0.625rem]">{expandAll ? "▲" : "▼"}</span>
          </span>
        </button>
      </div>

      <ol className="divide-y divide-border/20">
        {stages.map((s) => (
          <StageRow
            key={s.id}
            stage={s}
            events={events}
            isExpanded={Boolean(expandedStages[s.id])}
            onToggle={() => toggleStage(s.id)}
          />
        ))}
      </ol>

      {lastMessage && (
        <div className="bg-bg-elevated p-2.5 text-xs text-text-secondary">
          <span className="font-mono text-[length:var(--text-micro)] font-semibold uppercase tracking-wider text-text-muted">
            Latest:{" "}
          </span>
          {lastMessage}
        </div>
      )}

      {degraded && (
        <p
          className="mt-3 border p-2 text-xs"
          style={{
            color: "var(--warning)",
            backgroundColor: "var(--warning-soft)",
            borderColor: "var(--warning-line)",
          }}
        >
          The live connection dropped. It reconnects automatically and replays anything
          missed, so nothing is lost — this page is not stuck.
        </p>
      )}
    </section>
  );
}
