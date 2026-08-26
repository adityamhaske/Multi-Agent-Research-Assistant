"use client";

import Link from "next/link";

import { IconWarningTriangle } from "@/components/icons";
import { RelativeTime } from "@/components/RelativeTime";
import { formatCost } from "@/lib/format";
import { runStatusMeta } from "@/lib/runStatus";
import type { RunSummary } from "@/lib/types";

import { RunStatusBadge } from "./primitives";

/**
 * The one thing on Overview that outranks everything else: a run parked at a human gate,
 * spending nothing further until someone decides. This is the page's center, not a
 * warning strip — it is why the section sits directly under the header, full-width, with
 * its own heading rather than being folded into the run list below it.
 *
 * Deliberately makes no claim this page cannot back up: no citation count, no
 * verification rate, no evidence tally. Those numbers exist once a report has been
 * drafted and checked; a run sitting at AWAITING_PLAN has no report yet, and printing a
 * stale or guessed number here would be exactly the false-measurement bug this product
 * exists to refuse (AGENTS.md, "the invariant everything else serves"). What this card
 * states is only what the run summary actually carries: question, status, age, depth,
 * cost, and whether it is a demo.
 *
 * The CTA's `tab` query param is passed explicitly rather than relying on the run page's
 * own auto-redirect to the gated tab (`RunWorkspace`'s `demanded` tab) — belt and
 * suspenders: the destination should be legible from this file alone, not depend on
 * staying in sync with a redirect rule that lives three files away. Both land on the
 * correct panel today; only one of them is guaranteed to keep doing so if the other
 * changes.
 */
export function AttentionCard({
  run,
  waitingCount,
}: {
  run: RunSummary;
  /** Total runs currently waiting on a decision in this project, this one included. */
  waitingCount: number;
}) {
  const isPlan = run.status === "AWAITING_PLAN";
  const moreCount = waitingCount - 1;
  const meta = runStatusMeta(run.status);

  return (
    <section
      aria-labelledby="attention-heading"
      className="border p-5 sm:p-6"
      style={{ borderColor: "var(--warning-line)", backgroundColor: "var(--warning-soft)" }}
    >
      <div className="flex items-center gap-1.5">
        {/* The heading beside it carries the whole meaning, so the glyph is decoration and
            is hidden rather than announced as an unlabelled image. Every other call site
            gets this from `EmptyState`'s icon slot, which wraps it; rendered bare, the
            wrapper has to come from here. */}
        <span aria-hidden className="flex shrink-0 text-warning">
          <IconWarningTriangle className="h-3.5 w-3.5" />
        </span>
        <h2
          id="attention-heading"
          className="font-mono text-xs font-semibold uppercase tracking-wider text-warning"
        >
          Needs your decision
        </h2>
      </div>

      <p className="mt-3 line-clamp-3 break-words font-serif text-lg font-semibold leading-snug text-text-primary sm:text-xl">
        {run.question}
      </p>

      <p className="mt-1.5 text-sm leading-relaxed text-text-secondary">{meta.sentence}</p>

      <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1.5">
        <RunStatusBadge status={run.status} />
        <span className="font-mono text-xs text-text-muted">
          started <RelativeTime iso={run.created_at} />
        </span>
        <span className="font-mono text-xs text-text-muted">{run.depth}</span>
        <span className="font-mono text-xs text-text-muted">{formatCost(run.cost_usd)}</span>
        {run.demo && (
          <span
            className="font-mono text-xs font-semibold text-warning"
            title="Scripted models and fixture sources. Not real research."
          >
            demo
          </span>
        )}
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-x-5 gap-y-2">
        <Link
          href={`/research/run?id=${run.id}&tab=${isPlan ? "plan" : "review"}`}
          className="btn btn-primary"
        >
          {isPlan ? "Review plan" : "Review report"}
        </Link>
        {moreCount > 0 && (
          <a href="#waiting-on-you" className="font-mono text-xs text-accent hover:underline">
            +{moreCount} more waiting on you →
          </a>
        )}
      </div>
    </section>
  );
}
