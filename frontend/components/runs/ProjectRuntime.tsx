"use client";

import Link from "next/link";

import { useModelRouting } from "@/hooks/queries";

/**
 * Which model answers each pipeline role, for the reader who wants to know before they
 * start a run — an AI engineer checking routing, not a researcher who came here to work.
 *
 * A native `<details>` rather than the `showAdvanced`-state pattern the run form uses:
 * this section has no submit action and no other state to coordinate, so there is nothing
 * a `useState` toggle would buy over the browser's own disclosure semantics (keyboard,
 * screen reader, and print support for free). Collapsed by default and placed last —
 * "visually quiet" per the redesign brief, not because the information is unimportant.
 */
export function ProjectRuntime() {
  const routing = useModelRouting();
  // `routing` is the user's saved override and is null whenever they have never chosen one
  // — the deployment default still applies, and `effective_routing` is what a run will
  // actually dial. Reading only the override made this section report "nothing resolved"
  // on every install where nobody had opened Settings, while Settings itself listed the
  // models: two surfaces deriving one answer differently. `ModelPicker` already falls back
  // this way; this matches it rather than inventing a third rule.
  const resolved = routing.data?.routing ?? routing.data?.effective_routing ?? null;

  return (
    <details className="group">
      <summary className="flex cursor-pointer list-none items-center gap-1.5 font-mono text-xs text-text-muted transition-colors hover:text-text-primary [&::-webkit-details-marker]:hidden">
        <span aria-hidden className="inline-block w-2 text-center group-open:hidden">
          ▸
        </span>
        <span aria-hidden className="hidden w-2 text-center group-open:inline-block">
          ▾
        </span>
        <span className="uppercase tracking-wider">Runtime</span>
      </summary>

      <div className="mt-3 border-t border-border pt-3">
        <div className="mb-2.5 flex items-baseline justify-between gap-2">
          {/* An h2, not an h3, despite being visually the smallest heading on the page.
              This disclosure is a top-level section of Overview, a peer of Project health —
              an h3 here would place it *inside* that section's outline for anyone
              navigating by heading, which is a claim about structure the page does not
              mean. Visual weight and heading level are answering different questions. */}
          <h2 className="text-sm font-semibold text-text-primary">
            Agents this project runs on
          </h2>
          <Link href="/settings/models" className="font-mono text-xs text-accent hover:underline">
            Change →
          </Link>
        </div>
        {routing.isLoading ? (
          <div className="h-10 animate-pulse bg-bg-elevated" aria-hidden />
        ) : resolved ? (
          <dl className="grid gap-3 sm:grid-cols-3 lg:grid-cols-5">
            {Object.entries(resolved as Record<string, string>).map(
              ([role, route]) => (
                <div key={role}>
                  <dt className="font-mono text-[length:var(--text-micro)] uppercase tracking-wider text-text-muted">
                    {role}
                  </dt>
                  <dd className="truncate font-mono text-xs text-text-primary" title={route}>
                    {route}
                  </dd>
                </div>
              ),
            )}
          </dl>
        ) : (
          // Never a guessed default: an unresolved routing reads as unresolved.
          <p className="text-sm text-text-secondary">
            No model routing resolved yet — it is recorded per run, on the run.
          </p>
        )}
      </div>
    </details>
  );
}
