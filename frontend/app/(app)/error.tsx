"use client";

import { useEffect } from "react";

/**
 * Route-level error boundary for authenticated pages (docs/07 §2).
 *
 * Prevents transient errors (like temporary network drops or container restarts)
 * from crashing the entire app shell into Next.js's raw fallback screen.
 */
export default function AppError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    // Log error for debugging
    console.error("App route error:", error);
  }, [error]);

  return (
    <div className="flex h-full min-h-[50vh] flex-col items-center justify-center p-8 text-center">
      <div className="card max-w-md border border-border bg-bg-surface p-6 shadow-sm">
        <div className="mx-auto mb-3 flex h-10 w-10 items-center justify-center border border-border bg-bg-elevated font-mono font-bold text-danger">
          !
        </div>
        <h2 className="font-serif text-lg font-bold text-text-primary">
          Unable to load this section
        </h2>
        <p className="mt-1.5 text-xs leading-relaxed text-text-muted">
          {error.message || "A temporary connection or rendering issue occurred."}
        </p>
        <div className="mt-5 flex justify-center gap-3">
          <button
            type="button"
            onClick={() => reset()}
            className="btn btn-primary px-4 py-2 text-xs font-semibold"
          >
            Try again
          </button>
          <button
            type="button"
            onClick={() => window.location.reload()}
            className="btn btn-secondary px-4 py-2 text-xs font-semibold"
          >
            Reload page
          </button>
        </div>
      </div>
    </div>
  );
}
