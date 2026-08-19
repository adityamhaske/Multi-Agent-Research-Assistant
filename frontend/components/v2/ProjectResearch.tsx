"use client";

import Link from "next/link";

import { useV2Runs } from "@/hooks/v2";

import { RunCard } from "./RunCard";

/**
 * The research panel on the project overview.
 *
 * Deliberately operational, not analytical: what is running, what is waiting for a decision,
 * and what already has a verified artifact. No charts, no trends — a project overview should
 * answer "what needs me?" in one glance.
 *
 * Rows come from the shared `RunCard`, so Overview, Research and History cannot describe the
 * same run three different ways, which is what they were doing.
 */
export function ProjectResearch({ projectId }: { projectId: string | undefined }) {
  const { data: runs, isLoading, isError, refetch } = useV2Runs(projectId ?? null);
  const recent = runs?.slice(0, 5) ?? [];
  const waiting =
    runs?.filter((r) => r.status === "AWAITING_REVIEW" || r.status === "AWAITING_PLAN").length ?? 0;

  return (
    <section aria-labelledby="v2-research" className="card">
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
        <h2 id="v2-research" className="font-serif text-base font-bold text-text-primary">
          Research
        </h2>
        <Link href="/research" className="font-mono text-xs text-accent hover:underline">
          + New research
        </Link>
      </div>

      {waiting > 0 && (
        <p
          className="mb-3 border p-2 text-xs"
          style={{
            color: "var(--warning)",
            backgroundColor: "var(--warning-soft)",
            borderColor: "var(--warning-line)",
          }}
        >
          {waiting} run{waiting === 1 ? "" : "s"} waiting for your decision.
        </p>
      )}

      {isLoading ? (
        <div className="h-16 animate-pulse bg-bg-elevated" aria-hidden />
      ) : isError ? (
        <p className="text-sm text-text-secondary">
          Couldn&apos;t load this project&apos;s research.{" "}
          <button type="button" onClick={() => refetch()} className="text-accent hover:underline">
            Retry
          </button>
        </p>
      ) : recent.length === 0 ? (
        <p className="text-sm leading-relaxed text-text-secondary">
          No research yet. A run produces evidence, claims and sources you can inspect, and a
          verifiable artifact once you approve it.{" "}
          <Link href="/research" className="text-accent hover:underline">
            Ask a question
          </Link>{" "}
          to start.
        </p>
      ) : (
        <ul className="space-y-2">
          {recent.map((r) => (
            <li key={r.id}>
              <RunCard run={r} />
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
