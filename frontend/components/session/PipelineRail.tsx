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
                className="flex h-7 w-7 items-center justify-center border font-mono text-xs font-semibold"
                style={
                  s === "pending"
                    ? { borderColor: "var(--border)", color: "var(--text-muted)", backgroundColor: "var(--bg-elevated)" }
                    : {
                        borderColor: color,
                        color,
                        backgroundColor: `color-mix(in srgb, ${color} 10%, var(--bg-surface))`,
                        animation: s === "active" ? "pulse-ring 1.4s ease-in-out infinite" : undefined,
                      }
                }
                aria-hidden
              >
                {s === "done" ? "✓" : i + 1}
              </span>
              <span
                className="truncate font-mono text-[0.6875rem] uppercase tracking-wider font-medium"
                style={{ color: s === "pending" ? "var(--text-muted)" : color }}
              >
                {AGENT_LABELS[agent]}
              </span>
              <span className="sr-only">{s}</span>
            </div>
            {i < AGENTS.length - 1 && (
              <span
                className="mb-5 h-px flex-1"
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
