import { AGENTS, latestAgentOrder, taskProgress } from "./pipeline";
import type { AgentEvent, RunStatusV2 } from "./types";

/**
 * What a running V2 research run is actually doing, derived from state the backend
 * really reports.
 *
 * **There is no percentage here, and there must never be one.** The backend publishes
 * discrete agent events and a run status; it does not publish completion. A progress bar
 * would have to invent the denominator, and an invented measurement is the one thing this
 * product cannot ship (AGENTS.md, "the product claim is verifiability"). So the stages are
 * a checklist of steps that have *observably* happened, and the only number on it —
 * research tasks gathered — comes from counting planner and executor events, with the
 * total omitted entirely when the planner has not said what it is.
 *
 * Pure and separate from the component so the derivation is testable without a DOM: the
 * interesting cases are a run that failed mid-pipeline and a run watched from PENDING,
 * neither of which is convenient to reproduce by rendering.
 */

export type StageState =
  /** Not reached. */
  | "pending"
  /** Happening now. */
  | "active"
  /** Observed to have finished. */
  | "done"
  /** Waiting on the person reading this. */
  | "waiting"
  /** The run ended before this step ran. */
  | "stopped";

export interface Stage {
  id: string;
  agentName: string;
  actionLabel: string;
  label: string;
  state: StageState;
  /** A fact about this stage, or null. Never a guess. */
  detail: string | null;
}

/** The four engine agents, in pipeline order, with the words a reader recognises. */
const AGENT_STAGES: { id: string; agentName: string; actionLabel: string; label: string }[] = [
  {
    id: "planner",
    agentName: "Planner",
    actionLabel: "Planning the research",
    label: "Planner: Planning the research",
  },
  {
    id: "executor",
    agentName: "Executor",
    actionLabel: "Searching sources and gathering evidence",
    label: "Executor: Searching sources and gathering evidence",
  },
  {
    id: "critic",
    agentName: "Critic",
    actionLabel: "Checking the evidence",
    label: "Critic: Checking the evidence",
  },
  {
    id: "synthesizer",
    agentName: "Synthesizer",
    actionLabel: "Drafting the report",
    label: "Synthesizer: Drafting the report",
  },
];

export interface ProgressInput {
  status: RunStatusV2 | string;
  events: AgentEvent[];
  /** Whether this run has a design gate at all. A run that skipped it never shows one. */
  planGate: boolean;
  /** True once a PLAN review has been recorded. */
  planDecided: boolean;
}

/**
 * The stage checklist for a run.
 *
 * The rules mirror `PipelineRail`'s, which were arrived at by watching real runs:
 * a status that parks the graph (either gate, or a terminal) is authoritative about the
 * agents around it, and the event stream is only consulted for the middle of a live run.
 * Reading it the other way round made a run parked at the design gate claim the executor
 * was busy, because the furthest-along agent in the backlog said so.
 */
export function deriveStages({ status, events, planGate, planDecided }: ProgressInput): Stage[] {
  const order = latestAgentOrder(events);
  const running = status === "PENDING" || status === "RUNNING";
  const atPlanGate = status === "AWAITING_PLAN";
  const atReview = status === "AWAITING_REVIEW";
  const completed = status === "COMPLETED";
  const ended = status === "FAILED" || status === "CANCELLED";
  const agentsDone = atReview || completed;

  const agentState = (i: number): StageState => {
    if (agentsDone) return "done";
    // Parked at the design gate: the planner is finished and nothing after it has run,
    // whatever the furthest-along agent in the replayed backlog happens to be.
    if (atPlanGate) return i === 0 ? "done" : "pending";
    if (ended) {
      if (order < 0) return "stopped";
      if (i < order) return "done";
      return "stopped";
    }
    if (order < 0) return i === 0 && running ? "active" : "pending";
    if (i < order) return "done";
    if (i === order) return running ? "active" : "done";
    return "pending";
  };

  const { done, total } = taskProgress(events);

  const stages: Stage[] = [];
  AGENT_STAGES.forEach((stage, i) => {
    const state = agentState(i);
    let detail: string | null = null;
    // Only the executor gets a count, and only once the planner has said how many tasks
    // there are. `done` alone would read as progress toward an unknown finish.
    if (stage.id === "executor" && total > 0 && (state === "active" || state === "done")) {
      detail = `${Math.min(done, total)} of ${total} research tasks gathered`;
    }
    stages.push({ ...stage, state, detail });

    // The design gate sits between the planner and the executor, and only for runs that
    // have one. Drawing it on a run that skipped it would show a step that never existed.
    if (i === 0 && planGate) {
      stages.push({
        id: "plan-gate",
        agentName: "Plan review",
        actionLabel: "Your plan review",
        label: "Plan review: Your plan review",
        state: atPlanGate
          ? "waiting"
          : planDecided || agentsDone || order >= 1
            ? "done"
            : ended
              ? "stopped"
              : "pending",
        detail: atPlanGate ? "Approve the plan to start searching" : null,
      });
    }
  });

  stages.push({
    id: "review",
    agentName: "Final review",
    actionLabel: "Your review",
    label: "Final review: Your review",
    state: completed ? "done" : atReview ? "waiting" : ended ? "stopped" : "pending",
    detail: atReview ? "Approve the draft to create a verifiable artifact" : null,
  });

  return stages;
}

/** Sanity check kept next to the derivation: the agent list it walks is the engine's. */
export const AGENT_STAGE_COUNT = AGENTS.length;
