import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AttentionCard } from "./AttentionCard";
import type { RunSummary } from "@/lib/types";

/**
 * The attention card is the page's one prominent claim: "this run needs you." Its two
 * jobs under test are the ones that matter most if they drift — the CTA has to land
 * exactly on the gate that is actually open, and the card must never print a number this
 * run summary does not actually carry (AGENTS.md's unmeasured-vs-zero rule, applied to a
 * run with no report yet).
 */

function run(overrides: Partial<RunSummary> = {}): RunSummary {
  return {
    id: "run-1",
    project_id: "p1",
    question: "What are the leading approaches to long-term memory in LLM agents?",
    status: "AWAITING_REVIEW",
    depth: "balanced",
    demo: false,
    cost_usd: 1.2345,
    citation_resolution_rate: null,
    has_artifact: false,
    created_at: "2026-08-20T00:00:00Z",
    ...overrides,
  };
}

describe("AttentionCard", () => {
  it("links a report review to the run's review tab, labelled 'Review report'", () => {
    render(<AttentionCard run={run({ status: "AWAITING_REVIEW" })} waitingCount={1} />);
    const cta = screen.getByRole("link", { name: "Review report" });
    expect(cta).toHaveAttribute("href", "/research/run?id=run-1&tab=review");
  });

  it("links a plan review to the run's plan tab, labelled 'Review plan'", () => {
    render(<AttentionCard run={run({ status: "AWAITING_PLAN" })} waitingCount={1} />);
    const cta = screen.getByRole("link", { name: "Review plan" });
    expect(cta).toHaveAttribute("href", "/research/run?id=run-1&tab=plan");
  });

  it("says how many more are waiting when there is more than one", () => {
    render(<AttentionCard run={run()} waitingCount={3} />);
    const more = screen.getByRole("link", { name: /2 more waiting/ });
    expect(more).toHaveAttribute("href", "#waiting-on-you");
  });

  it("says nothing about further runs when this is the only one waiting", () => {
    render(<AttentionCard run={run()} waitingCount={1} />);
    expect(screen.queryByText(/more waiting/)).not.toBeInTheDocument();
  });

  it("names a demo run", () => {
    render(<AttentionCard run={run({ demo: true })} waitingCount={1} />);
    expect(screen.getByText("demo")).toBeInTheDocument();
  });

  it("never claims a citation or evidence figure this run summary does not carry", () => {
    render(<AttentionCard run={run()} waitingCount={1} />);
    expect(screen.queryByText(/citation/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/evidence/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/verified/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/% /)).not.toBeInTheDocument();
  });
});
