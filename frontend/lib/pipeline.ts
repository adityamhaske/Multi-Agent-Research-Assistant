import type { AgentEvent, AgentName } from "./types";

/** Pipeline shape + derivations from the agent event stream (docs/04, docs/07 §3). */

export const AGENTS: AgentName[] = ["planner", "executor", "critic", "synthesizer"];

export const AGENT_LABELS: Record<AgentName, string> = {
  planner: "Planner",
  executor: "Executor",
  critic: "Critic",
  synthesizer: "Synthesizer",
};

/** CSS token name (without `--`) for each agent's accent color. */
export const AGENT_TOKEN: Record<AgentName, string> = {
  planner: "agent-planner",
  executor: "agent-executor",
  critic: "agent-critic",
  synthesizer: "agent-synthesizer",
};

/** Order index of the furthest-along agent seen so far, or -1 if none. */
export function latestAgentOrder(events: AgentEvent[]): number {
  let order = -1;
  for (const e of events) {
    if (e.agent) {
      const i = AGENTS.indexOf(e.agent);
      if (i > order) order = i;
    }
  }
  return order;
}

/** Research-task progress derived from planner + executor events (rework-safe). */
export function taskProgress(events: AgentEvent[]): { done: number; total: number } {
  let total = 0;
  const gathered = new Set<string>();
  for (const e of events) {
    const detail = (e.detail ?? {}) as Record<string, unknown>;
    if (e.agent === "planner" && Array.isArray(detail.tasks)) {
      total = detail.tasks.length;
    }
    if (e.agent === "executor" && typeof e.message === "string" && e.message.startsWith("Gathered")) {
      gathered.add(detail.task_id !== undefined ? String(detail.task_id) : String(gathered.size));
    }
  }
  const done = total ? Math.min(gathered.size, total) : gathered.size;
  return { done, total };
}
