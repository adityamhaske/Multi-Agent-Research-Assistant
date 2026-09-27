import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { AgentRole, ModelCatalog } from "@/lib/types";

import { ModelPicker } from "./ModelPicker";

/**
 * Settings → Models answers one question — which model each role uses. Agent instructions
 * live on Settings → Agents; this pins that the picker still offers its model selectors and
 * carries nothing of the instruction editor.
 */

const ROLES: AgentRole[] = ["planner", "executor", "critic", "synthesizer", "chat"];
const ROUTING = Object.fromEntries(ROLES.map((r) => [r, "google:gemini"])) as Record<
  AgentRole,
  string
>;

const CATALOG: ModelCatalog = {
  roles: ROLES,
  models: [
    {
      route: "google:gemini",
      provider: "google",
      model_id: "gemini",
      display_name: "Gemini",
      input_per_mtok: 1,
      output_per_mtok: 2,
      context_window: null,
      max_output_tokens: null,
      supports_tools: true,
      supports_structured_output: true,
      notes: "",
      available: true,
    },
  ],
  presets: {},
  preset_names: [],
  available_providers: ["google"],
  effective_routing: ROUTING,
  user_routing: null,
  deployment_routing: ROUTING,
};

const usePromptDefaults = vi.hoisted(() => vi.fn());
const useMe = vi.hoisted(() => vi.fn());

vi.mock("@/hooks/queries", () => ({
  useModelCatalog: () => ({ data: CATALOG, isLoading: false }),
  useCustomEndpointStatus: () => ({ data: { models: [], reachable: false } }),
  useSetModelRouting: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useResetModelRouting: () => ({ mutateAsync: vi.fn(), isPending: false }),
  usePromptDefaults,
  useMe,
}));

describe("Settings → Models", () => {
  it("still offers a model selector for each of the five roles", async () => {
    render(<ModelPicker />);
    await userEvent.click(screen.getByRole("button", { name: "Customize" }));
    for (const label of ["Planner", "Executor", "Critic", "Synthesizer", "Follow-up chat"]) {
      expect(screen.getByRole("combobox", { name: `Model for ${label}` })).toBeInTheDocument();
    }
  });

  it("renders no agent instruction editor, mark or statement", async () => {
    const { container } = render(<ModelPicker />);
    await userEvent.click(screen.getByRole("button", { name: "Customize" }));
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /instructions/i })).not.toBeInTheDocument();
    expect(container.textContent).not.toMatch(/custom instructions|verification bundle/i);
  });

  it("does not load agent instructions at all", () => {
    render(<ModelPicker />);
    expect(usePromptDefaults).not.toHaveBeenCalled();
    expect(useMe).not.toHaveBeenCalled();
  });
});
