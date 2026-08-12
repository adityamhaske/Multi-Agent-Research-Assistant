"use client";

import { useMemoryStatus } from "@/hooks/queries";

/**
 * What this project remembers (docs/14 §8).
 *
 * Memory is invisible by nature — a user cannot tell the difference between "chat has
 * nothing on that" and "ingestion has been silently failing for a week". This card is
 * the difference. It states the two ways memory can be incomplete rather than waiting
 * for the user to infer them from bad answers.
 */
export function MemoryStatusCard({ projectId }: { projectId: string | undefined }) {
  const { data, isLoading } = useMemoryStatus(projectId);

  if (isLoading || !data) return null;

  if (!data.available) {
    return (
      <div className="card border-warning/40 text-sm">
        <h3 className="font-semibold text-text-primary">Project memory is off</h3>
        <p className="mt-1 text-text-secondary">
          No embedding provider is configured, so chat cannot read this project&rsquo;s
          research. Install Ollama and run{" "}
          <code className="rounded bg-bg-elevated px-1 py-0.5 text-xs">
            ollama pull nomic-embed-text
          </code>
          , or set <code className="rounded bg-bg-elevated px-1 py-0.5 text-xs">EMBEDDINGS_PROVIDER</code>{" "}
          with that provider&rsquo;s key.
        </p>
      </div>
    );
  }

  return (
    <div className="card text-sm">
      <div className="flex items-baseline justify-between gap-3">
        <h3 className="font-semibold text-text-primary">Project memory</h3>
        <span className="text-xs text-text-muted">{data.current_model}</span>
      </div>
      <p className="mt-1 text-text-secondary">
        {data.indexed_reports} approved{" "}
        {data.indexed_reports === 1 ? "report" : "reports"} indexed ({data.chunk_count}{" "}
        {data.chunk_count === 1 ? "excerpt" : "excerpts"}).
      </p>

      {data.pending_reports > 0 && (
        <p className="mt-2 text-warning">
          {data.pending_reports} approved{" "}
          {data.pending_reports === 1 ? "report is" : "reports are"} not indexed yet, so
          chat cannot cite {data.pending_reports === 1 ? "it" : "them"}. This usually means
          the embedding provider was unreachable when the research finished.
        </p>
      )}

      {data.stale_models.length > 0 && (
        <p className="mt-2 text-warning">
          Some excerpts were embedded with {data.stale_models.join(", ")} and are invisible
          to the current model. Vectors from different models are not comparable — a
          re-index is needed to bring them back.
        </p>
      )}

      {data.approved_reports === 0 && (
        <p className="mt-2 text-text-muted">
          Nothing has been approved in this project yet. Only reports you approve enter
          memory — that is what keeps the answers here citable.
        </p>
      )}
    </div>
  );
}
