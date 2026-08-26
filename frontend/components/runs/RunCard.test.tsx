import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";

import { RunCard } from "./RunCard";
import type { RunSummary } from "@/lib/types";

const mockMutateArchive = vi.fn();
const mockMutateDelete = vi.fn();

vi.mock("@/hooks/runs", async () => {
  const actual = await vi.importActual<typeof import("@/hooks/runs")>("@/hooks/runs");
  return {
    ...actual,
    useArchiveRun: () => ({
      mutateAsync: mockMutateArchive,
      isPending: false,
    }),
    useDeleteRun: () => ({
      mutateAsync: mockMutateDelete,
      isPending: false,
    }),
  };
});

function createSummary(overrides: Partial<RunSummary> = {}): RunSummary {
  return {
    id: "run-123",
    project_id: "proj-456",
    question: "How does distributed consensus work in Raft?",
    status: "COMPLETED",
    depth: "balanced",
    demo: false,
    cost_usd: 0.042,
    citation_resolution_rate: 1.0,
    has_artifact: true,
    archived_at: null,
    created_at: "2026-08-25T12:00:00Z",
    ...overrides,
  };
}

function renderCard(run: RunSummary, showProject?: string | null) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <RunCard run={run} showProject={showProject} />
    </QueryClientProvider>,
  );
}

describe("RunCard", () => {
  it("renders run metadata, question and status", () => {
    const run = createSummary();
    renderCard(run);

    expect(screen.getByText("How does distributed consensus work in Raft?")).toBeInTheDocument();
    expect(screen.getByText("Approved")).toBeInTheDocument();
    expect(screen.getByText("balanced")).toBeInTheDocument();
    expect(screen.getByText("✓ verified artifact")).toBeInTheDocument();
    expect(screen.getByText("100% citations resolve")).toBeInTheDocument();
  });

  it("shows Archive button for active run and calls archive mutation on click", async () => {
    const user = userEvent.setup();
    const run = createSummary({ archived_at: null });
    renderCard(run);

    const archiveBtn = screen.getByRole("button", { name: "Archive" });
    expect(archiveBtn).toBeInTheDocument();

    await user.click(archiveBtn);
    expect(mockMutateArchive).toHaveBeenCalledWith({ id: "run-123", archived: true });
  });

  it("shows Restore button for archived run and calls unarchive mutation on click", async () => {
    const user = userEvent.setup();
    const run = createSummary({ archived_at: "2026-08-25T14:00:00Z" });
    renderCard(run);

    const restoreBtn = screen.getByRole("button", { name: "Restore" });
    expect(restoreBtn).toBeInTheDocument();

    await user.click(restoreBtn);
    expect(mockMutateArchive).toHaveBeenCalledWith({ id: "run-123", archived: false });
  });

  it("shows inline confirmation when clicking Delete, and cancels on No", async () => {
    const user = userEvent.setup();
    const run = createSummary();
    renderCard(run);

    const deleteBtn = screen.getByRole("button", { name: "Delete" });
    await user.click(deleteBtn);

    expect(screen.getByText("Delete permanently?")).toBeInTheDocument();
    const noBtn = screen.getByRole("button", { name: "No" });
    await user.click(noBtn);

    expect(screen.queryByText("Delete permanently?")).not.toBeInTheDocument();
    expect(mockMutateDelete).not.toHaveBeenCalled();
  });

  it("deletes run permanently when clicking Yes on confirmation", async () => {
    const user = userEvent.setup();
    const run = createSummary();
    renderCard(run);

    const deleteBtn = screen.getByRole("button", { name: "Delete" });
    await user.click(deleteBtn);

    const yesBtn = screen.getByRole("button", { name: "Yes" });
    await user.click(yesBtn);

    expect(mockMutateDelete).toHaveBeenCalledWith("run-123");
  });
});
