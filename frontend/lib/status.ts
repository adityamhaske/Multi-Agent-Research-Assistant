import type { SessionStatus } from "./types";

/**
 * One status vocabulary, for the list, the card and the detail (docs/07 §2, Phase 7).
 *
 * These lived in two places — `StatusBadge`'s CONFIG and the history page's FILTERS —
 * and the second was already wrong: adding `AWAITING_PLAN` in Phase 4 updated the badge
 * and not the filter list, so a session parked at the design gate could be *seen* but
 * never *filtered for*. That is the worst way for this particular gap to fall, because a
 * session waiting on the user is exactly the one they are scanning the list to find.
 *
 * `Record<SessionStatus, …>` is what makes that impossible to repeat: adding a status to
 * the union without adding it here is a type error, and everything downstream is derived
 * from this object rather than restated.
 */
export interface StatusMeta {
  /** CSS token name (without `--`). Colour is never the sole carrier — the label is. */
  token: string;
  label: string;
  pulse?: boolean;
  /** Whether this status is waiting on the user rather than on the pipeline. */
  needsYou?: boolean;
}

export const STATUS_META: Record<SessionStatus, StatusMeta> = {
  PENDING: { token: "text-muted", label: "Queued" },
  RUNNING: { token: "info", label: "Running", pulse: true },
  // Both gates are amber: to someone scanning a list they are one urgency class —
  // "waiting on you" — and the label is what says which decision is owed. A distinct
  // hue would imply a difference in urgency that does not exist.
  AWAITING_PLAN: { token: "warning", label: "Plan review", needsYou: true },
  AWAITING_APPROVAL: { token: "warning", label: "Needs review", needsYou: true },
  COMPLETED: { token: "success", label: "Completed" },
  FAILED: { token: "danger", label: "Failed" },
};

/** Every status, in pipeline order — the order a run moves through them. */
export const STATUS_ORDER: SessionStatus[] = [
  "PENDING",
  "RUNNING",
  "AWAITING_PLAN",
  "AWAITING_APPROVAL",
  "COMPLETED",
  "FAILED",
];

export function statusMeta(status: SessionStatus): StatusMeta {
  return STATUS_META[status] ?? STATUS_META.PENDING;
}
