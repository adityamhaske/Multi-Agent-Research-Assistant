import { describe, expect, it } from "vitest";

import { deriveStages } from "./runProgress";
import type { AgentEvent } from "./types";

/**
 * The progress checklist is the one place a research UI is most tempted to lie: a bar that
 * creeps forward reads as knowledge the backend never supplied. These tests are about the
 * two things that keeps honest — that a stage is only "done" when something observed it,
 * and that the single number on the list comes from counted events rather than from a
 * guess at how long a run takes.
 */

const ev = (agent: AgentEvent["agent"], message?: string, detail?: Record<string, unknown>) =>
  ({ type: "agent_log", agent, message, detail }) as AgentEvent;

const base = { events: [] as AgentEvent[], planGate: false, planDecided: false };

function ids(stages: { id: string }[]) {
  return stages.map((s) => s.id);
}

function state(stages: { id: string; state: string }[], id: string) {
  return stages.find((s) => s.id === id)?.state;
}

describe("deriveStages", () => {
  it("lists the four engine stages plus the review, and no plan gate when the run skipped it", () => {
    const stages = deriveStages({ ...base, status: "RUNNING" });
    expect(ids(stages)).toEqual(["planner", "executor", "critic", "synthesizer", "review"]);
  });

  it("draws the plan gate only for a run that has one, and in the right place", () => {
    const stages = deriveStages({ ...base, status: "AWAITING_PLAN", planGate: true });
    expect(ids(stages)).toEqual([
      "planner",
      "plan-gate",
      "executor",
      "critic",
      "synthesizer",
      "review",
    ]);
  });

  it("shows the planner active on a queued run rather than claiming nothing is happening", () => {
    const stages = deriveStages({ ...base, status: "PENDING" });
    expect(state(stages, "planner")).toBe("active");
    expect(state(stages, "executor")).toBe("pending");
  });

  it("advances only as far as the furthest agent the stream actually reported", () => {
    const stages = deriveStages({
      ...base,
      status: "RUNNING",
      events: [ev("planner", "Planned 3 tasks"), ev("executor", "Gathered 1")],
    });
    expect(state(stages, "planner")).toBe("done");
    expect(state(stages, "executor")).toBe("active");
    expect(state(stages, "critic")).toBe("pending");
  });

  it("trusts the gate status over the event backlog", () => {
    // A reconnect replays every prior event, so the furthest-along agent in the backlog can
    // be well past the point the run is actually parked at. The status is authoritative.
    const stages = deriveStages({
      ...base,
      status: "AWAITING_PLAN",
      planGate: true,
      events: [ev("planner"), ev("executor"), ev("synthesizer")],
    });
    expect(state(stages, "planner")).toBe("done");
    expect(state(stages, "plan-gate")).toBe("waiting");
    expect(state(stages, "executor")).toBe("pending");
  });

  it("marks every agent done and the review waiting at the report gate", () => {
    const stages = deriveStages({ ...base, status: "AWAITING_REVIEW" });
    for (const id of ["planner", "executor", "critic", "synthesizer"]) {
      expect(state(stages, id)).toBe("done");
    }
    expect(state(stages, "review")).toBe("waiting");
  });

  it("distinguishes a stage that did not run from one that has not started", () => {
    const stages = deriveStages({
      ...base,
      status: "FAILED",
      events: [ev("planner"), ev("executor")],
    });
    expect(state(stages, "planner")).toBe("done");
    // The executor was the furthest-along agent when it died: it did not finish.
    expect(state(stages, "executor")).toBe("stopped");
    expect(state(stages, "synthesizer")).toBe("stopped");
    expect(state(stages, "review")).toBe("stopped");
  });

  it("reports a task count only once the planner has said how many there are", () => {
    const withoutTotal = deriveStages({
      ...base,
      status: "RUNNING",
      events: [ev("executor", "Gathered evidence", { task_id: "1" })],
    });
    expect(withoutTotal.find((s) => s.id === "executor")?.detail).toBeNull();

    const withTotal = deriveStages({
      ...base,
      status: "RUNNING",
      events: [
        ev("planner", "Planned", { tasks: [1, 2, 3] }),
        ev("executor", "Gathered evidence for task 1", { task_id: "1" }),
      ],
    });
    expect(withTotal.find((s) => s.id === "executor")?.detail).toBe(
      "1 of 3 research tasks gathered",
    );
  });

  it("never reports more tasks gathered than the planner asked for", () => {
    const stages = deriveStages({
      ...base,
      status: "RUNNING",
      events: [
        ev("planner", "Planned", { tasks: [1] }),
        ev("executor", "Gathered a", { task_id: "1" }),
        ev("executor", "Gathered b", { task_id: "2" }),
      ],
    });
    expect(stages.find((s) => s.id === "executor")?.detail).toBe("1 of 1 research tasks gathered");
  });

  it("treats a decided plan gate as passed even after the run moves on", () => {
    const stages = deriveStages({
      ...base,
      status: "COMPLETED",
      planGate: true,
      planDecided: true,
    });
    expect(state(stages, "plan-gate")).toBe("done");
    expect(state(stages, "review")).toBe("done");
  });

  it("exposes no percentage anywhere in its output", () => {
    const stages = deriveStages({
      ...base,
      status: "RUNNING",
      events: [ev("planner", "Planned", { tasks: [1, 2] }), ev("executor", "Gathered")],
    });
    const serialized = JSON.stringify(stages);
    expect(serialized).not.toMatch(/%/);
    expect(serialized).not.toMatch(/percent/i);
  });
});
