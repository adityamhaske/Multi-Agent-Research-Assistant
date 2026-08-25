"use client";

import Link from "next/link";

import { useCorpusStatus, useMemoryStatus } from "@/hooks/queries";
import { isDesktop } from "@/lib/desktop";
import { formatCost } from "@/lib/format";
import type { V2RunSummary } from "@/lib/types";

import { Stat } from "./primitives";

/**
 * Three compact, honest questions about this project, side by side: what does it know,
 * what can it draw on, and what has that cost. One bordered strip (`.academic-grid`'s 1px
 * hairlines between cells) rather than three separate `.card` boxes — the old page's six
 * independent cards were the "stack of large repetitive cards" problem this page exists to
 * fix, and three cards that always say something short do not need three borders each.
 *
 * **Corpus and project memory are kept as distinct concepts, on purpose.** A corpus
 * document is embedded synchronously at upload (`app/(app)/corpus/page.tsx`) — there is no
 * "still indexing" state for a document once it is listed. What *can* be silently
 * incomplete is project **memory**: an approved report that failed to embed
 * (`pending_reports`), or one embedded under an embedding model that is no longer current
 * (`stale_models`). Labelling both "indexing" would blur a corpus problem (go to Corpus,
 * re-upload) with a memory problem (nothing to do there — it is the report that needs
 * re-indexing), which is exactly the kind of imprecise warning this section exists to
 * avoid.
 *
 * Every cell owns an explicit unmeasured branch. `runs` is `undefined` rather than `[]`
 * when the run list has not answered, because `[].reduce` produces a perfectly plausible
 * `$0.00` that is not a measurement of anything — the failure mode AGENTS.md calls a P0.
 */
export function ProjectHealth({
  projectId,
  runs,
  runsLoading,
  runsError,
}: {
  projectId: string;
  /** `undefined` until the run list has actually answered. Never defaulted to `[]` here. */
  runs: V2RunSummary[] | undefined;
  runsLoading: boolean;
  runsError: boolean;
}) {
  const memory = useMemoryStatus(isDesktop ? undefined : projectId);
  const corpus = useCorpusStatus(projectId);

  const spend = runs?.reduce((total, r) => total + (r.cost_usd || 0), 0) ?? 0;

  return (
    <section aria-labelledby="project-health">
      <h2
        id="project-health"
        className="mb-3 font-serif text-lg font-bold tracking-tight text-text-primary"
      >
        Project health
      </h2>
      <div className="academic-grid grid-cols-1 sm:grid-cols-3">
        {/* Project memory: what earlier approved research this project can draw on. */}
        <div className="p-4">
          <div className="mb-2.5 flex items-baseline justify-between gap-2">
            <h3 className="text-sm font-semibold text-text-primary">Project memory</h3>
            <Link href="/chat" className="font-mono text-xs text-accent hover:underline">
              Chat →
            </Link>
          </div>
          {isDesktop ? (
            <p className="text-xs leading-relaxed text-text-secondary">
              Needs Postgres with pgvector, so it isn&apos;t part of the desktop app. Your
              reports and corpus are all here — only cross-report recall is missing.
            </p>
          ) : memory.isLoading ? (
            <div className="h-10 animate-pulse bg-bg-elevated" aria-hidden />
          ) : memory.isError || !memory.data ? (
            <p className="text-xs text-text-secondary">Couldn&apos;t read memory status.</p>
          ) : !memory.data.available ? (
            // `available` is the server's own "can memory function at all" flag
            // (`embedder.model_id != "none"`). Without it the counts below are structurally
            // zero, and reporting them as an approval backlog would blame the user for a
            // deployment setting.
            <p className="text-xs leading-relaxed text-text-secondary">
              No embedding model is configured, so nothing can be indexed into memory.{" "}
              <Link href="/settings/models" className="text-accent hover:underline">
                Configure one
              </Link>
              .
            </p>
          ) : (
            <>
              <dl className="flex gap-5">
                <Stat label="Approved" value={memory.data.approved_reports} />
                <Stat label="Indexed" value={memory.data.indexed_reports} />
              </dl>
              {/* Scope stated once, because the number is narrower than the page around it:
                  `approved_reports` counts COMPLETED V1 `sessions` only
                  (backend/app/services/memory.py), and nothing in the V2 runtime writes
                  memory. Without this line the panel can read "Nothing approved yet" while
                  the run list beside it badges three research runs "Approved" — two true
                  numbers that look like a contradiction because one of them is unscoped. */}
              <p className="mt-2 text-xs leading-snug text-text-muted">
                Built from approved legacy sessions; research runs are not indexed into it.
              </p>
              {memory.data.pending_reports > 0 && (
                <p className="mt-2 text-xs leading-snug text-warning">
                  {memory.data.pending_reports} approved report
                  {memory.data.pending_reports === 1 ? "" : "s"} not indexed — follow-up
                  chat can&apos;t draw on{" "}
                  {memory.data.pending_reports === 1 ? "it" : "them"} yet.
                </p>
              )}
              {memory.data.stale_models.length > 0 && (
                <p className="mt-2 text-xs leading-snug text-warning">
                  Some excerpts were embedded with a model this project no longer uses and
                  are invisible to it now — a re-index would bring them back.
                </p>
              )}
            </>
          )}
        </div>

        {/* Corpus: the uploaded source material a run can be restricted to. */}
        <div className="p-4">
          <div className="mb-2.5 flex items-baseline justify-between gap-2">
            <h3 className="text-sm font-semibold text-text-primary">Corpus</h3>
            <Link href="/corpus" className="font-mono text-xs text-accent hover:underline">
              Manage →
            </Link>
          </div>
          {corpus.isLoading ? (
            <div className="h-10 animate-pulse bg-bg-elevated" aria-hidden />
          ) : corpus.isError ? (
            <p className="text-xs text-text-secondary">Couldn&apos;t read the corpus.</p>
          ) : corpus.data && corpus.data.documents > 0 ? (
            <dl className="flex gap-5">
              <Stat label="Documents" value={corpus.data.documents} />
              <Stat label="Chunks" value={corpus.data.chunks} />
            </dl>
          ) : (
            <p className="text-xs leading-relaxed text-text-secondary">
              No documents yet.{" "}
              <Link href="/corpus" className="text-accent hover:underline">
                Upload some
              </Link>{" "}
              to restrict a run to this project&apos;s own material.
            </p>
          )}
        </div>

        {/* Recent research runs and what they cost. */}
        <div className="p-4">
          <h3 className="mb-2.5 text-sm font-semibold text-text-primary">Recent runs</h3>
          {runsLoading ? (
            <div className="h-10 animate-pulse bg-bg-elevated" aria-hidden />
          ) : runsError || runs === undefined ? (
            <p className="text-xs text-text-secondary">Couldn&apos;t read recent runs.</p>
          ) : (
            <>
              <dl className="flex gap-5">
                <Stat label="Runs" value={runs.length} />
                <Stat label="Cost" value={formatCost(spend)} />
              </dl>
              {/* The set summed is the run list the server returned (capped at 50), which
                  is neither "everything in this project" nor "the rows visible above" —
                  the list shows fewer. Naming the actual set is the only version of this
                  caption that is true in both directions. Legacy sessions carry their own
                  cost and are not in this sum. */}
              <p className="mt-2 text-xs leading-snug text-text-muted">
                Across the {runs.length} most recent research run
                {runs.length === 1 ? "" : "s"} — not a project total, and not counting
                legacy sessions.
              </p>
            </>
          )}
        </div>
      </div>
    </section>
  );
}
