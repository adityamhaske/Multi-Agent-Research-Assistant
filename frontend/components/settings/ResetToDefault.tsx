"use client";

/**
 * Per-setting revert (docs/07 §2, Phase 3) — "as much customization as possible"
 * survives only if every knob has a visible way back. Shown only when the current
 * value differs from the default; a reset link next to an already-default field is
 * noise with nothing to do.
 */
export function ResetToDefault({
  isDefault,
  onReset,
}: {
  isDefault: boolean;
  onReset: () => void;
}) {
  if (isDefault) return null;
  return (
    <button
      type="button"
      onClick={onReset}
      className="font-mono text-[0.6875rem] text-accent hover:underline"
    >
      Reset to default
    </button>
  );
}
