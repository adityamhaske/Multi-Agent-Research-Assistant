import { render as rtlRender, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";

import { ActiveResearchList } from "./ActiveResearchList";
import type { RunSummary } from "@/lib/types";

function render(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return rtlRender(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

function run(overrides: Partial<RunSummary> = {}): RunSummary {
  return {
    id: "r",
    project_id: "p1",
    question: "Question",
    status: "COMPLETED",
    depth: "balanced",
    demo: false,
    cost_usd: 0,
    citation_resolution_rate: null,
    has_artifact: true,
    created_at: "2026-08-20T00:00:00Z",
    ...overrides,
  };
}

describe("ActiveResearchList", () => {
  it("shows a loading skeleton and no content while runs are still loading", () => {
    render(
      <ActiveResearchList runs={[]} excludeId={null} isLoading isError={false} onRetry={vi.fn()} />,
    );
    expect(screen.getByText(/Loading this project's research/)).toBeInTheDocument();
  });

  it("offers a retry when the run list failed to load with nothing cached", () => {
    const onRetry = vi.fn();
    render(
      <ActiveResearchList runs={[]} excludeId={null} isLoading={false} isError onRetry={onRetry} />,
    );
    screen.getByRole("button", { name: "Try again" }).click();
    expect(onRetry).toHaveBeenCalled();
  });

  it("keeps showing cached rows when a background refresh fails, warning they may be stale", () => {
    // React Query keeps the last good `data` when a refetch fails, and the rest of the page
    // renders those same rows from that cache — so replacing this section with an error
    // panel made the page contradict itself and orphaned the attention card's anchor.
    render(
      <ActiveResearchList
        runs={[run({ id: "a", question: "Cached question", status: "RUNNING" })]}
        excludeId={null}
        isLoading={false}
        isError
        onRetry={vi.fn()}
      />,
    );
    expect(screen.getByText("Cached question")).toBeInTheDocument();
    expect(screen.getByText(/may be out of date/)).toBeInTheDocument();
    expect(screen.queryByText(/Couldn't load this project's research/)).not.toBeInTheDocument();
  });

  it("keeps the waiting-on-you anchor target present when the attention card links to it", () => {
    // The AttentionCard renders "+N more waiting on you" pointing at #waiting-on-you; that
    // target must exist in every state where the link can render, including a stale-cache
    // error. It is also focusable so following the link moves keyboard focus.
    const { container } = render(
      <ActiveResearchList
        runs={[
          run({ id: "promoted", status: "AWAITING_REVIEW" }),
          run({ id: "second", status: "AWAITING_PLAN" }),
        ]}
        excludeId="promoted"
        isLoading={false}
        isError
        onRetry={vi.fn()}
      />,
    );
    const target = container.querySelector("#waiting-on-you");
    expect(target).not.toBeNull();
    expect(target).toHaveAttribute("tabindex", "-1");
  });

  it("says there is no research yet when the project truly has none", () => {
    render(
      <ActiveResearchList runs={[]} excludeId={null} isLoading={false} isError={false} onRetry={vi.fn()} />,
    );
    expect(screen.getByText("No research yet")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Ask a question" })).toHaveAttribute(
      "href",
      "/research",
    );
  });

  it("distinguishes 'nothing else here' from 'no research at all' when the only run is promoted above", () => {
    const promoted = run({ id: "promoted", status: "AWAITING_REVIEW" });
    render(
      <ActiveResearchList
        runs={[promoted]}
        excludeId="promoted"
        isLoading={false}
        isError={false}
        onRetry={vi.fn()}
      />,
    );
    expect(screen.getByText("Nothing else here yet")).toBeInTheDocument();
    expect(screen.getByText(/waiting for a decision from you, above/)).toBeInTheDocument();
    expect(screen.queryByText("No research yet")).not.toBeInTheDocument();
  });

  it("excludes the promoted run so it is never shown twice on the page", () => {
    const promoted = run({ id: "promoted", question: "Promoted question", status: "AWAITING_REVIEW" });
    const other = run({ id: "other", question: "Other question", status: "RUNNING" });
    render(
      <ActiveResearchList
        runs={[promoted, other]}
        excludeId="promoted"
        isLoading={false}
        isError={false}
        onRetry={vi.fn()}
      />,
    );
    expect(screen.queryByText("Promoted question")).not.toBeInTheDocument();
    expect(screen.getByText("Other question")).toBeInTheDocument();
  });

  it("groups waiting-on-you, in-progress and recently-finished runs under their own headings, in that order", () => {
    const waiting = run({ id: "w", question: "Waiting question", status: "AWAITING_PLAN" });
    const active = run({ id: "a", question: "Active question", status: "RUNNING" });
    const finished = run({ id: "f", question: "Finished question", status: "COMPLETED" });
    render(
      <ActiveResearchList
        runs={[finished, active, waiting]}
        excludeId={null}
        isLoading={false}
        isError={false}
        onRetry={vi.fn()}
      />,
    );
    const headings = screen.getAllByRole("heading", { level: 3 }).map((h) => h.textContent);
    expect(headings).toEqual(["Waiting on you", "In progress", "Recently finished"]);

    // Each run appears once, under a heading a screen reader would reach in this order.
    expect(screen.getByText("Waiting question")).toBeInTheDocument();
    expect(screen.getByText("Active question")).toBeInTheDocument();
    expect(screen.getByText("Finished question")).toBeInTheDocument();
  });

  it("orders waiting-on-you oldest first, and in-progress / finished newest first", () => {
    const waitOld = run({ id: "wo", question: "Wait old", status: "AWAITING_PLAN", created_at: "2026-08-10T00:00:00Z" });
    const waitNew = run({ id: "wn", question: "Wait new", status: "AWAITING_REVIEW", created_at: "2026-08-20T00:00:00Z" });
    const runOld = run({ id: "ro", question: "Run old", status: "RUNNING", created_at: "2026-08-10T00:00:00Z" });
    const runNew = run({ id: "rn", question: "Run new", status: "PENDING", created_at: "2026-08-20T00:00:00Z" });
    const { container } = render(
      <ActiveResearchList
        runs={[waitNew, waitOld, runOld, runNew]}
        excludeId={null}
        isLoading={false}
        isError={false}
        onRetry={vi.fn()}
      />,
    );
    const text = container.textContent ?? "";
    // Fairness within "waiting": the older decision reads first.
    expect(text.indexOf("Wait old")).toBeLessThan(text.indexOf("Wait new"));
    // Freshness within "in progress": the newer activity reads first.
    expect(text.indexOf("Run new")).toBeLessThan(text.indexOf("Run old"));
  });

  it("caps recently-finished runs and links to History for the rest, without silently dropping the count", () => {
    const finishedRuns = Array.from({ length: 7 }, (_, i) =>
      run({ id: `f${i}`, question: `Finished ${i}`, status: "COMPLETED", created_at: `2026-08-${10 + i}T00:00:00Z` }),
    );
    render(
      <ActiveResearchList
        runs={finishedRuns}
        excludeId={null}
        isLoading={false}
        isError={false}
        onRetry={vi.fn()}
      />,
    );
    const overflow = screen.getByRole("link", { name: /2 more in History/ });
    expect(overflow).toHaveAttribute("href", "/history");
  });

  it("still shows a run whose status this client has not been taught, under 'Other', rather than dropping it", () => {
    render(
      <ActiveResearchList
        runs={[
          run({
            id: "x",
            question: "From-the-future question",
            status: "SOME_FUTURE_STATUS" as RunSummary["status"],
          }),
        ]}
        excludeId={null}
        isLoading={false}
        isError={false}
        onRetry={vi.fn()}
      />,
    );
    expect(screen.getByRole("heading", { name: "Other", level: 3 })).toBeInTheDocument();
    expect(screen.getByText("From-the-future question")).toBeInTheDocument();
  });
});
