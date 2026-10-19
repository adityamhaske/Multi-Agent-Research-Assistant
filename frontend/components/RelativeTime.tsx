"use client";

import { useMounted } from "@/hooks/useMounted";

import { relativeTime } from "@/lib/format";

/**
 * Renders a relative timestamp ("2h ago"). Before mount it shows the tz-stable date
 * (YYYY-MM-DD) so server and client markup match — locale/tz-dependent strings would
 * cause a hydration mismatch.
 */
export function RelativeTime({ iso }: { iso: string }) {
  const mounted = useMounted();
  return (
    <time dateTime={iso} title={mounted ? new Date(iso).toLocaleString() : undefined}>
      {mounted ? relativeTime(iso) : iso.slice(0, 10)}
    </time>
  );
}
