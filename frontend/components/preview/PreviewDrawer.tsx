"use client";

import { useEffect, useRef } from "react";

import { DocumentPreview } from "@/components/preview/DocumentPreview";

/**
 * A right-hand drawer that shows a corpus document without leaving the page
 * (docs/07 §2, Phase 6; req 9).
 *
 * "In place" is the point. Clicking a document — or a citation that resolves to one —
 * used to mean a download and a context switch into another application, which is the
 * moment a reader stops checking sources. The drawer keeps the list, the report and the
 * evidence on screen behind it.
 *
 * Focus is moved into the drawer on open and returned to whatever opened it on close,
 * and Escape closes. Without that a keyboard user lands in a dialog they cannot leave,
 * and a screen-reader user is never told anything appeared.
 */
export function PreviewDrawer({
  open,
  onClose,
  url,
  filename,
  downloadable,
  subtitle,
}: {
  open: boolean;
  onClose: () => void;
  url: string;
  filename: string;
  downloadable: boolean;
  /** Optional context line — e.g. which citation opened this. */
  subtitle?: string;
}) {
  const panelRef = useRef<HTMLDivElement>(null);
  const returnFocusRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (!open) return;
    returnFocusRef.current = document.activeElement as HTMLElement | null;
    panelRef.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        onClose();
        return;
      }
      if (e.key !== "Tab") return;
      // `aria-modal="true"` tells assistive tech that everything outside is inert.
      // Without a trap that is a lie: a keyboard user tabs straight out of the dialog
      // into a page their screen reader has been told does not exist. Cycle instead.
      const panel = panelRef.current;
      if (!panel) return;
      const focusable = panel.querySelectorAll<HTMLElement>(
        'a[href], button:not([disabled]), input, select, textarea, iframe, object, [tabindex]:not([tabindex="-1"])',
      );
      if (focusable.length === 0) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      const active = document.activeElement;
      if (e.shiftKey && (active === first || active === panel)) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && active === last) {
        e.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      // Return focus to the row or citation that opened this, not to the top of the page.
      returnFocusRef.current?.focus?.();
    };
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-40 flex justify-end">
      <button
        type="button"
        aria-label="Close preview"
        onClick={onClose}
        className="absolute inset-0 bg-black/40"
      />
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-label={`Preview of ${filename}`}
        tabIndex={-1}
        className="relative flex h-full w-full max-w-2xl flex-col border-l border-border bg-bg-surface shadow-xl"
      >
        <div className="flex items-start justify-between gap-3 border-b border-border p-4">
          <div className="min-w-0">
            <p className="truncate font-serif text-sm font-semibold text-text-primary">
              {filename}
            </p>
            {subtitle && <p className="mt-0.5 font-mono text-xs text-text-muted">{subtitle}</p>}
          </div>
          <div className="flex shrink-0 items-center gap-2">
            {downloadable && (
              <a
                href={url}
                download={filename}
                className="border border-border px-2 py-1 font-mono text-xs text-text-secondary hover:border-accent hover:text-accent"
              >
                Download
              </a>
            )}
            <button
              type="button"
              onClick={onClose}
              className="border border-border px-2 py-1 font-mono text-xs text-text-secondary hover:border-accent hover:text-accent"
            >
              Close
            </button>
          </div>
        </div>

        <div className="min-h-0 flex-1">
          <DocumentPreview url={url} filename={filename} downloadable={downloadable} />
        </div>
      </div>
    </div>
  );
}
