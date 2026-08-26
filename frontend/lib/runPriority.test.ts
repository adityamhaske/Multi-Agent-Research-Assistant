import { describe, expect, it } from "vitest";

import { pickPriorityRun } from "./runPriority";
import type { RunSummary } from "./types";

function run(id: string, created_at: string, status: RunSummary["status"] = "AWAITING_REVIEW"): RunSummary {
  return {
    id,
    project_id: "p1",
    question: `Question ${id}`,
    status,
    depth: "balanced",
    demo: false,
    cost_usd: 0,
    citation_resolution_rate: null,
    has_artifact: false,
    created_at,
  };
}

describe("pickPriorityRun", () => {
  it("returns null for an empty list", () => {
    expect(pickPriorityRun([])).toBeNull();
  });

  it("returns the only run when there is one", () => {
    const r = run("a", "2026-08-20T00:00:00Z");
    expect(pickPriorityRun([r])).toBe(r);
  });

  it("picks the oldest run — the one that has waited longest", () => {
    const oldest = run("oldest", "2026-08-18T00:00:00Z");
    const middle = run("middle", "2026-08-20T00:00:00Z");
    const newest = run("newest", "2026-08-22T00:00:00Z");
    // Order in the input array must not matter — only created_at does.
    expect(pickPriorityRun([newest, oldest, middle])).toBe(oldest);
    expect(pickPriorityRun([middle, newest, oldest])).toBe(oldest);
  });
});
