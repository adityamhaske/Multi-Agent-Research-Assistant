import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { AgentRole, ModelCatalog, PromptDefaults, User } from "@/lib/types";

import { AgentsSection } from "./AgentsSection";

/**
 * Settings → Agents: how each agent behaves, apart from which model it uses (scope freeze
 * §12). Exactly the five public roles, a visible shipped/customized state, one editor at a
 * time, reset through `ResetToDefault` sending `null`, the model shown read-only with a way
 * to where it is changed — and nothing that creates an agent or names a protected purpose.
 */

const ROLES: AgentRole[] = ["planner", "executor", "critic", "synthesizer", "chat"];
const LABELS = ["Planner", "Executor", "Critic", "Synthesizer", "Follow-up chat"];

const DEFAULTS: PromptDefaults = {
  max_chars: 2500,
  roles: ROLES.map((role) => ({
    role,
    default_prompt: `Shipped ${role} prompt.`,
    untrusted_content_framed: role !== "planner",
  })),
};

const CATALOG = {
  roles: ROLES,
  models: [
    {
      route: "anthropic:claude-sonnet",
      provider: "anthropic",
      model_id: "claude-sonnet",
      display_name: "Claude Sonnet",
    },
  ],
  effective_routing: Object.fromEntries(ROLES.map((r) => [r, "anthropic:claude-sonnet"])),
} as unknown as ModelCatalog;

const updateProfile = vi.hoisted(() => ({ mutateAsync: vi.fn(), isPending: false }));
const state = vi.hoisted(() => ({
  me: null as User | null,
  defaults: { data: undefined as PromptDefaults | undefined, isLoading: false, isError: false },
}));

vi.mock("@/hooks/queries", () => ({
  useMe: () => ({ data: state.me, isLoading: false }),
  usePromptDefaults: () => state.defaults,
  useModelCatalog: () => ({ data: CATALOG }),
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

function show(overrides: Partial<Record<AgentRole, string>> | null = null) {
  state.me = user(overrides);
  state.defaults = { data: DEFAULTS, isLoading: false, isError: false };
  return render(<AgentsSection />);
}

const card = (label: string) => screen.getByRole("listitem", { name: label });

beforeEach(() => {
  updateProfile.mutateAsync.mockReset().mockResolvedValue(user(null));
});

describe("the page", () => {
  it("says what it is for", () => {
    show();
    expect(screen.getByText("Customize how your research agents behave.")).toBeInTheDocument();
  });

  it("lists exactly the five public agents, in order", () => {
    show();
    const items = within(screen.getByRole("list", { name: "Agents" })).getAllByRole("listitem");
    expect(items.map((li) => li.getAttribute("aria-label"))).toEqual(LABELS);
  });

  it("states that customization is recorded in the artifact and needs a current verifier", () => {
    show();
    expect(screen.getByText(/verification bundle records them in full/)).toHaveTextContent(
      /format v2, which a verifier from before this release refuses/,
    );
  });

  it("opens no editor until asked", () => {
    show();
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
  });

  it("offers no way to create an agent", () => {
    show();
    expect(screen.queryByRole("button", { name: /create|add|new/i })).not.toBeInTheDocument();
  });

  it("never names a protected purpose, even with every editor opened in turn", async () => {
    const { container } = show({ critic: "Grade harshly." });
    for (const label of LABELS) {
      const button = within(card(label)).getByRole("button", {
        name: /Customize|Edit instructions/,
      });
      await userEvent.click(button);
      await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    }
    for (const name of ["citation_verify", "contradiction_detector", "synthesizer.repair", "chat.project"]) {
      expect(container.textContent).not.toContain(name);
    }
  });
});

describe("each agent's state", () => {
  it("marks a shipped agent as shipped and offers Customize", () => {
    show();
    const planner = card("Planner");
    expect(within(planner).getByText("Shipped")).toBeInTheDocument();
    expect(within(planner).getByRole("button", { name: "Customize" })).toBeInTheDocument();
    expect(within(planner).queryByRole("button", { name: "Reset to default" })).not.toBeInTheDocument();
  });

  it("marks a customized agent and offers Edit instructions and Reset to default", () => {
    show({ critic: "Grade harshly." });
    const critic = card("Critic");
    expect(within(critic).getByText("Customized")).toBeInTheDocument();
    expect(within(critic).getByRole("button", { name: "Edit instructions" })).toBeInTheDocument();
    expect(within(critic).getByRole("button", { name: "Reset to default" })).toBeInTheDocument();
    expect(within(card("Planner")).getByText("Shipped")).toBeInTheDocument();
  });
});

describe("editing", () => {
  it("Customize opens that agent's editor on the shipped text", async () => {
    show();
    await userEvent.click(within(card("Executor")).getByRole("button", { name: "Customize" }));
    expect(screen.getByRole("textbox", { name: "Instructions for Executor" })).toHaveValue(
      "Shipped executor prompt.",
    );
  });

  it("Edit instructions opens that agent's editor on the saved text", async () => {
    show({ critic: "Grade harshly." });
    await userEvent.click(within(card("Critic")).getByRole("button", { name: "Edit instructions" }));
    expect(screen.getByRole("textbox", { name: "Instructions for Critic" })).toHaveValue(
      "Grade harshly.",
    );
  });

  it("keeps one editor open at a time", async () => {
    show();
    await userEvent.click(within(card("Planner")).getByRole("button", { name: "Customize" }));
    expect(screen.getAllByRole("textbox")).toHaveLength(1);
    expect(within(card("Critic")).getByRole("button", { name: "Customize" })).toBeDisabled();
  });

  it("saves that agent's text alone", async () => {
    show();
    await userEvent.click(within(card("Critic")).getByRole("button", { name: "Customize" }));
    const box = screen.getByRole("textbox", { name: "Instructions for Critic" });
    await userEvent.clear(box);
    await userEvent.type(box, "Grade harshly.");
    await userEvent.click(screen.getByRole("button", { name: "Save instructions" }));
    expect(updateProfile.mutateAsync).toHaveBeenCalledWith({
      preferences: { prompt_overrides: { critic: "Grade harshly." } },
    });
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
  });

  it("keeps the API's validation: a refusal shows inline and the editor stays open", async () => {
    updateProfile.mutateAsync.mockRejectedValue(
      new (await import("@/lib/api")).ApiError(
        422,
        "Value error, prompt override for 'critic' is 2501 characters; the maximum is 2500",
      ),
    );
    show();
    await userEvent.click(within(card("Critic")).getByRole("button", { name: "Customize" }));
    await userEvent.type(screen.getByRole("textbox"), " more");
    await userEvent.click(screen.getByRole("button", { name: "Save instructions" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "prompt override for 'critic' is 2501 characters; the maximum is 2500",
    );
    expect(screen.getByRole("textbox")).toBeInTheDocument();
  });
});

describe("resetting", () => {
  it("sends null for that agent alone", async () => {
    show({ critic: "Grade harshly.", planner: "Plan in three steps." });
    await userEvent.click(within(card("Critic")).getByRole("button", { name: "Reset to default" }));
    expect(updateProfile.mutateAsync).toHaveBeenCalledWith({
      preferences: { prompt_overrides: { critic: null } },
    });
  });
});

describe("the model, read-only", () => {
  it("shows each agent's current model and links to Models to change it", () => {
    show();
    const planner = card("Planner");
    expect(within(planner).getByText(/Model: Claude Sonnet/)).toBeInTheDocument();
    expect(within(planner).getByRole("link", { name: "Change in Models" })).toHaveAttribute(
      "href",
      "/settings/models",
    );
  });

  it("offers no model selector of its own", () => {
    show();
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  });
});

describe("loading and failure", () => {
  it("shows a placeholder while loading", () => {
    state.me = user(null);
    state.defaults = { data: undefined, isLoading: true, isError: false };
    render(<AgentsSection />);
    expect(screen.queryByRole("list", { name: "Agents" })).not.toBeInTheDocument();
  });

  it("says the instructions could not be loaded, and offers nothing to edit", () => {
    state.me = user(null);
    state.defaults = { data: undefined, isLoading: false, isError: true };
    render(<AgentsSection />);
    expect(screen.getByText(/could not be loaded/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Customize|Edit instructions/ })).not.toBeInTheDocument();
  });
});
