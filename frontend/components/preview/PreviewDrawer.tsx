"use client";

import { useRef } from "react";
import toast from "react-hot-toast";

import { DocumentPreview } from "@/components/preview/DocumentPreview";
import { useDialogFocus } from "@/hooks/useDialogFocus";
import { ApiError } from "@/lib/api";
import { downloadFile } from "@/lib/download";

/**
 * A right-hand drawer that shows a corpus document without leaving the page
 * (internal/07 Phase 6; req 9).
 *
 * "In place" is the point. Clicking a document — or a citation that resolves to one —
 * used to mean a download and a context switch into another application, which is the
 * moment a reader stops checking sources. The drawer keeps the list, the report and the
 * evidence on screen behind it.
 *
 * Keyboard behaviour is `useDialogFocus`'s: without it a keyboard user lands in a dialog
 * they cannot leave, and a screen-reader user is never told anything appeared.
 */
export function PreviewDrawer({
  open,
  onClose,
  url,
  filename,
  downloadable,
  subtitle,
  page = null,
}: {
  open: boolean;
  onClose: () => void;
  url: string;
  filename: string;
  downloadable: boolean;
  /** Optional context line — e.g. which citation opened this. */
  subtitle?: string;
  /** The cited page, which a PDF opens at. */
  page?: number | null;
}) {
  const panelRef = useRef<HTMLDivElement>(null);

  useDialogFocus(open, onClose, panelRef);

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
                // An anchor for its semantics, a fetch for its bytes: a link cannot carry the
                // desktop's bearer token, so a plain click was a 401 there (lib/download.ts).
                onClick={(e) => {
                  if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
                  e.preventDefault();
                  downloadFile(url, filename).catch((err: Error) =>
                    toast.error(err instanceof ApiError ? err.message : "Download failed."),
                  );
                }}
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
          <DocumentPreview
            url={url}
            filename={filename}
            downloadable={downloadable}
            page={page}
          />
        </div>
      </div>
    </div>
  );
}
