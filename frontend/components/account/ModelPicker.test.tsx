import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { AgentRole, ModelCatalog, PromptDefaults, User } from "@/lib/types";

import { ModelPicker } from "./ModelPicker";

/**
 * The prompt editors live on the model picker's existing per-role rows (scope freeze §12):
 * no new page, a visible mark on a customised role, a reset that sends `null`, and the
 * statement that customisation is recorded in the artifact and needs a current verifier.
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

const DEFAULTS: PromptDefaults = {
  max_chars: 2500,
  roles: ROLES.map((role) => ({
    role,
    default_prompt: `Shipped ${role} prompt.`,
    untrusted_content_framed: role !== "planner",
  })),
};

const updateProfile = vi.hoisted(() => ({ mutateAsync: vi.fn(), isPending: false }));
const me = vi.hoisted(() => ({ value: null as User | null }));

vi.mock("@/hooks/queries", () => ({
  useModelCatalog: () => ({ data: CATALOG, isLoading: false }),
  useCustomEndpointStatus: () => ({ data: { models: [], reachable: false } }),
  useSetModelRouting: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useResetModelRouting: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useMe: () => ({ data: me.value }),
  usePromptDefaults: () => ({ data: DEFAULTS }),
  useUpdateProfile: () => updateProfile,
}));

function user(prompt_overrides: Partial<Record<AgentRole, string>> | null): User {
  return {
    id: "u1",
    email: "a@example.com",
    is_active: true,
    created_at: "2026-01-01T00:00:00Z",
    display_name: null,
    avatar_url: null,
    monthly_token_limit: 0,
    api_key_provider: null,
    api_key_hint: null,
    api_key_label: null,
    api_key_set_at: null,
    preferences: { prompt_overrides },
  };
}

async function openRoles() {
  await userEvent.click(screen.getByRole("button", { name: "Customize" }));
}

beforeEach(() => {
  updateProfile.mutateAsync.mockReset().mockResolvedValue(user(null));
});

describe("the customised mark", () => {
  it("counts customised roles in the footer, visible with the roles drawer closed", () => {
    me.value = user({ planner: "Plan in three steps.", critic: "Grade harshly." });
    render(<ModelPicker />);
    expect(screen.getByText(/2 roles use custom instructions\./)).toBeInTheDocument();
  });

  it("says nothing when no role is customised", () => {
    me.value = user(null);
    render(<ModelPicker />);
    expect(screen.queryByText(/custom instructions\./)).not.toBeInTheDocument();
  });

  it("marks exactly the customised roles on their rows", async () => {
    me.value = user({ critic: "Grade harshly." });
    render(<ModelPicker />);
    await openRoles();
    expect(screen.getAllByText("Custom instructions")).toHaveLength(1);
  });
});

describe("the editors", () => {
  it("puts one on each of the five existing role rows", async () => {
    me.value = user(null);
    render(<ModelPicker />);
    await openRoles();
    expect(screen.getAllByRole("button", { name: /^Instructions/ })).toHaveLength(5);
  });

  it("states that customisation is recorded in the artifact and needs a current verifier", async () => {
    me.value = user(null);
    render(<ModelPicker />);
    await openRoles();
    expect(screen.getByText(/verification bundle records them in full/)).toHaveTextContent(
      /format v2, which a verifier from before this release refuses/,
    );
  });

  it("resets a role by sending null for that role alone", async () => {
    me.value = user({ planner: "Plan in three steps." });
    render(<ModelPicker />);
    await openRoles();
    await userEvent.click(screen.getAllByRole("button", { name: /^Instructions/ })[0]);
    await userEvent.click(screen.getByRole("button", { name: "Reset to default" }));
    expect(updateProfile.mutateAsync).toHaveBeenCalledWith({
      preferences: { prompt_overrides: { planner: null } },
    });
  });

  it("saves a role's text under that role alone", async () => {
    me.value = user(null);
    render(<ModelPicker />);
    await openRoles();
    await userEvent.click(screen.getAllByRole("button", { name: /^Instructions/ })[2]);
    const box = screen.getByRole("textbox", { name: "Instructions for Critic" });
    await userEvent.clear(box);
    await userEvent.type(box, "Grade harshly.");
    await userEvent.click(screen.getByRole("button", { name: "Save instructions" }));
    expect(updateProfile.mutateAsync).toHaveBeenCalledWith({
      preferences: { prompt_overrides: { critic: "Grade harshly." } },
    });
  });

  it("never names a protected purpose", async () => {
    me.value = user({ critic: "Grade harshly." });
    const { container } = render(<ModelPicker />);
    await openRoles();
    for (const toggle of screen.getAllByRole("button", { name: /^Instructions/ })) {
      await userEvent.click(toggle);
    }
    for (const name of [
      "citation_verify",
      "contradiction_detector",
      "synthesizer.repair",
      "chat.project",
    ]) {
      expect(container.textContent).not.toContain(name);
    }
    expect(within(container).getAllByRole("textbox")).toHaveLength(5);
  });
});
