import { describe, expect, it } from "vitest";

import { AGENTS, latestAgentOrder, taskProgress } from "./pipeline";
import type { AgentEvent } from "./types";

const log = (agent: AgentEvent["agent"], message: string, detail?: Record<string, unknown>): AgentEvent => ({
  type: "agent_log",
  agent,
  message,
  detail: detail ?? null,
});

describe("latestAgentOrder", () => {
  it("returns -1 before any agent has spoken", () => {
    expect(latestAgentOrder([])).toBe(-1);
  });

  it("tracks the furthest-along agent", () => {
    const events = [log("planner", "Decomposing…"), log("executor", "Researching: 'a'")];
    expect(latestAgentOrder(events)).toBe(AGENTS.indexOf("executor"));
  });

  it("does not regress when the executor/critic loop revisits an earlier agent", () => {
    const events = [
      log("planner", "Decomposing…"),
      log("executor", "Researching: 'a'"),
      log("critic", "❌ FAIL (retry 1)"),
      log("executor", "Researching: 'a'"), // loop back
    ];
    expect(latestAgentOrder(events)).toBe(AGENTS.indexOf("critic"));
  });
});

describe("taskProgress", () => {
  it("is zero with no events", () => {
    expect(taskProgress([])).toEqual({ done: 0, total: 0 });
  });

  it("reads the total from the planner and counts gathered tasks", () => {
    const events = [
      log("planner", "Created 3 research tasks", { tasks: ["a", "b", "c"] }),
      log("executor", "Gathered 4 source(s) for task t1", { task_id: "t1" }),
      log("executor", "Gathered 2 source(s) for task t2", { task_id: "t2" }),
    ];
    expect(taskProgress(events)).toEqual({ done: 2, total: 3 });
  });

  it("counts a re-gathered task once so rework never inflates progress", () => {
    const events = [
      log("planner", "Created 2 research tasks", { tasks: ["a", "b"] }),
      log("executor", "Gathered 4 source(s) for task t1", { task_id: "t1" }),
      log("critic", "❌ FAIL (retry 1)"),
      log("executor", "Gathered 6 source(s) for task t1", { task_id: "t1" }), // same task again
    ];
    expect(taskProgress(events)).toEqual({ done: 1, total: 2 });
  });

  it("never reports more done than total", () => {
    const events = [
      log("planner", "Created 1 research tasks", { tasks: ["a"] }),
      log("executor", "Gathered 1 source(s) for task t1", { task_id: "t1" }),
      log("executor", "Gathered 1 source(s) for task t2", { task_id: "t2" }),
    ];
    expect(taskProgress(events).done).toBe(1);
  });
});
