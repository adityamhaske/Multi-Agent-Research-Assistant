import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { PipelineRail } from "./PipelineRail";
import type { AgentEvent, SessionStatus } from "@/lib/types";

/**
 * The rail gained a sixth node — Plan review, between Planner and Executor (docs/07 §2,
 * Phase 4). The risks worth pinning are the ones a screenshot would not catch: the
 * numbering of every later node shifts, and a session that never used the gate must not
 * show a node stuck pending forever in the middle of an otherwise finished run.
 */

const event = (agent: AgentEvent["agent"]): AgentEvent => ({ type: "agent_log", agent });

function renderRail(status: SessionStatus, events: AgentEvent[] = []) {
  return render(<PipelineRail events={events} status={status} />);
}

function nodes() {
  return within(screen.getByRole("list", { name: "Pipeline progress" })).getAllByRole("listitem");
}

describe("PipelineRail with the design gate", () => {
  it("shows six steps, with Plan review between Planner and Executor", () => {
    renderRail("RUNNING", [event("planner")]);
    const labels = screen
      .getAllByText(/^(Planner|Plan review|Executor|Critic|Synthesizer|Review)$/)
      .map((el) => el.textContent);
    expect(labels).toEqual([
      "Planner",
      "Plan review",
      "Executor",
      "Critic",
      "Synthesizer",
      "Review",
    ]);
  });

  it("numbers the nodes 1..6 with no duplicate and no gap", () => {
    // Every node is pending, so each shows its number rather than a tick.
    renderRail("PENDING");
    for (const n of ["1", "2", "3", "4", "5", "6"]) {
      expect(screen.getByText(n)).toBeInTheDocument();
    }
  });

  it("marks Plan review active and everything downstream pending at the gate", () => {
    renderRail("AWAITING_PLAN", [event("planner")]);
    const [planner, , executor] = nodes();

    // The planner is finished — reaching the gate is what finishing it means.
    expect(within(planner).getByText("done")).toBeInTheDocument();
    // Nothing after the gate has run, whatever the event stream's furthest agent says.
    expect(within(executor).getByText("pending")).toBeInTheDocument();
    expect(screen.getByText("awaiting your research plan")).toBeInTheDocument();
  });

  it("does not leave Plan review pending on a run that skipped the gate", () => {
    // The regression this guards: a completed session — including every session that
    // predates the gate — rendering a permanently-unfinished node in the middle, which
    // reads as a run that is stuck rather than one that never used the feature.
    renderRail("COMPLETED", [event("synthesizer")]);
    expect(screen.queryByText("awaiting your research plan")).not.toBeInTheDocument();
    // Six ticks: five stages plus the draft gate, all done.
    expect(screen.getAllByText("✓")).toHaveLength(6);
  });

  it("keeps the draft gate as the active step at AWAITING_APPROVAL", () => {
    renderRail("AWAITING_APPROVAL", [event("synthesizer")]);
    expect(screen.getByText("awaiting your approval")).toBeInTheDocument();
    expect(screen.queryByText("awaiting your research plan")).not.toBeInTheDocument();
  });
});
