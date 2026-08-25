"use client";

import Link from "next/link";

import { useActiveProject } from "@/components/ActiveProject";
import { FirstRunNotice } from "@/components/FirstRunNotice";
import { RelativeTime } from "@/components/RelativeTime";
import { StatusBadge } from "@/components/StatusBadge";
import { EmptyState } from "@/components/ui/EmptyState";
import { ActiveResearchList } from "@/components/v2/ActiveResearchList";
import { AttentionCard } from "@/components/v2/AttentionCard";
import { EmptyProjectWelcome } from "@/components/v2/EmptyProjectWelcome";
import { ProjectHealth } from "@/components/v2/ProjectHealth";
import { ProjectRuntime } from "@/components/v2/ProjectRuntime";
import { useCorpusStatus, useSessions } from "@/hooks/queries";
import { useV2Runs } from "@/hooks/v2";
import { sessionHref } from "@/lib/desktop";
import { formatCost } from "@/lib/format";
import { isProjectEmpty } from "@/lib/projectEmptiness";
import { pickPriorityRun } from "@/lib/runPriority";
import { v2StatusMeta } from "@/lib/v2Status";

/**
 * Overview: the project's home (docs/07 §2, Phase 6; req 9).
 *
 * Answers four questions, in this order, because they are asked in this order: what needs
 * me now, what is running or done, what does this project actually know, and how do I
 * start or resume work. Everything below the header exists to answer one of those and
 * nothing is here that doesn't.
 *
 * `useV2Runs` is called once, here, and its result threaded down to `AttentionCard`,
 * `ActiveResearchList` and `ProjectHealth` as props rather than let each component fetch
 * its own copy. Not a performance concern — React Query would dedupe an identical second
 * call for free — but a correctness one: which run gets promoted to Attention, which runs
 * the list must exclude, and which runs the spend figure covers are one decision, and
 * computing it in three files is exactly the "two homes for one contract" drift AGENTS.md
 * warns about.
 *
 * The run list's *measurement state* is threaded with it, deliberately. Passing
 * `data ?? []` would hand every consumer a plausible empty list built from a request that
 * failed, and `[].reduce` renders as `$0.00` — a number that looks measured and is not.
 */
export default function ProjectPage() {
  const { activeId, active } = useActiveProject();
  const sessions = useSessions(1, 5, false, activeId);
  const corpus = useCorpusStatus(activeId);
  const runsQuery = useV2Runs(activeId);

  if (!activeId || !active) {
    return (
      <EmptyState
        title="No project selected"
        description="Pick a project from the switcher above to see its workspace."
      />
    );
  }

  const runs = runsQuery.data ?? [];
  const spend = runs.reduce((total, r) => total + (r.cost_usd || 0), 0);
  const waiting = runs
    .filter((r) => v2StatusMeta(r.status).needsYou)
    .sort((a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime());
  const priorityRun = pickPriorityRun(waiting);

  const legacySessions = sessions.data?.sessions ?? [];

  // A first-time project: no V2 research, no legacy sessions, no corpus. The rule for what
  // counts as "empty" rather than "not read yet" lives in `lib/projectEmptiness.ts` — see
  // there for why an errored source is not a zero. While it resolves, the sections below
  // render their own per-section loading state rather than one page-wide gate.
  const emptyProject = isProjectEmpty([
    {
      isLoading: runsQuery.isLoading,
      isError: runsQuery.isError,
      data: runsQuery.data,
      count: runs.length,
    },
    {
      isLoading: sessions.isLoading,
      isError: sessions.isError,
      data: sessions.data,
      count: sessions.data?.total ?? 0,
    },
    {
      isLoading: corpus.isLoading,
      isError: corpus.isError,
      data: corpus.data,
      count: corpus.data?.documents ?? 0,
    },
  ]);

  return (
    <div className="space-y-8" key={activeId}>
      {/* Top Academic Project Hero Card */}
      <header className="card space-y-4 p-5 sm:p-6">
        {/* Eyebrow & Actions Header */}
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border pb-3">
          <div className="flex items-center gap-2">
            <span className="badge-frame">
              <span className="status-marker bg-success" />
              PROJECT WORKSPACE
            </span>
            <span className="font-mono text-[length:var(--text-micro)] text-text-muted">
              {runs.length} {runs.length === 1 ? "research run" : "research runs"}
            </span>
          </div>

          <div className="flex items-center gap-2">
            <Link href="/corpus" className="btn btn-secondary h-8 px-2.5 text-xs">
              Corpus
            </Link>
            <Link href="/chat" className="btn btn-secondary h-8 px-2.5 text-xs">
              Chat
            </Link>
          </div>
        </div>

        {/* Project Title & Description */}
        <div>
          <h1 className="font-serif text-2xl sm:text-3xl font-bold tracking-tight text-text-primary">
            {active.name}
          </h1>
          {active.description ? (
            <p className="mt-1.5 max-w-3xl text-sm leading-relaxed text-text-secondary">
              {active.description}
            </p>
          ) : (
            <p className="mt-1 text-xs text-text-muted">
              Grounded multi-agent research workspace with cited evidence and human verification gates.
            </p>
          )}
        </div>

        {/* Quick Project KPI Strip */}
        <div className="grid grid-cols-2 gap-2 border-t border-border/40 pt-3 sm:grid-cols-4">
          <div className="bg-bg-elevated p-2.5">
            <div className="font-mono text-[length:var(--text-micro)] uppercase tracking-wider text-text-muted">
              Total Runs
            </div>
            <div className="mt-0.5 font-mono text-lg font-bold text-text-primary">
              {runsQuery.isLoading ? "…" : runs.length}
            </div>
          </div>

          <div className="bg-bg-elevated p-2.5">
            <div className="font-mono text-[length:var(--text-micro)] uppercase tracking-wider text-text-muted">
              Waiting On You
            </div>
            <div className={`mt-0.5 font-mono text-lg font-bold ${waiting.length > 0 ? "text-warning" : "text-text-primary"}`}>
              {runsQuery.isLoading ? "…" : waiting.length}
            </div>
          </div>

          <div className="bg-bg-elevated p-2.5">
            <div className="font-mono text-[length:var(--text-micro)] uppercase tracking-wider text-text-muted">
              Corpus Documents
            </div>
            <div className="mt-0.5 font-mono text-lg font-bold text-text-primary">
              {corpus.isLoading ? "…" : (corpus.data?.documents ?? 0)}
            </div>
          </div>

          <div className="bg-bg-elevated p-2.5">
            <div className="font-mono text-[length:var(--text-micro)] uppercase tracking-wider text-text-muted">
              Recent Spend
            </div>
            <div className="mt-0.5 font-mono text-lg font-bold text-text-primary">
              {runsQuery.isLoading ? "…" : formatCost(spend)}
            </div>
          </div>
        </div>
      </header>

      {/* Above everything else: someone with no model configured needs to see the next
          step before anything on this page can do anything. */}
      <FirstRunNotice />

      {emptyProject ? (
        <EmptyProjectWelcome projectName={active.name} />
      ) : (
        <>
          {priorityRun && <AttentionCard run={priorityRun} waitingCount={waiting.length} />}

          <ActiveResearchList
            runs={runs}
            excludeId={priorityRun?.id ?? null}
            isLoading={runsQuery.isLoading}
            isError={runsQuery.isError}
            onRetry={runsQuery.refetch}
          />

          <ProjectHealth
            projectId={activeId}
            runs={runsQuery.data}
            runsLoading={runsQuery.isLoading}
            runsError={runsQuery.isError}
          />
        </>
      )}

      <ProjectRuntime />

      {/* Legacy V1 sessions: kept reachable, deliberately quiet, and absent entirely when
          there are none — an empty collapsed section is still a section nobody needed. */}
      {legacySessions.length > 0 && (
        <details className="group">
          <summary className="flex cursor-pointer list-none items-center gap-1.5 font-mono text-xs text-text-muted transition-colors hover:text-text-primary [&::-webkit-details-marker]:hidden">
            {/* A ▸/▾ pair swapped by `group-open:`, not one static glyph. A frozen arrow is
                worse than no arrow: once expanded it states the opposite of the real state,
                and it is the only cue a sighted user has left after the native marker is
                suppressed. */}
            <span aria-hidden className="inline-block w-2 text-center group-open:hidden">
              ▸
            </span>
            <span aria-hidden className="hidden w-2 text-center group-open:inline-block">
              ▾
            </span>
            <span className="uppercase tracking-wider">Legacy sessions</span>
          </summary>
          <div className="mt-3 border-t border-border pt-3">
            {/* A real heading, so this section is reachable by heading navigation — the
                primary way a screen-reader user skims. The visible label lives in the
                summary; this is the same words at the level the outline needs, kept
                off-screen rather than duplicated visually. */}
            <h2 className="sr-only">Legacy sessions</h2>
            <p className="mb-3 text-xs leading-relaxed text-text-muted">
              From the earlier research form. Still here and still openable — new research
              runs through the flow above instead.
            </p>
            <ul className="divide-y divide-border">
              {legacySessions.map((s) => (
                <li key={s.session_id} className="flex items-center justify-between gap-3 py-2">
                  <Link
                    href={sessionHref(s.session_id)}
                    className="min-w-0 flex-1 truncate text-sm text-text-primary hover:text-accent"
                  >
                    {s.prompt}
                  </Link>
                  <div className="flex shrink-0 items-center gap-2.5">
                    <StatusBadge status={s.status} />
                    <span className="font-mono text-xs text-text-muted">
                      <RelativeTime iso={s.created_at} />
                    </span>
                  </div>
                </li>
              ))}
            </ul>
            <Link
              href="/history"
              className="mt-3 inline-block font-mono text-xs text-accent hover:underline"
            >
              All legacy sessions →
            </Link>
          </div>
        </details>
      )}
    </div>
  );
}
