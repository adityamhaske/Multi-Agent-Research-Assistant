import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { LiveFeed } from "./LiveFeed";
import type { AgentEvent } from "@/lib/types";

/**
 * The feed's detail pane was nine sibling boxes with no hierarchy. It is now four
 * semantic groups — Reasoning · Evidence · Verdict · Draft (docs/07 §2, Phase 7).
 *
 * Grouped, **not merged**: "Evaluation Reasons" and "Critic Feedback For Rework" are
 * different things, and folding them into one block would destroy that distinction to
 * fix a layout problem. What is asserted here is that the grouping appeared and that no
 * label was lost — and that a group with nothing in it renders nothing, since an
 * executor event sprouting an empty "Verdict" heading is the obvious way to get this
 * wrong.
 */

function feed(events: AgentEvent[]) {
  return render(<LiveFeed events={events} state="open" />);
}

const CRITIC: AgentEvent = {
  type: "agent_log",
  id: 1,
  agent: "critic",
  message: "Evaluated task 1",
  detail: {
    reasons: ["two independent sources"],
    feedback_for_executor: "Gather a primary source for the 2025 figure.",
  },
};

const EXECUTOR: AgentEvent = {
  type: "agent_log",
  id: 2,
  agent: "executor",
  message: "Researching: 'grounding metrics'",
  detail: { thought: "Start with survey papers.", query: "grounding metrics" },
};

describe("LiveFeed detail groups", () => {
  it("groups a critic's blocks under Verdict without losing either label", async () => {
    const user = userEvent.setup();
    feed([CRITIC]);
    await user.click(screen.getByRole("button", { name: /details/i }));

    expect(screen.getByRole("region", { name: "Verdict" })).toBeInTheDocument();
    // Both distinct labels survive the grouping.
    expect(screen.getByText("Evaluation Reasons")).toBeInTheDocument();
    expect(screen.getByText(/Critic Feedback/i)).toBeInTheDocument();
  });

  it("renders no heading for a group that holds nothing", async () => {
    const user = userEvent.setup();
    feed([EXECUTOR]);
    await user.click(screen.getByRole("button", { name: /details/i }));

    expect(screen.getByRole("region", { name: "Reasoning" })).toBeInTheDocument();
    // This event carries no verdict and no draft; empty headings would be noise
    // presented as structure.
    expect(screen.queryByRole("region", { name: "Verdict" })).not.toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Draft" })).not.toBeInTheDocument();
  });
});

describe("LiveFeed density", () => {
  it("switches the log's density without touching the saved preference", async () => {
    const user = userEvent.setup();
    feed([EXECUTOR]);

    const log = screen.getByLabelText("Agent activity log");
    expect(log).toHaveAttribute("data-density", "comfortable");

    await user.click(screen.getByRole("button", { name: /comfortable/i }));
    expect(log).toHaveAttribute("data-density", "compact");
    // A reading posture for this run, not a setting — nothing is persisted, so there is
    // no request to assert and no profile write to undo.
  });
});
