import Link from "next/link";

import { formatCost } from "@/lib/format";
import type { SessionSummary } from "@/lib/types";

import { RelativeTime } from "./RelativeTime";
import { StatusBadge } from "./StatusBadge";

export function SessionCard({ session }: { session: SessionSummary }) {
  return (
    <Link
      href={`/session/${session.session_id}`}
      className="card block transition-colors hover:border-accent focus-visible:border-accent"
    >
      <div className="flex items-center justify-between gap-2">
        <StatusBadge status={session.status} />
        <span className="text-xs text-text-muted">
          <RelativeTime iso={session.created_at} />
        </span>
      </div>
      <p className="mt-3 line-clamp-2 text-sm text-text-primary">{session.prompt}</p>
      <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-text-muted">
        <span className="capitalize">{session.research_depth}</span>
        <span>{formatCost(session.total_cost_usd)}</span>
        {session.rework_count > 0 && (
          <span>
            {session.rework_count} rework{session.rework_count > 1 ? "s" : ""}
          </span>
        )}
      </div>
    </Link>
  );
}
