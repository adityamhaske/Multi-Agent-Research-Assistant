"use client";

import { useId, useState } from "react";
import toast from "react-hot-toast";

import { ResetToDefault } from "@/components/settings/ResetToDefault";
import { Disclosure } from "@/components/ui/Disclosure";
import { ApiError } from "@/lib/api";
import { apiValidationMessage, promptEditorState } from "@/lib/promptOverrides";
import type { PromptDefault } from "@/lib/types";

/**
 * One role's replacement system prompt (scope freeze §12).
 *
 * It starts from what runs today — the user's override, else the shipped prompt with the
 * system-added untrusted-content instruction removed — and offers exactly two ways to change
 * that: save new text, or reset to the shipped prompt, which sends `null`. Emptying the box
 * is deliberately not a third way: an empty prompt is refused, not read as a reset, so the
 * editor says which control to use instead of offering a Save that would fail.
 */
export function RolePromptEditor({
  label,
  shipped,
  maxChars,
  saved,
  busy,
  onSave,
  onReset,
}: {
  label: string;
  shipped: PromptDefault;
  maxChars: number;
  saved: string | undefined;
  busy: boolean;
  onSave: (text: string) => Promise<void>;
  onReset: () => Promise<void>;
}) {
  const [draft, setDraft] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const id = useId();
  const state = promptEditorState({
    saved,
    draft,
    defaultPrompt: shipped.default_prompt,
    maxChars,
  });

  const counterId = `${id}-count`;
  const hintId = `${id}-hint`;
  const errorId = `${id}-error`;

  function failed(err: unknown) {
    setError(
      err instanceof ApiError
        ? apiValidationMessage(err.message)
        : "Could not reach the server. Nothing was changed.",
    );
  }

  async function save() {
    setError(null);
    try {
      await onSave(state.text);
      setDraft(null);
      toast.success(`${label} instructions saved. They apply to research you start from now on.`);
    } catch (err) {
      failed(err);
    }
  }

  async function reset() {
    setError(null);
    try {
      await onReset();
      setDraft(null);
      toast.success(`${label} is back on the shipped prompt.`);
    } catch (err) {
      failed(err);
    }
  }

  const describedBy = [counterId, state.dirty && state.blank ? hintId : null, error ? errorId : null]
    .filter(Boolean)
    .join(" ");

  return (
    <Disclosure
      label="Instructions"
      summary={state.customised ? "custom" : "shipped default"}
    >
      <div className="space-y-2">
        {shipped.untrusted_content_framed && (
          <p role="note" className="text-xs leading-relaxed text-text-muted">
            Whatever you write here, the system also adds its rule for untrusted web content
            before and after it: text retrieved from the web is data, never instructions. That
            rule is not part of what you edit and cannot be removed.
          </p>
        )}
        <textarea
          aria-label={`Instructions for ${label}`}
          aria-describedby={describedBy}
          aria-invalid={state.tooLong || error !== null}
          className="textarea-base w-full font-mono text-xs leading-relaxed"
          rows={10}
          value={state.text}
          disabled={busy}
          onChange={(e) => {
            setDraft(e.target.value);
            setError(null);
          }}
        />
        <div className="flex flex-wrap items-center justify-between gap-2">
          <span
            id={counterId}
            className={`font-mono text-[0.6875rem] tabular-nums ${
              state.tooLong ? "text-danger" : "text-text-muted"
            }`}
          >
            {state.length.toLocaleString()} / {maxChars.toLocaleString()} characters
            {state.tooLong && " — over the limit"}
          </span>
          <div className="flex items-center gap-3">
            <ResetToDefault isDefault={!state.customised} onReset={reset} />
            {state.dirty && (
              <button
                type="button"
                className="btn btn-ghost"
                disabled={busy}
                onClick={() => {
                  setDraft(null);
                  setError(null);
                }}
              >
                Discard edits
              </button>
            )}
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
              : "Discard your edits to keep the shipped prompt."}
          </p>
        )}
        {error && (
          <p id={errorId} role="alert" className="text-xs leading-relaxed text-danger">
            {error}
          </p>
        )}
      </div>
    </Disclosure>
  );
}
