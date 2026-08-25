import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { StartResearchForm } from "./StartResearchForm";

/**
 * Starting a run is the one action in this product that spends money, so the form's job is
 * as much refusal as submission: refuse an empty or three-word question, refuse when there
 * is no project to scope the run to, and refuse a second submit while the first is in
 * flight — and in every case *say which*, because a disabled button with no reason reads as
 * broken rather than blocked.
 */

const mutate = vi.fn();
let pending = false;
let activeId: string | undefined = "p1";
let projectsLoading = false;

vi.mock("@/hooks/v2", () => ({
  useStartV2Research: () => ({
    mutate,
    isPending: pending,
    isError: false,
    error: null,
  }),
}));

vi.mock("@/hooks/queries", () => ({
  useCorpusStatus: () => ({ data: undefined }),
  // The form reads the catalog to show which models the run will actually use. Resolved
  // to one route for every role, which is what the picker can represent as a single model.
  useModelCatalog: () => ({
    data: {
      available_providers: ["custom", "ollama"],
      models: [],
      effective_routing: {
        planner: "custom:auto/best-fast",
        executor: "custom:auto/best-fast",
        critic: "custom:auto/best-fast",
        synthesizer: "custom:auto/best-fast",
        chat: "custom:auto/best-fast",
      },
    },
    isLoading: false,
    isError: false,
  }),
  useCustomEndpointStatus: () => ({ data: undefined, isLoading: false }),
  useLocalLLMStatus: () => ({ data: undefined, isLoading: false }),
}));

vi.mock("@/components/ActiveProject", () => ({
  useActiveProject: () => ({
    activeId,
    active: activeId ? { id: activeId, name: "Agent Memory" } : undefined,
    isLoading: projectsLoading,
    projects: [],
    setActiveId: vi.fn(),
  }),
}));

function view() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <StartResearchForm onStarted={vi.fn()} />
    </QueryClientProvider>,
  );
}

const LONG = "What does the evidence say about agent memory?";

beforeEach(() => {
  mutate.mockClear();
  pending = false;
  activeId = "p1";
  projectsLoading = false;
});

describe("StartResearchForm", () => {
  it("refuses a too-short question and says how short it is", () => {
    view();
    fireEvent.change(screen.getByLabelText("Research question"), { target: { value: "why" } });
    expect(screen.getByText("At least 10 characters")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Start research" })).toBeDisabled();
  });

  it("refuses to submit with no project, and names that as the reason", () => {
    activeId = undefined;
    view();
    fireEvent.change(screen.getByLabelText("Research question"), { target: { value: LONG } });
    expect(screen.getByRole("button", { name: "Start research" })).toBeDisabled();
    expect(screen.getByText(/Create a project first/)).toBeInTheDocument();
  });

  it("says it is still loading rather than blaming the user for a missing project", () => {
    activeId = undefined;
    projectsLoading = true;
    view();
    expect(screen.getByText("Loading your projects…")).toBeInTheDocument();
    expect(screen.queryByText(/Create a project first/)).not.toBeInTheDocument();
  });

  it("posts the question with the run's settings", () => {
    view();
    fireEvent.change(screen.getByLabelText("Research question"), { target: { value: LONG } });
    fireEvent.click(screen.getByRole("button", { name: "Start research" }));
    expect(mutate).toHaveBeenCalledWith(
      {
        project_id: "p1",
        question: LONG,
        depth: "balanced",
        corpus_mode: false,
        // The run form's default is the design gate ON, which is the opposite of the
        // endpoint's own default — see AGENTS.md on the three `skip_plan_gate` defaults.
        // It is sent explicitly for exactly that reason.
        skip_plan_gate: false,
      },
      expect.anything(),
    );
  });

  it("sends the advanced options a person actually chose", () => {
    view();
    fireEvent.change(screen.getByLabelText("Research question"), { target: { value: LONG } });
    fireEvent.click(screen.getByRole("radio", { name: "Comprehensive" }));
    fireEvent.click(screen.getByRole("button", { name: /Options/ }));
    fireEvent.click(screen.getByRole("checkbox", { name: /Restrict to uploaded corpus/ }));
    fireEvent.click(screen.getByRole("checkbox", { name: /Review the research plan/ }));
    fireEvent.click(screen.getByRole("button", { name: "Start research" }));
    expect(mutate).toHaveBeenCalledWith(
      expect.objectContaining({
        depth: "comprehensive",
        corpus_mode: true,
        // Unticked, so this run skips the design gate.
        skip_plan_gate: true,
      }),
      expect.anything(),
    );
  });

  it("names departures from the default on the closed disclosure, and only those", () => {
    view();
    fireEvent.click(screen.getByRole("button", { name: /Options/ }));
    fireEvent.click(screen.getByRole("checkbox", { name: /Restrict to uploaded corpus/ }));
    fireEvent.click(screen.getByRole("checkbox", { name: /Review the research plan/ }));
    fireEvent.click(screen.getByRole("button", { name: /Options/ }));
    expect(screen.getByText(/Corpus only · No plan review/)).toBeInTheDocument();
  });

  it("says the run will stop at both gates when the defaults are untouched", () => {
    view();
    expect(screen.getByText(/pauses for your plan review before searching/)).toBeInTheDocument();
  });

  it("cannot be submitted twice while the first request is in flight", () => {
    pending = true;
    view();
    fireEvent.change(screen.getByLabelText("Research question"), { target: { value: LONG } });
    const button = screen.getByRole("button", { name: /Starting/ });
    expect(button).toBeDisabled();
    fireEvent.click(button);
    fireEvent.submit(button.closest("form")!);
    expect(mutate).not.toHaveBeenCalled();
  });

  it("says what is happening the moment the run is being opened", () => {
    pending = true;
    view();
    expect(screen.getByText(/Opening the run/)).toBeInTheDocument();
  });
});
