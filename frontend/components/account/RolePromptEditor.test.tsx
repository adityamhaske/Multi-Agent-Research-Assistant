import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";
import type { PromptDefault } from "@/lib/types";

import { RolePromptEditor } from "./RolePromptEditor";

/**
 * One agent's instruction editor (scope freeze §12): it starts from what runs today, saves
 * real text, and never turns an emptied box into a save. Its reset is covered below; the
 * card's own reset, and the editor's reaching the API, in `AgentsSection.test.tsx`.
 */

type Save = (text: string) => Promise<void>;
type Close = () => void;
type Reset = () => void;

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
  onClose = vi.fn<Close>(),
  onReset = vi.fn<Reset>(),
  maxChars = 60,
}: {
  shipped?: PromptDefault;
  saved?: string;
  onSave?: ReturnType<typeof vi.fn<Save>>;
  onClose?: ReturnType<typeof vi.fn<Close>>;
  onReset?: ReturnType<typeof vi.fn<Reset>>;
  maxChars?: number;
} = {}) {
  render(
    <RolePromptEditor
      label="Planner"
      shipped={shipped}
      maxChars={maxChars}
      saved={saved}
      busy={false}
      onSave={onSave}
      onClose={onClose}
      onReset={onReset}
    />,
  );
  const box = screen.getByRole("textbox", { name: "Instructions for Planner" });
  return { box, onSave, onClose, onReset };
}

describe("what the editor starts from", () => {
  it("shows the shipped prompt when the agent is not customized", () => {
    expect(setUp().box).toHaveValue(PLANNER.default_prompt);
  });

  it("shows the user's own text when the agent is customized", () => {
    expect(setUp({ saved: "Plan in three steps." }).box).toHaveValue("Plan in three steps.");
  });

  it("takes focus when it opens", () => {
    expect(setUp().box).toHaveFocus();
  });

  it("says the untrusted-content rule is added, for an agent that gets it", () => {
    setUp({ shipped: CRITIC });
    expect(screen.getByRole("note")).toHaveTextContent(/cannot be removed/);
  });

  it("says nothing about it for an agent that does not", () => {
    setUp();
    expect(screen.queryByRole("note")).not.toBeInTheDocument();
  });
});

describe("saving", () => {
  it("offers nothing to save until the text changes", () => {
    setUp();
    expect(screen.getByRole("button", { name: "Save instructions" })).toBeDisabled();
  });

  it("saves the edited text, then closes", async () => {
    const { box, onSave, onClose } = setUp();
    await userEvent.clear(box);
    await userEvent.type(box, "Plan carefully.");
    await userEvent.click(screen.getByRole("button", { name: "Save instructions" }));
    expect(onSave).toHaveBeenCalledWith("Plan carefully.");
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it.each(["", "   "])("never saves a blank prompt, and says what to use instead (%j)", async (text) => {
    const { box, onSave } = setUp({ saved: "Plan in three steps." });
    await userEvent.clear(box);
    if (text) await userEvent.type(box, text);
    expect(screen.getByRole("button", { name: "Save instructions" })).toBeDisabled();
    expect(screen.getByText(/An empty prompt is not a reset/)).toHaveTextContent(
      /Reset to default/,
    );
    expect(onSave).not.toHaveBeenCalled();
  });

  it("tells a shipped agent's editor to cancel rather than save an empty box", async () => {
    const { box } = setUp();
    await userEvent.clear(box);
    expect(screen.getByText(/An empty prompt is not a reset/)).toHaveTextContent(
      /Cancel to keep the shipped prompt/,
    );
  });

  it("refuses text over the limit and says so on the counter", async () => {
    const { box } = setUp({ maxChars: 10 });
    await userEvent.clear(box);
    await userEvent.type(box, "x".repeat(11));
    expect(screen.getByRole("button", { name: "Save instructions" })).toBeDisabled();
    expect(screen.getByText(/11 \/ 10 characters — over the limit/)).toBeInTheDocument();
  });

  it("shows an API refusal inline, in the API's words, and stays open", async () => {
    const onSave = vi
      .fn<Save>()
      .mockRejectedValue(
        new ApiError(
          422,
          "Value error, prompt override for 'planner' is 61 characters; the maximum is 60",
        ),
      );
    const { box, onClose } = setUp({ onSave });
    await userEvent.type(box, " More.");
    await userEvent.click(screen.getByRole("button", { name: "Save instructions" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "prompt override for 'planner' is 61 characters; the maximum is 60",
    );
    expect(screen.getByRole("alert")).not.toHaveTextContent("Value error");
    expect(onClose).not.toHaveBeenCalled();
  });

  it("cancels without saving", async () => {
    const { box, onSave, onClose } = setUp();
    await userEvent.type(box, " edited");
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(onSave).not.toHaveBeenCalled();
  });
});

describe("resetting to the shipped prompt from inside the editor", () => {
  const reset = () => screen.queryByRole("button", { name: "Reset to default" });

  it("offers nothing while the shipped text is untouched — there is nothing to go back to", () => {
    setUp();
    expect(reset()).toBeNull();
  });

  it("puts the shipped text back after an edit, without saving anything", async () => {
    const { box, onSave, onReset } = setUp();
    await userEvent.type(box, " Add a timeline task.");
    await userEvent.click(reset()!);
    expect(box).toHaveValue(PLANNER.default_prompt);
    expect(onSave).not.toHaveBeenCalled();
    expect(onReset).not.toHaveBeenCalled();
    expect(reset()).toBeNull();
  });

  it("on a customized agent, clears the override rather than saving a copy of the shipped text", async () => {
    // A copy would still be an override — the run would record the agent as customized.
    const { onSave, onReset } = setUp({ saved: "Plan in three steps." });
    await userEvent.click(reset()!);
    expect(onReset).toHaveBeenCalledOnce();
    expect(onSave).not.toHaveBeenCalled();
  });
});
