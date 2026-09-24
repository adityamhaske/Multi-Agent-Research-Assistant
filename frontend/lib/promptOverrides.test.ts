import { describe, expect, it } from "vitest";

import {
  PROMPT_ROLES,
  apiValidationMessage,
  customisedRoles,
  promptEditorState,
} from "./promptOverrides";

const SHIPPED = "You are the Orchestration Planner.";
const base = { saved: undefined, draft: null, defaultPrompt: SHIPPED, maxChars: 40 };

describe("promptEditorState", () => {
  it("starts from the shipped prompt when the role is not customised", () => {
    const s = promptEditorState(base);
    expect(s.text).toBe(SHIPPED);
    expect(s.customised).toBe(false);
    expect(s.dirty).toBe(false);
    expect(s.canSave).toBe(false);
  });

  it("starts from the saved override when there is one", () => {
    const s = promptEditorState({ ...base, saved: "Plan in three steps." });
    expect(s.text).toBe("Plan in three steps.");
    expect(s.customised).toBe(true);
    expect(s.canSave).toBe(false);
  });

  it("can save an edit", () => {
    const s = promptEditorState({ ...base, draft: "Plan carefully." });
    expect(s.dirty).toBe(true);
    expect(s.canSave).toBe(true);
  });

  it("does not count retyping the starting text as a change", () => {
    expect(promptEditorState({ ...base, draft: SHIPPED }).dirty).toBe(false);
  });

  it.each(["", "   ", "\n\t "])("never offers to save a blank prompt (%j)", (draft) => {
    const s = promptEditorState({ ...base, saved: "Something", draft });
    expect(s.blank).toBe(true);
    expect(s.canSave).toBe(false);
  });

  it("allows exactly the limit and refuses one character over", () => {
    expect(promptEditorState({ ...base, draft: "x".repeat(40) }).canSave).toBe(true);
    const over = promptEditorState({ ...base, draft: "x".repeat(41) });
    expect(over.tooLong).toBe(true);
    expect(over.canSave).toBe(false);
    expect(over.length).toBe(41);
  });
});

describe("customisedRoles", () => {
  it("lists roles holding text, in role order", () => {
    expect(customisedRoles({ synthesizer: "a", planner: "b" })).toEqual(["planner", "synthesizer"]);
  });

  it("does not count a null or missing role as customised", () => {
    expect(customisedRoles({ planner: null })).toEqual([]);
    expect(customisedRoles(null)).toEqual([]);
    expect(customisedRoles(undefined)).toEqual([]);
  });

  it("covers exactly the five public roles", () => {
    expect(PROMPT_ROLES).toEqual(["planner", "executor", "critic", "synthesizer", "chat"]);
  });
});

describe("apiValidationMessage", () => {
  it("drops only the Pydantic label, keeping the API's words", () => {
    expect(
      apiValidationMessage(
        "Value error, prompt override for 'planner' is 2501 characters; the maximum is 2500",
      ),
    ).toBe("prompt override for 'planner' is 2501 characters; the maximum is 2500");
  });

  it("strips each joined message separately", () => {
    expect(apiValidationMessage("Value error, first; Value error, second")).toBe(
      "first; second",
    );
  });

  it("leaves a message without the label untouched", () => {
    expect(apiValidationMessage("Not authenticated")).toBe("Not authenticated");
  });
});
