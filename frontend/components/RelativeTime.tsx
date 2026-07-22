"use client";

import { useSyncExternalStore } from "react";

import { relativeTime } from "@/lib/format";

const emptySubscribe = () => () => {};

/**
 * Renders a relative timestamp ("2h ago"). Before mount it shows the tz-stable date
 * (YYYY-MM-DD) so server and client markup match — locale/tz-dependent strings would
 * cause a hydration mismatch.
 */
export function RelativeTime({ iso }: { iso: string }) {
  const mounted = useSyncExternalStore(
    emptySubscribe,
    () => true,
    () => false,
  );
  return (
    <time dateTime={iso} title={new Date(iso).toLocaleString()}>
      {mounted ? relativeTime(iso) : iso.slice(0, 10)}
    </time>
  );
}
