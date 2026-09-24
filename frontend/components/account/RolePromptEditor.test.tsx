import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";
import type { PromptDefault } from "@/lib/types";

import { RolePromptEditor } from "./RolePromptEditor";

/**
 * One role's prompt editor (scope freeze §12): it starts from what runs today, saves real
 * text, resets through its own control, and never turns an emptied box into a save.
 */

type Save = (text: string) => Promise<void>;
type Reset = () => Promise<void>;

const PLANNER: PromptDefault = {
  role: "planner",
  default_prompt: "You are the Orchestration Planner.",
  untrusted_content_framed: false,
};
const CRITIC: PromptDefault = {
  role: "critic",
  default_prompt: "You are the Quality Critic.",
  untrusted_content_framed: true,
};

function setUp({
  shipped = PLANNER,
  saved,
  onSave = vi.fn<Save>().mockResolvedValue(undefined),
  onReset = vi.fn<Reset>().mockResolvedValue(undefined),
  maxChars = 60,
}: {
  shipped?: PromptDefault;
  saved?: string;
  onSave?: ReturnType<typeof vi.fn<Save>>;
  onReset?: ReturnType<typeof vi.fn<Reset>>;
  maxChars?: number;
} = {}) {
  const utils = render(
    <RolePromptEditor
      label="Planner"
      shipped={shipped}
      maxChars={maxChars}
      saved={saved}
      busy={false}
      onSave={onSave}
      onReset={onReset}
    />,
  );
  return { ...utils, onSave, onReset };
}

async function open() {
  await userEvent.click(screen.getByRole("button", { name: /instructions/i }));
  return screen.getByRole("textbox", { name: "Instructions for Planner" });
}

describe("what the editor starts from", () => {
  it("shows the shipped prompt when the role is not customised", async () => {
    setUp();
    expect(screen.getByText("shipped default")).toBeInTheDocument();
    expect(await open()).toHaveValue(PLANNER.default_prompt);
  });

  it("shows the user's own text when the role is customised", async () => {
    setUp({ saved: "Plan in three steps." });
    expect(screen.getByText("custom")).toBeInTheDocument();
    expect(await open()).toHaveValue("Plan in three steps.");
  });

  it("says the untrusted-content rule is added, for a role that gets it", async () => {
    setUp({ shipped: CRITIC });
    await open();
    expect(screen.getByRole("note")).toHaveTextContent(/cannot be removed/);
  });

  it("says nothing about it for a role that does not", async () => {
    setUp();
    await open();
    expect(screen.queryByRole("note")).not.toBeInTheDocument();
  });
});

describe("saving", () => {
  it("offers nothing to save until the text changes", async () => {
    setUp();
    await open();
    expect(screen.getByRole("button", { name: "Save instructions" })).toBeDisabled();
  });

  it("saves the edited text", async () => {
    const { onSave } = setUp();
    const box = await open();
    await userEvent.clear(box);
    await userEvent.type(box, "Plan carefully.");
    await userEvent.click(screen.getByRole("button", { name: "Save instructions" }));
    expect(onSave).toHaveBeenCalledWith("Plan carefully.");
  });

  it.each(["", "   "])("never saves a blank prompt, and says what to use instead (%j)", async (text) => {
    const { onSave } = setUp({ saved: "Plan in three steps." });
    const box = await open();
    await userEvent.clear(box);
    if (text) await userEvent.type(box, text);
    expect(screen.getByRole("button", { name: "Save instructions" })).toBeDisabled();
    expect(screen.getByText(/An empty prompt is not a reset/)).toHaveTextContent(
      /Reset to default/,
    );
    expect(onSave).not.toHaveBeenCalled();
  });

  it("refuses text over the limit and says so on the counter", async () => {
    setUp({ maxChars: 10 });
    const box = await open();
    await userEvent.clear(box);
    await userEvent.type(box, "x".repeat(11));
    expect(screen.getByRole("button", { name: "Save instructions" })).toBeDisabled();
    expect(screen.getByText(/11 \/ 10 characters — over the limit/)).toBeInTheDocument();
  });

  it("shows an API refusal inline, in the API's words", async () => {
    const onSave = vi
      .fn<Save>()
      .mockRejectedValue(
        new ApiError(422, "Value error, prompt override for 'planner' is 61 characters; the maximum is 60"),
      );
    setUp({ onSave });
    const box = await open();
    await userEvent.type(box, " More.");
    await userEvent.click(screen.getByRole("button", { name: "Save instructions" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "prompt override for 'planner' is 61 characters; the maximum is 60",
    );
    expect(screen.getByRole("alert")).not.toHaveTextContent("Value error");
  });
});

describe("resetting", () => {
  it("is offered only for a customised role", async () => {
    setUp();
    await open();
    expect(screen.queryByRole("button", { name: "Reset to default" })).not.toBeInTheDocument();
  });

  it("goes through its own control, not an emptied box", async () => {
    const { onReset, onSave } = setUp({ saved: "Plan in three steps." });
    await open();
    await userEvent.click(screen.getByRole("button", { name: "Reset to default" }));
    expect(onReset).toHaveBeenCalledTimes(1);
    expect(onSave).not.toHaveBeenCalled();
  });
});

describe("what it never shows", () => {
  it.each(["citation_verify", "contradiction_detector", "synthesizer.repair", "chat.project"])(
    "does not mention %s",
    async (name) => {
      const { container } = setUp({ shipped: CRITIC });
      await open();
      expect(container.textContent).not.toContain(name);
    },
  );
});
