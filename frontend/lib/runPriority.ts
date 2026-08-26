import type { RunSummary } from "./types";

/**
 * Which pending decision earns the Overview page's one attention slot.
 *
 * Oldest-first: a decision that has waited longest is the one most likely to be
 * forgotten, and "whoever has waited longest goes first" is a rule nobody has to be told
 * twice. Isolated in its own function rather than inlined at the call site because this is
 * a policy, not a computation — the obvious next iteration (weight by cost, by depth, by
 * an explicit urgency flag once one exists) should mean changing this one function, not
 * hunting through the page for where "priority" got decided.
 *
 * Callers pass the already-filtered "needs a decision" subset — this function only orders
 * it, so it never has to know the status vocabulary that defines "waiting" (`lib/v2Status.ts`
 * owns that).
 */
export function pickPriorityRun(waiting: RunSummary[]): RunSummary | null {
  if (waiting.length === 0) return null;
  return waiting.reduce((oldest, r) =>
    new Date(r.created_at).getTime() < new Date(oldest.created_at).getTime() ? r : oldest,
  );
}
