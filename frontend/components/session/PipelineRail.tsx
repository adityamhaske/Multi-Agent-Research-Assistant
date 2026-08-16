import { AGENT_LABELS, AGENT_TOKEN, AGENTS, latestAgentOrder, routeModelLabel } from "@/lib/pipeline";
import type { AgentEvent, SessionStatus } from "@/lib/types";

type NodeState = "pending" | "active" | "done";

/**
 * The "brain monitor" rail (docs/07 §3): Planner → Executor → Critic → Synthesizer →
 * Review, with live per-node state.
 *
 * The Review node is presentational and derived from `status`, not from an agent event:
 * the human gate is a LangGraph `interrupt()` checkpoint rather than an agent, so nothing
 * emits it into the stream and `AgentName` stays exactly the backend's four. It is drawn
 * anyway because the gate is the step the *user* is on the hook for — a rail ending at
 * "Synthesizer ✓" implied the run was finished at the exact moment it was waiting on them.
 */
const REVIEW_COLOR = "var(--agent-hitl)";

export function PipelineRail({
  events,
  status,
  modelRouting,
}: {
  events: AgentEvent[];
  status: SessionStatus;
  /** Resolved per-role routing (docs/07 §2). Absent/null renders every node's model
   * as "—" rather than guessing — the unmeasured-vs-zero rule. */
  modelRouting?: Record<string, string> | null;
}) {
  const order = latestAgentOrder(events);
  const agentsDone = status === "AWAITING_APPROVAL" || status === "COMPLETED";
  const running = status === "PENDING" || status === "RUNNING";

  const reviewState: NodeState =
    status === "COMPLETED" ? "done" : status === "AWAITING_APPROVAL" ? "active" : "pending";

  const nodeState = (i: number): NodeState => {
    if (agentsDone) return "done";
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
              <span
                className="max-w-full truncate font-mono text-[length:var(--text-micro)] text-text-muted"
                title={modelRouting?.[agent] || "Model not resolved"}
              >
                {routeModelLabel(modelRouting?.[agent])}
              </span>
              <span className="sr-only">{s}</span>
            </div>
            <span
              className="mb-5 h-px flex-1"
              style={{ backgroundColor: i < order || agentsDone ? color : "var(--border)" }}
              aria-hidden
            />
          </li>
        );
      })}

      {/* The human gate. Same visual grammar as an agent node so the rail reads as one
          sequence, but it is the reviewer's step, not the pipeline's. */}
      <li className="flex flex-1 items-center gap-1">
        <div className="flex min-w-0 flex-1 flex-col items-center gap-1.5">
          <span
            className="flex h-7 w-7 items-center justify-center border font-mono text-xs font-semibold"
            style={
              reviewState === "pending"
                ? {
                    borderColor: "var(--border)",
                    color: "var(--text-muted)",
                    backgroundColor: "var(--bg-elevated)",
                  }
                : {
                    borderColor: REVIEW_COLOR,
                    color: REVIEW_COLOR,
                    backgroundColor: `color-mix(in srgb, ${REVIEW_COLOR} 10%, var(--bg-surface))`,
                    animation:
                      reviewState === "active" ? "pulse-ring 1.4s ease-in-out infinite" : undefined,
                  }
            }
            aria-hidden
          >
            {reviewState === "done" ? "✓" : AGENTS.length + 1}
          </span>
          <span
            className="truncate font-mono text-[0.6875rem] uppercase tracking-wider font-medium"
            style={{ color: reviewState === "pending" ? "var(--text-muted)" : REVIEW_COLOR }}
          >
            Review
          </span>
          <span className="sr-only">
            {reviewState === "active" ? "awaiting your approval" : reviewState}
          </span>
        </div>
      </li>
    </ol>
  );
}
