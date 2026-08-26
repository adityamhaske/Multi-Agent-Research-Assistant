"use client";

import { useEffect, useMemo, useRef } from "react";
import toast from "react-hot-toast";

import { EmptyState } from "@/components/ui/EmptyState";
import { parseCorpusLocator } from "@/lib/corpusLocator";
import type { RunEvidence, RunGraph, RunSource } from "@/lib/types";

import { CitationChip } from "../primitives";

/**
 * Everything the run retrieved.
 *
 * **Retrieved is not cited.** A source the report never referenced has no citation number
 * and is listed anyway, under its own heading — omitting it would overstate how much of the
 * retrieval made it into the report, and quietly numbering it would make a marker resolve
 * to a source the report never cited.
 *
 * The two groups are headed rather than merely styled differently: a dashed border is not
 * a label, and the distinction is the point of the tab.
 */

function domainOf(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

function SourceCard({
  source,
  evidence,
  claimCount,
  focused,
  onInspectEvidence,
}: {
  source: RunSource;
  evidence: RunEvidence[];
  claimCount: number;
  focused: boolean;
  onInspectEvidence: (sourceId: string) => void;
}) {
  const ref = useRef<HTMLLIElement>(null);
  // Arriving from a claim must actually land on the source, not merely tint it: the card
  // is commonly below the fold on a run with twenty sources, and a highlight nobody
  // scrolls to is the same as no highlight.
  useEffect(() => {
    if (focused) ref.current?.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [focused]);

  // A corpus source's URL uses a scheme the browser cannot follow, so it gets no link.
  // A dead "open" affordance is worse than none: it claims the source is checkable and
  // then refuses to show it.
  const corpus = parseCorpusLocator(source.url);

  const copyCitation = async () => {
    const n = source.citation_index;
    const cite = `${n === null ? "" : `[${n}] `}${source.title || source.url}${
      corpus ? "" : ` — ${source.url}`
    }`;
    try {
      await navigator.clipboard.writeText(cite);
      toast.success("Citation copied.");
    } catch {
      toast.error("Couldn't access the clipboard.");
    }
  };

  return (
    <li
      ref={ref}
      className={`card ${focused ? "ring-1 ring-accent" : ""}`}
      style={source.citation_index === null ? { borderStyle: "dashed" } : undefined}
    >
      <div className="flex flex-wrap items-center gap-2">
        <CitationChip source={source} />
        {corpus ? (
          <span className="min-w-0 break-words text-sm font-medium text-text-primary">
            {source.title || "Uploaded document"}
          </span>
        ) : (
          <a
            href={source.url}
            target="_blank"
            rel="noreferrer noopener"
            className="min-w-0 break-words text-sm text-accent hover:underline"
          >
            {source.title || source.url}
          </a>
        )}
      </div>

      <p className="mt-1 truncate font-mono text-xs text-text-muted" title={source.url}>
        {corpus ? "from your corpus" : domainOf(source.url)}
      </p>

      <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[length:var(--text-micro)] text-text-muted">
        <span>{source.kind === "CORPUS" ? "Uploaded document" : "Web"}</span>
        <span title="How the source was obtained. UNKNOWN means the run did not record it.">
          {source.retrieval_status.toLowerCase().replace(/_/g, " ")}
        </span>
        <span>
          {evidence.length} evidence item{evidence.length === 1 ? "" : "s"}
        </span>
        <span>
          {claimCount === 0
            ? "backs no claim"
            : `backs ${claimCount} claim${claimCount === 1 ? "" : "s"}`}
        </span>
      </div>

      <div className="mt-2 flex flex-wrap gap-3 text-xs">
        {evidence.length > 0 && (
          <button
            type="button"
            onClick={() => onInspectEvidence(source.id)}
            className="text-accent hover:underline"
          >
            Read its evidence →
          </button>
        )}
        <button type="button" onClick={copyCitation} className="text-accent hover:underline">
          Copy citation
        </button>
      </div>
    </li>
  );
}

export function SourcesPanel({
  graph,
  focus,
  onInspectEvidence,
}: {
  graph: RunGraph;
  focus: string | null;
  onInspectEvidence: (sourceId: string) => void;
}) {
  const evidenceBySource = useMemo(() => {
    const map = new Map<string, RunEvidence[]>();
    for (const e of graph.evidence) {
      map.set(e.source_id, [...(map.get(e.source_id) ?? []), e]);
    }
    return map;
  }, [graph.evidence]);

  const claimsBySource = useMemo(() => {
    const evidenceToSource = new Map(graph.evidence.map((e) => [e.id, e.source_id]));
    const map = new Map<string, Set<string>>();
    for (const link of graph.claim_evidence_links) {
      const sourceId = evidenceToSource.get(link.evidence_id);
      if (!sourceId) continue;
      const set = map.get(sourceId) ?? new Set<string>();
      set.add(link.claim_id);
      map.set(sourceId, set);
    }
    return map;
  }, [graph.evidence, graph.claim_evidence_links]);

  if (graph.sources.length === 0) {
    return (
      <EmptyState
        title="No sources"
        description="Nothing was retrieved for this run. Sources appear here as the executor fetches them."
      />
    );
  }

  const cited = graph.sources
    .filter((s) => s.citation_index !== null)
    .sort((a, b) => (a.citation_index ?? 0) - (b.citation_index ?? 0));
  const uncited = graph.sources.filter((s) => s.citation_index === null);

  const card = (s: RunSource) => (
    <SourceCard
      key={s.id}
      source={s}
      evidence={evidenceBySource.get(s.id) ?? []}
      claimCount={claimsBySource.get(s.id)?.size ?? 0}
      focused={focus === s.id}
      onInspectEvidence={onInspectEvidence}
    />
  );

  return (
    <div className="space-y-4">
      <p className="text-xs leading-relaxed text-text-secondary">
        Everything the run retrieved.{" "}
        <strong className="text-text-primary">Retrieved is not cited</strong>:{" "}
        {uncited.length} of {graph.sources.length} carry no citation number because the report
        does not reference them. They are listed anyway — omitting them would overstate how
        much of the retrieval made it into the report.
      </p>

      {cited.length > 0 && (
        <section aria-labelledby="cited-sources">
          <h3
            id="cited-sources"
            className="font-mono text-[length:var(--text-micro)] font-semibold uppercase tracking-wider text-text-muted"
          >
            Cited sources ({cited.length})
          </h3>
          <ul className="mt-2 space-y-2">{cited.map(card)}</ul>
        </section>
      )}

      {uncited.length > 0 && (
        <section aria-labelledby="uncited-sources">
          <h3
            id="uncited-sources"
            className="font-mono text-[length:var(--text-micro)] font-semibold uppercase tracking-wider text-text-muted"
          >
            Retrieved, never cited ({uncited.length})
          </h3>
          <p className="mt-1 text-xs text-text-secondary">
            The run fetched these and the report does not reference them. They have no
            citation number.
          </p>
          <ul className="mt-2 space-y-2">{uncited.map(card)}</ul>
        </section>
      )}
    </div>
  );
}
