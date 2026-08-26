import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ProjectHealth } from "./ProjectHealth";
import type { MemoryStatus, RunSummary } from "@/lib/types";

/**
 * Project health is where this page makes numerical claims, so its tests are mostly about
 * refusal: never call a partial sum a total, never render a zero for something that could
 * not be read, and never let a corpus problem and a memory problem wear each other's
 * words.
 */

let memoryState: {
  data?: Partial<MemoryStatus>;
  isLoading?: boolean;
  isError?: boolean;
};
let corpusState: {
  data?: { documents: number; chunks: number };
  isLoading?: boolean;
  isError?: boolean;
};
let desktop = false;

vi.mock("@/lib/desktop", () => ({
  get isDesktop() {
    return desktop;
  },
}));

vi.mock("@/hooks/queries", () => ({
  useMemoryStatus: () => memoryState,
  useCorpusStatus: () => corpusState,
}));

function memory(overrides: Partial<MemoryStatus> = {}): Partial<MemoryStatus> {
  return {
    available: true,
    chunk_count: 40,
    indexed_reports: 2,
    approved_reports: 2,
    pending_reports: 0,
    current_model: "nomic-embed-text",
    models: [],
    stale_models: [],
    last_ingest_at: null,
    ...overrides,
  };
}

function run(cost: number, id: string): RunSummary {
  return {
    id,
    project_id: "p1",
    question: "Q",
    status: "COMPLETED",
    depth: "balanced",
    demo: false,
    cost_usd: cost,
    citation_resolution_rate: null,
    has_artifact: true,
    created_at: "2026-08-20T00:00:00Z",
  };
}

function view(
  runs: RunSummary[] | undefined = [],
  { runsLoading = false, runsError = false } = {},
) {
  return render(
    <ProjectHealth
      projectId="p1"
      runs={runs}
      runsLoading={runsLoading}
      runsError={runsError}
    />,
  );
}

beforeEach(() => {
  desktop = false;
  memoryState = { data: memory(), isLoading: false, isError: false };
  corpusState = { data: { documents: 3, chunks: 90 }, isLoading: false, isError: false };
});

describe("ProjectHealth", () => {
  it("sums cost over the runs it was given and refuses to call it a project total", () => {
    view([run(1.5, "a"), run(2.25, "b")]);
    expect(screen.getByText("$3.75")).toBeInTheDocument();
    expect(screen.getByText(/not a project total/)).toBeInTheDocument();
  });

  it("names the exact set the spend covers", () => {
    view([run(1, "a"), run(1, "b")]);
    // The caption once said "runs shown on this page", which the list below contradicts:
    // it shows fewer than the sum covers.
    expect(screen.getByText(/2 most recent research runs/)).toBeInTheDocument();
    expect(screen.getByText(/not a project total/)).toBeInTheDocument();
  });

  it("says recent runs could not be read rather than rendering Runs 0 / $0.00", () => {
    view(undefined, { runsError: true });
    expect(screen.getByText(/Couldn't read recent runs/)).toBeInTheDocument();
    expect(screen.queryByText("$0.00")).not.toBeInTheDocument();
    expect(screen.queryByText(/most recent research run/)).not.toBeInTheDocument();
  });

  it("does not render a spend figure while the run list is still loading", () => {
    view(undefined, { runsLoading: true });
    expect(screen.queryByText("$0.00")).not.toBeInTheDocument();
  });

  it("says the corpus could not be read rather than rendering zero documents", () => {
    corpusState = { data: undefined, isLoading: false, isError: true };
    view();
    expect(screen.getByText(/Couldn't read the corpus/)).toBeInTheDocument();
    expect(screen.queryByText("Documents")).not.toBeInTheDocument();
  });

  it("says memory status could not be read rather than rendering zero reports", () => {
    memoryState = { data: undefined, isLoading: false, isError: true };
    view();
    expect(screen.getByText(/Couldn't read memory status/)).toBeInTheDocument();
    expect(screen.queryByText("Approved")).not.toBeInTheDocument();
  });

  it("keeps corpus emptiness and memory emptiness in separate words", () => {
    corpusState = { data: { documents: 0, chunks: 0 }, isLoading: false, isError: false };
    memoryState = {
      data: memory({ approved_reports: 0, indexed_reports: 0 }),
      isLoading: false,
      isError: false,
    };
    view();
    // Corpus: an upload problem, pointing at Corpus.
    expect(screen.getByText(/No documents yet/)).toBeInTheDocument();
    // Memory: scoped to what actually feeds it, not described as un-indexed documents.
    expect(screen.getByText(/Built from approved reports only/)).toBeInTheDocument();
  });

  it("says what feeds memory rather than implying every finished run does", () => {
    // This caption used to read "research runs are not indexed into it", which was true
    // when only one pipeline wrote memory and became false the day both did. Approval is
    // the filter, and that is what the card now says.
    memoryState = {
      data: memory({ approved_reports: 0, indexed_reports: 0 }),
      isLoading: false,
      isError: false,
    };
    view();
    expect(screen.getByText(/Built from approved reports only/)).toBeInTheDocument();
    expect(screen.queryByText(/not indexed into it/)).not.toBeInTheDocument();
  });

  it("blames the missing embedding model, not the user, when memory cannot function at all", () => {
    memoryState = {
      data: memory({ available: false, approved_reports: 0, indexed_reports: 0 }),
      isLoading: false,
      isError: false,
    };
    view();
    expect(screen.getByText(/No embedding model is configured/)).toBeInTheDocument();
    // Must not tell them approving something will populate memory — it will not.
    expect(screen.queryByText(/Built from approved reports only/)).not.toBeInTheDocument();
  });

  it("makes an un-indexed approved report actionable by naming the consequence", () => {
    memoryState = {
      data: memory({ approved_reports: 3, indexed_reports: 2, pending_reports: 1 }),
      isLoading: false,
      isError: false,
    };
    view();
    expect(
      screen.getByText(/1 approved report not indexed — follow-up chat can't draw on it yet\./),
    ).toBeInTheDocument();
  });

  it("explains a stale embedding model as a memory problem, not a corpus one", () => {
    memoryState = {
      data: memory({ stale_models: ["text-embedding-3-small"] }),
      isLoading: false,
      isError: false,
    };
    view();
    expect(screen.getByText(/a re-index would bring them back/)).toBeInTheDocument();
  });

  it("says project memory is absent on desktop instead of showing it as empty", () => {
    desktop = true;
    view();
    expect(screen.getByText(/isn't part of the desktop app/)).toBeInTheDocument();
    expect(screen.queryByText("Approved")).not.toBeInTheDocument();
  });
});
