/**
 * The workspace's tab vocabulary.
 *
 * A plain module rather than an export from `RunWorkspace.tsx`: the run page needs the
 * type and the guard to validate `?tab=` before it renders anything, and importing them
 * from a `"use client"` component to do that put the whole workspace — react-markdown
 * included — into the page's client reference graph twice.
 *
 * The tab order *is* the argument the product makes: a report is the end of a chain, not
 * the whole of it.
 */
export const TABS = [
  "plan",
  "report",
  "claims",
  "evidence",
  "sources",
  "contradictions",
  "review",
  "artifact",
] as const;

export type Tab = (typeof TABS)[number];

/** Whether a `?tab=` value names a real tab. Anything else falls back, never throws. */
export function isTab(value: string | null | undefined): value is Tab {
  return Boolean(value) && (TABS as readonly string[]).includes(value as string);
}
