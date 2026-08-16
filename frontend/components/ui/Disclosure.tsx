"use client";

import { useId, useState, type ReactNode } from "react";

/**
 * The collapsed-summary disclosure (docs/07 §2, "Progressive disclosure"):
 * a trigger that expands to reveal detail, and — open or closed — always
 * names its own current state instead of hiding behind a bare arrow. Lifted
 * out of the dashboard run form's "Options" toggle, which is the model every
 * new options group should follow.
 */
export function Disclosure({
  label,
  summary,
  defaultOpen = false,
  children,
}: {
  label: ReactNode;
  /** What the closed state means right now — shown next to the label when collapsed. */
  summary?: ReactNode;
  defaultOpen?: boolean;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const contentId = useId();

  return (
    <div>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-controls={contentId}
        className="flex items-center gap-1.5 font-mono text-xs text-text-muted transition-colors hover:text-text-primary"
      >
        <span aria-hidden className="inline-block w-2 text-center">
          {open ? "▾" : "▸"}
        </span>
        <span className="uppercase tracking-wider">{label}</span>
        {!open && summary && <span className="font-semibold text-accent">{summary}</span>}
      </button>
      {open && (
        <div
          id={contentId}
          className="mt-3 space-y-[var(--space-lg)] border-t border-border pt-[var(--space-lg)]"
        >
          {children}
        </div>
      )}
    </div>
  );
}
