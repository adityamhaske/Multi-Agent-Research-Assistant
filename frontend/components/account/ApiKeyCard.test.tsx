import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { User } from "@/lib/types";

import { ApiKeyCard } from "./ApiKeyCard";

/**
 * The active BYOK connection's nickname (PATCH /me/api-key/label).
 *
 * `activeProvider.label` ("Custom Endpoint") is the fixed catalog name every user
 * routed through that provider shares — the behaviour under test is that a saved
 * nickname is what's actually shown, that renaming never touches the key itself,
 * and that the inline editor can't leak a submit into the card's own save-key form
 * (docs/07 §2, Phase 2a).
 */

const setApiKeyLabel = vi.hoisted(() => ({ mutateAsync: vi.fn(), isPending: false }));
const setApiKey = vi.hoisted(() => ({ mutateAsync: vi.fn(), isPending: false, data: undefined }));
const meData = vi.hoisted(() => ({ value: null as Record<string, unknown> | null }));

vi.mock("@/hooks/queries", () => ({
  useMe: () => ({ data: meData.value, isLoading: false }),
  useSetApiKey: () => setApiKey,
  useDeleteApiKey: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useSetApiKeyLabel: () => setApiKeyLabel,
  useProviderHealth: () => ({ data: null, isFetching: false, refetch: vi.fn() }),
}));

const BASE_USER: User = {
  id: "u1",
  email: "a@example.com",
  is_active: true,
  created_at: "2026-01-01T00:00:00Z",
  display_name: null,
  avatar_url: null,
  monthly_token_limit: 0,
  api_key_provider: "custom",
  api_key_hint: "…c9c5",
  api_key_label: null,
  api_key_set_at: "2026-08-01T00:00:00Z",
  preferences: {},
};

function setUp(user: Partial<typeof BASE_USER> = {}) {
  meData.value = { ...BASE_USER, ...user };
  setApiKeyLabel.mutateAsync.mockReset().mockResolvedValue({ ...BASE_USER, ...user });
  setApiKey.mutateAsync.mockReset();
  return render(<ApiKeyCard />);
}

describe("renaming the active connection", () => {
  it("shows the catalog label alone until a nickname is set", () => {
    setUp();
    // Twice: once as the connection's own name, once as the Provider <select>'s
    // "Custom Endpoint" option — getAllByText is the honest query here, not a
    // scoped one, precisely because the two are supposed to read identically.
    expect(screen.getAllByText("Custom Endpoint")).toHaveLength(2);
    expect(screen.queryByText("(Custom Endpoint)")).not.toBeInTheDocument();
  });

  it("shows a saved nickname as the primary name, with the catalog label kept alongside", () => {
    setUp({ api_key_label: "OmniRoute" });
    expect(screen.getByText("OmniRoute")).toBeInTheDocument();
    expect(screen.getByText("(Custom Endpoint)")).toBeInTheDocument();
    // Only the <select> option reads as the bare label now — the connection's own
    // name switched over to the nickname.
    expect(screen.getAllByText("Custom Endpoint")).toHaveLength(1);
  });

  it("opens an editor seeded with the current nickname, saves it, and closes", async () => {
    setUp({ api_key_label: "OmniRoute" });
    await userEvent.click(screen.getByRole("button", { name: "Rename" }));

    const input = screen.getByLabelText("Connection nickname");
    expect(input).toHaveValue("OmniRoute");
    await userEvent.clear(input);
    await userEvent.type(input, "Work vLLM");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(setApiKeyLabel.mutateAsync).toHaveBeenCalledWith("Work vLLM");
    expect(screen.queryByLabelText("Connection nickname")).not.toBeInTheDocument();
  });

  it("saves on Enter without submitting the card's own save-key form", async () => {
    setUp();
    await userEvent.click(screen.getByRole("button", { name: "Rename" }));
    const input = screen.getByLabelText("Connection nickname");
    await userEvent.type(input, "OmniRoute{Enter}");

    expect(setApiKeyLabel.mutateAsync).toHaveBeenCalledWith("OmniRoute");
    // The outer form's own submit path (PUT /me/api-key) must be untouched by Enter here.
    expect(setApiKey.mutateAsync).not.toHaveBeenCalled();
  });

  it("discards the draft on Cancel without saving anything", async () => {
    setUp({ api_key_label: "OmniRoute" });
    await userEvent.click(screen.getByRole("button", { name: "Rename" }));
    await userEvent.type(screen.getByLabelText("Connection nickname"), " (edited)");
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));

    expect(setApiKeyLabel.mutateAsync).not.toHaveBeenCalled();
    expect(screen.getByText("OmniRoute")).toBeInTheDocument();
  });

  it("offers no rename control at all without an active connection", () => {
    setUp({ api_key_provider: null, api_key_hint: null, api_key_label: null });
    expect(screen.queryByRole("button", { name: "Rename" })).not.toBeInTheDocument();
  });

  it("blanking the field back out is a valid save (clears to the catalog label)", async () => {
    setUp({ api_key_label: "OmniRoute" });
    await userEvent.click(screen.getByRole("button", { name: "Rename" }));
    await userEvent.clear(screen.getByLabelText("Connection nickname"));
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(setApiKeyLabel.mutateAsync).toHaveBeenCalledWith("");
  });
});
