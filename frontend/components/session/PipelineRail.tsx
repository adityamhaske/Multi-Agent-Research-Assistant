import { AGENT_LABELS, AGENT_TOKEN, AGENTS, latestAgentOrder, routeModelLabel } from "@/lib/pipeline";
import type { AgentEvent, SessionStatus } from "@/lib/types";

type NodeState = "pending" | "active" | "done";

/**
 * The "brain monitor" rail (docs/07 §3): Planner → **Plan review** → Executor → Critic →
 * Synthesizer → Review, with live per-node state.
 *
 * The two review nodes are presentational and derived from `status`, not from an agent
 * event: both human gates are LangGraph `interrupt()` checkpoints rather than agents, so
 * nothing emits them into the stream and `AgentName` stays exactly the backend's four.
 * They are drawn anyway because they are the steps the *user* is on the hook for — a rail
 * ending at "Synthesizer ✓" implied the run was finished at the exact moment it was
 * waiting on them.
 *
 * Both gates use `--agent-hitl`: it is the human's hue, and the two nodes are the same
 * kind of step. Colour is never the sole carrier here anyway (AGENTS.md) — position,
 * number and label all distinguish them, and a sixth audited hue would say "different
 * urgency" when the truth is "different decision".
 */
const REVIEW_COLOR = "var(--agent-hitl)";

function nodeStyle(state: NodeState, color: string) {
  return state === "pending"
    ? {
        borderColor: "var(--border)",
        color: "var(--text-muted)",
        backgroundColor: "var(--bg-elevated)",
      }
    : {
        borderColor: color,
        color,
        backgroundColor: `color-mix(in srgb, ${color} 10%, var(--bg-surface))`,
        animation: state === "active" ? "pulse-ring 1.4s ease-in-out infinite" : undefined,
      };
}

/** A human-gate node. Same grammar as an agent node, minus the model line — a gate
 *  dials no model, and printing "—" there would read as unresolved routing. */
function GateNode({
  state,
  index,
  label,
  activeHint,
}: {
  state: NodeState;
  index: number;
  label: string;
  activeHint: string;
}) {
  return (
    <div className="flex min-w-0 flex-1 flex-col items-center gap-1.5">
      <span
        className="flex h-7 w-7 items-center justify-center border font-mono text-xs font-semibold"
        style={nodeStyle(state, REVIEW_COLOR)}
        aria-hidden
      >
        {state === "done" ? "✓" : index}
      </span>
      <span
        className="truncate font-mono text-[0.6875rem] uppercase tracking-wider font-medium"
        style={{ color: state === "pending" ? "var(--text-muted)" : REVIEW_COLOR }}
      >
        {label}
      </span>
      <span className="sr-only">{state === "active" ? activeHint : state}</span>
    </div>
  );
}

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
  const atPlanGate = status === "AWAITING_PLAN";
  const agentsDone = status === "AWAITING_APPROVAL" || status === "COMPLETED";
  const running = status === "PENDING" || status === "RUNNING";

  // The design gate is "done" the moment anything downstream of it has run — which is
  // also true of every session that skipped it or predates it, so those show it passed
  // rather than pending. A permanently-pending node in the middle of a finished rail
  // reads as a run that is stuck.
  //
  // Not derived from `atPlanGate` alone: that made the node render as passed before the
  // planner had produced anything, on a run whose very first frame is PENDING.
  const planGateState: NodeState = atPlanGate
    ? "active"
    : agentsDone || order >= 1
      ? "done"
      : "pending";

  const reviewState: NodeState =
    status === "COMPLETED" ? "done" : status === "AWAITING_APPROVAL" ? "active" : "pending";

  const nodeState = (i: number): NodeState => {
    if (agentsDone) return "done";
    // Parked at the design gate: the planner is finished and nothing after it has run,
    // regardless of what the event stream's furthest-along agent happens to be.
    if (atPlanGate) return i === 0 ? "done" : "pending";
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
        // The design gate is drawn immediately after the planner, so the numbering of
        // every later node shifts by one — derived, not hardcoded, so adding a stage
        // cannot leave two nodes claiming the same number.
        const number = i === 0 ? 1 : i + 2;
        return (
          <li key={agent} className="flex flex-1 items-center gap-1">
            <div className="flex min-w-0 flex-1 flex-col items-center gap-1.5">
              <span
                className="flex h-7 w-7 items-center justify-center border font-mono text-xs font-semibold"
                style={nodeStyle(s, color)}
                aria-hidden
              >
                {s === "done" ? "✓" : number}
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
              style={{
                backgroundColor:
                  i < order || agentsDone ? color : atPlanGate && i === 0 ? color : "var(--border)",
              }}
              aria-hidden
            />
            {/* Plan review, between Planner and Executor. Rendered inside the planner's
                <li> so the connector line either side of it stays continuous. */}
            {i === 0 && (
              <>
                <GateNode
                  state={planGateState}
                  index={2}
                  label="Plan review"
                  activeHint="awaiting your research plan"
                />
                <span
                  className="mb-5 h-px flex-1"
                  style={{
                    backgroundColor: planGateState === "done" ? REVIEW_COLOR : "var(--border)",
                  }}
                  aria-hidden
                />
              </>
            )}
          </li>
        );
      })}

      {/* The draft gate. Same visual grammar, and the last step in the sequence. */}
      <li className="flex flex-1 items-center gap-1">
        <GateNode
          state={reviewState}
          index={AGENTS.length + 2}
          label="Review"
          activeHint="awaiting your approval"
        />
      </li>
    </ol>
  );
}
