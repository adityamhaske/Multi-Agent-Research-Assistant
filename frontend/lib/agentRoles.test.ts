import { describe, expect, it } from "vitest";

import type { ModelCatalog } from "@/lib/types";

import { ROLE_COPY, roleModelLabel } from "./agentRoles";

const catalog = {
  roles: ["planner", "executor", "critic", "synthesizer", "chat"],
  models: [
    {
      route: "anthropic:claude-sonnet",
      provider: "anthropic",
      model_id: "claude-sonnet",
      display_name: "Claude Sonnet",
    },
  ],
  effective_routing: {
    planner: "anthropic:claude-sonnet",
    executor: "custom:auto/best-fast",
    critic: "ollama:qwen2.5:7b",
    synthesizer: "anthropic:claude-sonnet",
  },
} as unknown as ModelCatalog;

describe("roleModelLabel", () => {
  it("names a catalogued model by its display name", () => {
    expect(roleModelLabel(catalog, "planner")).toBe("Claude Sonnet");
  });

  it("shows an uncatalogued route's model id, split on the first colon only", () => {
    expect(roleModelLabel(catalog, "executor")).toBe("auto/best-fast");
    expect(roleModelLabel(catalog, "critic")).toBe("qwen2.5:7b");
  });

  it("says nothing rather than guessing when the role is unrouted or the catalog is absent", () => {
    expect(roleModelLabel(catalog, "chat")).toBeNull();
    expect(roleModelLabel(undefined, "planner")).toBeNull();
  });
});

describe("ROLE_COPY", () => {
  it("describes exactly the five public roles", () => {
    expect(Object.keys(ROLE_COPY)).toEqual(["planner", "executor", "critic", "synthesizer", "chat"]);
  });
});
