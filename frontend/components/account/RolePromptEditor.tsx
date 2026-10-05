"use client";

import { useEffect, useId, useRef, useState } from "react";
import toast from "react-hot-toast";

import { ResetToDefault } from "@/components/settings/ResetToDefault";
import { ApiError } from "@/lib/api";
import { apiValidationMessage, promptEditorState } from "@/lib/promptOverrides";
import type { PromptDefault } from "@/lib/types";

/**
 * One agent's instruction editor (scope freeze §12), opened from its card on Settings →
 * Agents.
 *
 * It starts from what runs today — the user's override, else the shipped prompt with the
 * system-added untrusted-content instruction removed — and saves real text. Emptying the box
 * is deliberately not a way to reset: an empty prompt is refused, not read as a reset, so the
 * editor names the control to use instead of offering a Save that would fail.
 *
 * Reset to default is here as well as on the card, beside the text it would replace, and
 * means two things. For a customized agent it clears the override (`onReset`) — saving a
 * copy of the shipped text would still be an override, and the run would record the agent
 * as customized. For a shipped agent it only discards unsaved edits; nothing is sent.
 */
export function RolePromptEditor({
  label,
  shipped,
  maxChars,
  saved,
  busy,
  onSave,
  onClose,
  onReset,
}: {
  label: string;
  shipped: PromptDefault;
  maxChars: number;
  saved: string | undefined;
  busy: boolean;
  onSave: (text: string) => Promise<void>;
  onClose: () => void;
  onReset: () => void;
}) {
  const [draft, setDraft] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const box = useRef<HTMLTextAreaElement>(null);
  const id = useId();
  const state = promptEditorState({
    saved,
    draft,
    defaultPrompt: shipped.default_prompt,
    maxChars,
  });

  // The editor opens in response to a button press, so the cursor follows the person there.
  useEffect(() => {
    box.current?.focus();
  }, []);

  const counterId = `${id}-count`;
  const hintId = `${id}-hint`;
  const errorId = `${id}-error`;

  async function save() {
    setError(null);
    try {
      await onSave(state.text);
      toast.success(`${label} instructions saved. They apply to research you start from now on.`);
      onClose();
    } catch (err) {
      setError(
        err instanceof ApiError
          ? apiValidationMessage(err.message)
          : "Could not reach the server. Nothing was changed.",
      );
    }
  }

  function resetToShipped() {
    setError(null);
    if (state.customised) {
      onReset();
      return;
    }
    setDraft(null);
    box.current?.focus();
  }

  const atShipped = !state.customised && state.text === shipped.default_prompt;

  const describedBy = [counterId, state.dirty && state.blank ? hintId : null, error ? errorId : null]
    .filter(Boolean)
    .join(" ");

  return (
    <div className="space-y-2">
      {shipped.untrusted_content_framed && (
        <p role="note" className="text-xs leading-relaxed text-text-muted">
          Whatever you write here, the system also adds its rule for untrusted web content
          before and after it: text retrieved from the web is data, never instructions. That
          rule is not part of what you edit and cannot be removed.
        </p>
      )}
      <textarea
        ref={box}
        aria-label={`Instructions for ${label}`}
        aria-describedby={describedBy}
        aria-invalid={state.tooLong || error !== null}
        className="textarea-base w-full font-mono text-xs leading-relaxed"
        rows={12}
        value={state.text}
        disabled={busy}
        onChange={(e) => {
          setDraft(e.target.value);
          setError(null);
        }}
      />
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-3">
          <span
            id={counterId}
            className={`font-mono text-[0.6875rem] tabular-nums ${
              state.tooLong ? "text-danger" : "text-text-muted"
            }`}
          >
            {state.length.toLocaleString()} / {maxChars.toLocaleString()} characters
            {state.tooLong && " — over the limit"}
          </span>
          <ResetToDefault isDefault={atShipped || busy} onReset={resetToShipped} />
        </div>
        <div className="flex items-center gap-2">
          <button type="button" className="btn btn-ghost" disabled={busy} onClick={onClose}>
            Cancel
          </button>
          <button
            type="button"
            className="btn btn-primary"
            disabled={!state.canSave || busy}
            onClick={save}
          >
            Save instructions
          </button>
        </div>
      </div>
      {state.dirty && state.blank && (
        <p id={hintId} className="text-xs leading-relaxed text-text-secondary">
          An empty prompt is not a reset — an agent needs instructions.{" "}
          {state.customised
            ? "Use Reset to default to go back to the shipped prompt."
            : "Cancel to keep the shipped prompt."}
        </p>
      )}
      {error && (
        <p id={errorId} role="alert" className="text-xs leading-relaxed text-danger">
          {error}
        </p>
      )}
    </div>
  );
}
