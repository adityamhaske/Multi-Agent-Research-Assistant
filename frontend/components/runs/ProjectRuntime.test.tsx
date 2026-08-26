import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ProjectRuntime } from "./ProjectRuntime";
import type { ModelRouting, RoutingResponse } from "@/lib/types";

let routingState: {
  data?: Partial<RoutingResponse>;
  isLoading?: boolean;
};

vi.mock("@/hooks/queries", () => ({
  useModelRouting: () => routingState,
}));

beforeEach(() => {
  routingState = { data: undefined, isLoading: false };
});

describe("ProjectRuntime", () => {
  it("is collapsed by default, so it cannot compete with the research above it", () => {
    const { container } = render(<ProjectRuntime />);
    const details = container.querySelector("details");
    expect(details).not.toBeNull();
    expect(details).not.toHaveAttribute("open");
  });

  it("heads its content at h2, because it is a top-level section and not part of Project health", () => {
    routingState = { data: { routing: null }, isLoading: false };
    render(<ProjectRuntime />);
    expect(
      screen.getByRole("heading", { name: "Agents this project runs on", level: 2 }),
    ).toBeInTheDocument();
  });

  it("lists each role's route once a routing is resolved", () => {
    routingState = {
      data: {
        routing: { planner: "anthropic:claude-sonnet-5", critic: "ollama:qwen2.5:7b" } as ModelRouting,
      },
      isLoading: false,
    };
    render(<ProjectRuntime />);
    expect(screen.getByText("planner")).toBeInTheDocument();
    expect(screen.getByText("anthropic:claude-sonnet-5")).toBeInTheDocument();
    // A route splits on the FIRST colon only, so a model name containing one must survive
    // intact rather than be truncated for display (AGENTS.md, provider routing rules).
    expect(screen.getByText("ollama:qwen2.5:7b")).toBeInTheDocument();
  });

  it("falls back to the deployment's effective routing when the user has saved no override", () => {
    // `routing` is null on every install where nobody has opened Settings → Models, but the
    // deployment default still resolves and every run dials it. Reading only the override
    // made this section deny models that Settings was listing three clicks away.
    routingState = {
      data: {
        routing: null,
        effective_routing: { planner: "google:gemini-2.5-flash" } as ModelRouting,
      },
      isLoading: false,
    };
    render(<ProjectRuntime />);
    expect(screen.getByText("google:gemini-2.5-flash")).toBeInTheDocument();
    expect(screen.queryByText(/No model routing resolved yet/)).not.toBeInTheDocument();
  });

  it("says routing is unresolved rather than inventing a default", () => {
    routingState = { data: { routing: null }, isLoading: false };
    render(<ProjectRuntime />);
    expect(screen.getByText(/No model routing resolved yet/)).toBeInTheDocument();
  });
});
