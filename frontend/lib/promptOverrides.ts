import type { AgentRole } from "@/lib/types";

/**
 * The rules behind a role's prompt editor (scope freeze §12), kept out of the component so
 * they can be tested without rendering one.
 *
 * The API is the authority on what may be stored; these rules only decide what the editor
 * offers. They stop two requests the API is known to refuse — empty text and text over the
 * limit — because §12 forbids presenting "clear the box" as a reset, and a Save button that
 * sends an empty prompt would be exactly that.
 */

/** Public role order, matching `GET /models/prompt-defaults` and the model picker. */
export const PROMPT_ROLES: readonly AgentRole[] = [
  "planner",
  "executor",
  "critic",
  "synthesizer",
  "chat",
];

export interface PromptEditorInput {
  /** The user's stored override for this role, or undefined when it runs the shipped prompt. */
  saved: string | undefined;
  /** Unsaved edits, or null when the editor shows what is stored. */
  draft: string | null;
  defaultPrompt: string;
  maxChars: number;
}

export interface PromptEditorState {
  /** What the textarea shows. */
  text: string;
  customised: boolean;
  dirty: boolean;
  blank: boolean;
  tooLong: boolean;
  canSave: boolean;
  length: number;
}

export function promptEditorState({
  saved,
  draft,
  defaultPrompt,
  maxChars,
}: PromptEditorInput): PromptEditorState {
  const customised = saved !== undefined;
  // The starting text is what runs today: the user's own override, else the shipped prompt.
  const starting = saved ?? defaultPrompt;
  const text = draft ?? starting;
  const dirty = draft !== null && draft !== starting;
  const blank = text.trim() === "";
  const tooLong = text.length > maxChars;
  return {
    text,
    customised,
    dirty,
    blank,
    tooLong,
    canSave: dirty && !blank && !tooLong,
    length: text.length,
  };
}

/**
 * The roles a user has customised, in role order. A key holding anything but text is not an
 * override — the API never stores one, and the editor must not claim a role it cannot show.
 */
export function customisedRoles(
  overrides: Partial<Record<AgentRole, string | null>> | null | undefined,
): AgentRole[] {
  if (!overrides) return [];
  return PROMPT_ROLES.filter((role) => typeof overrides[role] === "string");
}

const PYDANTIC_VALUE_ERROR = /^Value error, /;

/**
 * An API refusal as the editor shows it (D-4): the API's own words, minus the "Value error, "
 * label Pydantic puts in front of every validator message. `apiFetch` joins a 422's
 * messages with "; ", so each one is stripped separately.
 */
export function apiValidationMessage(message: string): string {
  return message
    .split("; ")
    .map((part) => part.replace(PYDANTIC_VALUE_ERROR, ""))
    .join("; ");
}
