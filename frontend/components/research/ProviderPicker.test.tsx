import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import {
  defaultKind,
  isKindReady,
  isUnpricedRoute,
  ProviderPicker,
  routeForKind,
  routingFor,
  splitRoute,
} from "./ProviderPicker";

/**
 * The run form's whole model decision: which backend, and is it up.
 *
 * The behaviour under test is mostly about not lying — showing what a run will really be
 * routed to, marking a dead endpoint dead, and never quietly substituting one backend for
 * another when the chosen one is down.
 */

const catalog = vi.hoisted(() => ({ value: {} as Record<string, unknown> }));
const custom = vi.hoisted(() => ({ value: {} as Record<string, unknown> }));
const local = vi.hoisted(() => ({ value: {} as Record<string, unknown> }));

vi.mock("@/hooks/queries", () => ({
  useModelCatalog: () => catalog.value,
  useCustomEndpointStatus: () => custom.value,
  useLocalLLMStatus: () => local.value,
}));

const CATALOG = {
  user_routing: null,
  deployment_routing: routingFor("custom:auto/best-fast"),
  models: [
    {
      route: "google:gemini-2.5-pro",
      provider: "google",
      display_name: "Gemini 2.5 Pro",
      available: true,
    },
  ],
};
const LOCAL = {
  models: [{ name: "qwen2.5:7b", route: "ollama:qwen2.5:7b", is_embedding: false }],
};
const CUSTOM = { reachable: true, models: ["auto/best-fast"], configured_base_url: "http://x/v1" };

function setUp({ cat = CATALOG, cus = CUSTOM, loc = LOCAL } = {}) {
  catalog.value = { data: cat, isLoading: false };
  custom.value = { data: cus, isLoading: false };
  local.value = { data: loc, isLoading: false };
  return { cat, cus, loc };
}

describe("backend resolution", () => {
  it("prefers the custom endpoint, then local, then API", () => {
    // The order the user asked for, and the order the buttons are shown in.
    expect(defaultKind(CATALOG, CUSTOM, LOCAL)).toBe("custom");
    expect(defaultKind(CATALOG, { ...CUSTOM, reachable: false }, LOCAL)).toBe("local");
    expect(
      defaultKind(CATALOG, { ...CUSTOM, reachable: false }, { models: [] }),
    ).toBe("api");
  });

  it("returns null while nothing is reachable, rather than guessing", () => {
    // A button that appears selected and then moves is worse than one that arrives late.
    const bare = { user_routing: null, deployment_routing: null, models: [] };
    expect(defaultKind(bare, { ...CUSTOM, reachable: false }, { models: [] })).toBeNull();
  });

  it("honours a model chosen in Settings over the deployment's own default", () => {
    // Moving model choice into Settings is only real if the run form obeys it.
    const withSaved = { ...CATALOG, user_routing: routingFor("custom:my/pinned-model") };
    expect(routeForKind("custom", withSaved, CUSTOM, LOCAL)).toBe("custom:my/pinned-model");
  });

  it("falls back to the deployment's configured route when Settings names none", () => {
    expect(routeForKind("custom", CATALOG, CUSTOM, LOCAL)).toBe("custom:auto/best-fast");
  });

  it("picks an installed local model by its exact tag", () => {
    expect(routeForKind("local", CATALOG, CUSTOM, LOCAL)).toBe("ollama:qwen2.5:7b");
    expect(splitRoute("ollama:qwen2.5:7b")).toEqual({ provider: "ollama", model: "qwen2.5:7b" });
  });

  it("reports a backend with nothing configured as null, not as an empty route", () => {
    expect(routeForKind("local", CATALOG, CUSTOM, { models: [] })).toBeNull();
    expect(isKindReady("local", CATALOG, CUSTOM, { models: [] })).toBe(false);
  });

  it("knows which backends have no measurable cost", () => {
    expect(isUnpricedRoute("custom:auto/best-fast")).toBe(true);
    expect(isUnpricedRoute("openrouter:meta/llama")).toBe(true);
    // Local is genuinely free — a different statement from unknown.
    expect(isUnpricedRoute("ollama:qwen2.5:7b")).toBe(false);
    expect(isUnpricedRoute("google:gemini-2.5-pro")).toBe(false);
  });
});

describe("ProviderPicker", () => {
  it("offers exactly three backends", () => {
    setUp();
    render(<ProviderPicker value="custom" onChange={vi.fn()} />);
    expect(screen.getAllByRole("radio")).toHaveLength(3);
    for (const label of ["Custom Endpoint", "Local LLM", "API"]) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
  });

  it("shows the route each backend will actually use", () => {
    setUp();
    render(<ProviderPicker value="custom" onChange={vi.fn()} />);
    expect(screen.getByText("custom:auto/best-fast")).toBeInTheDocument();
    expect(screen.getByText("ollama:qwen2.5:7b")).toBeInTheDocument();
  });

  it("marks a stopped endpoint stopped in text, not only in colour", () => {
    // The dot is decorative; the word is what a screen reader gets.
    setUp({ cus: { ...CUSTOM, reachable: false } });
    render(<ProviderPicker value="local" onChange={vi.fn()} />);
    expect(screen.getByText("Custom Endpoint is stopped")).toBeInTheDocument();
    expect(screen.getByText("Local LLM is running")).toBeInTheDocument();
  });

  it("says a chosen dead backend will fail rather than switching provider", () => {
    // The rule this guards: a silent substitution would make the finished report's
    // attribution the first place it became visible.
    setUp({ cus: { ...CUSTOM, reachable: false } });
    render(<ProviderPicker value="custom" onChange={vi.fn()} />);
    expect(screen.getByRole("alert")).toHaveTextContent(/will fail rather than switch/i);
  });

  it("does not warn when the chosen backend is up", () => {
    setUp();
    render(<ProviderPicker value="custom" onChange={vi.fn()} />);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("reports the user's choice", async () => {
    setUp();
    const onChange = vi.fn();
    render(<ProviderPicker value="custom" onChange={onChange} />);
    await userEvent.click(screen.getByRole("radio", { name: /local llm/i }));
    expect(onChange).toHaveBeenCalledWith("local");
  });

  it("points at Settings for the model itself", () => {
    setUp();
    render(<ProviderPicker value="custom" onChange={vi.fn()} />);
    expect(screen.getByText(/Settings → Models/)).toBeInTheDocument();
  });
});
