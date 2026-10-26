"use client";

import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef } from "react";

import { apiFetch } from "@/lib/api";
import type { CorpusLocator } from "@/lib/corpusLocator";

type Extracted = {
  filename: string;
  kind: string;
  text: string;
  segments: [number, string][];
  extraction_mode: "verbatim" | "linearized";
};

/** The segment a character offset falls in — the server's `segment_label`, for display. */
function labelAt(segments: [number, string][], offset: number): string | null {
  let label: string | null = null;
  for (const [start, name] of segments) if (start <= offset) label = name;
  return label;
}

/**
 * A corpus citation shown in place: the document's canonical extracted text — exactly what
 * the quote was verified against — with the cited span highlighted and scrolled into view
 * (RFC V3.1 §12). Text is rendered as text, never as markup, so a document cannot inject
 * anything into the page. A linearized document says so beside the quote.
 */
export function CitedPassage({ projectId, locator }: { projectId: string; locator: CorpusLocator }) {
  const mark = useRef<HTMLElement>(null);
  const { data, error, isLoading } = useQuery({
    queryKey: ["corpus", projectId, "text", locator.documentId],
    queryFn: () =>
      apiFetch<Extracted>(
        `/projects/${projectId}/corpus/documents/${encodeURIComponent(locator.documentId)}/text`,
      ),
  });
  useEffect(() => {
    mark.current?.scrollIntoView({ block: "center" });
  }, [data]);

  if (isLoading) return <p className="text-xs text-text-muted">Opening the cited passage…</p>;
  if (error || !data)
    return (
      <p className="text-xs text-danger">
        This document is no longer in the corpus. The run kept the quoted evidence, but the full
        file cannot be reopened.
      </p>
    );

  const start = Math.max(0, Math.min(locator.start ?? 0, data.text.length));
  const end = Math.max(start, Math.min(locator.end ?? start, data.text.length));
  const where = labelAt(data.segments, start) ?? (locator.page ? `page ${locator.page}` : null);
  return (
    <div className="space-y-2">
      <p className="text-xs text-text-secondary">
        <span className="font-semibold text-text-primary">{data.filename}</span>
        {where ? ` — ${where}` : ""}
        {data.extraction_mode === "linearized" &&
          " · quoted from a text rendering of this file's tables, slides or cells"}
      </p>
      <pre className="max-h-96 overflow-auto whitespace-pre-wrap border border-border bg-bg-elevated p-3 text-xs leading-relaxed text-text-secondary">
        {data.text.slice(Math.max(0, start - 2000), start)}
        <mark ref={mark} className="bg-warning-soft text-text-primary">
          {data.text.slice(start, end)}
        </mark>
        {data.text.slice(end, end + 2000)}
      </pre>
    </div>
  );
}
