import { AGENT_LABELS, AGENT_TOKEN, AGENTS, latestAgentOrder } from "@/lib/pipeline";
import type { AgentEvent, SessionStatus } from "@/lib/types";

type NodeState = "pending" | "active" | "done";

/**
 * The "brain monitor" rail (docs/07 §3): Planner → Executor → Critic → Synthesizer with
 * live per-node state. Once the pipeline reaches the review gate (or later), every node
 * reads done.
 */
export function PipelineRail({ events, status }: { events: AgentEvent[]; status: SessionStatus }) {
  const order = latestAgentOrder(events);
  const allDone = status === "AWAITING_APPROVAL" || status === "COMPLETED";
  const running = status === "PENDING" || status === "RUNNING";

  const nodeState = (i: number): NodeState => {
    if (allDone) return "done";
    if (order < 0) return i === 0 && running ? "active" : "pending";
    if (i < order) return "done";
    if (i === order) return running ? "active" : "done";
    return "pending";
  };

  return (
    <ol className="flex items-center gap-1" aria-label="Pipeline progress">
      {AGENTS.map((agent, i) => {
        const s = nodeState(i);
        const color = `var(--${AGENT_TOKEN[agent]})`;
        return (
          <li key={agent} className="flex flex-1 items-center gap-1">
            <div className="flex min-w-0 flex-1 flex-col items-center gap-1.5">
              <span
                className="flex h-8 w-8 items-center justify-center rounded-full border-2 text-xs font-semibold"
                style={
                  s === "pending"
                    ? { borderColor: "var(--border)", color: "var(--text-muted)" }
                    : {
                        borderColor: color,
                        color,
                        backgroundColor: `color-mix(in srgb, ${color} 14%, transparent)`,
                        animation: s === "active" ? "pulse-ring 1.4s ease-in-out infinite" : undefined,
                      }
                }
                aria-hidden
              >
                {s === "done" ? "✓" : i + 1}
              </span>
              <span
                className="truncate text-[0.7rem] font-medium"
                style={{ color: s === "pending" ? "var(--text-muted)" : color }}
              >
                {AGENT_LABELS[agent]}
              </span>
              <span className="sr-only">{s}</span>
            </div>
            {i < AGENTS.length - 1 && (
              <span
                className="mb-5 h-0.5 flex-1 rounded"
                style={{ backgroundColor: i < order || allDone ? color : "var(--border)" }}
                aria-hidden
              />
            )}
          </li>
        );
      })}
    </ol>
  );
}
