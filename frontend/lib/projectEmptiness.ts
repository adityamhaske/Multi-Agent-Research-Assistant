/**
 * Is this project genuinely new, or have we simply not finished reading it?
 *
 * The distinction is the whole point. "No research, no sessions, no documents" and "three
 * requests that have not answered yet" produce the same zeroes, and only one of them
 * should greet a user with a first-run welcome screen — showing that screen to someone
 * whose project is mid-load tells them their work is gone. This is the same
 * unmeasured-vs-zero rule the rest of the product runs on (AGENTS.md), applied to a
 * layout decision rather than to a metric.
 *
 * A pure function in `lib/` rather than a few `&&`s inside the page component because it
 * is the page's one load-bearing piece of logic and the page itself is not reachable by
 * the unit suite (`vitest.config.ts` collects `{lib,components,hooks}` only). Logic that
 * decides what a user sees should not be the part that nothing can test.
 *
 * **`data` presence is the settled signal, not the absence of the two flags.** Checking
 * only `!isLoading && !isError` misses a third state: React Query v5 reports
 * `isLoading = isPending && isFetching`, so a query paused because the browser is offline
 * (`fetchStatus: "paused"`, the default `networkMode: "online"` behaviour) reports
 * `isLoading: false`, `isError: false` and `data: undefined`. Reading a count off that
 * scores an unread source as a measured zero — which is precisely the bug this function
 * exists to prevent, so it has to exclude all three non-answers rather than two of them.
 * An **errored** source is unsettled for the same reason: a corpus request that failed has
 * told us nothing about whether documents exist.
 */
export interface EmptinessSource {
  isLoading: boolean;
  isError: boolean;
  /** Whatever the query returned. `undefined` means it has not answered. */
  data: unknown;
  /** The count this source reports. Only read once the source has answered. */
  count: number;
}

export function isProjectEmpty(sources: EmptinessSource[]): boolean {
  const answered = (s: EmptinessSource) =>
    !s.isLoading && !s.isError && s.data !== undefined;
  if (!sources.every(answered)) return false;
  return sources.every((s) => s.count === 0);
}
