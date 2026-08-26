"use client";

import Link from "next/link";
import { useMemo } from "react";
import Markdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";

import { runHref, sessionHref } from "@/lib/desktop";

import { UnverifiedChip, makeMarkerPlugin } from "./citations";

import type { MemoryCitation } from "./types";

/**
 * Citations for project chat (docs/14 §5).
 *
 * A report cites the web: `[1]` resolves to a URL. A project-chat answer cites *approved
 * research*: `[R1]` resolves to a report in this project, and through that report to the
 * sources it cited. Same contract, one link further along the chain — which is why the
 * chip links to the report rather than opening an external page.
 *
 * The popover carries the retrieved excerpt verbatim. That is the point rather than a
 * nicety: it lets a reader check the claim against the exact text it was drawn from
 * without leaving the conversation, the same standard the report's own snippets meet.
 *
 * The ⚠ chip is shared with report citations deliberately. A model that writes `[R9]`
 * when only three excerpts were retrieved has made exactly the failure the chip exists
 * to expose, and it should look identical wherever it happens.
 */

function MemoryChip({ citation }: { citation: MemoryCitation }) {
  const date = new Date(citation.created_at);
  const label = Number.isNaN(date.getTime()) ? "" : date.toLocaleDateString();
  return (
    <span className="group relative inline-block align-baseline">
      <button
        type="button"
        aria-label={`Approved report: ${citation.title}`}
        className="align-super font-mono text-[0.65em] font-semibold leading-none text-accent px-1 py-0.5 bg-accent-muted border border-border hover:brightness-95 transition"
      >
        [{citation.marker}]
      </button>
      <span
        role="tooltip"
        className="pointer-events-none invisible absolute bottom-full left-1/2 z-20 mb-2 w-80 -translate-x-1/2 border border-border bg-bg-elevated p-3 text-left opacity-0 shadow-lg transition-opacity duration-150 group-hover:visible group-hover:opacity-100 group-focus-within:visible group-focus-within:opacity-100"
      >
        <span className="block font-serif text-xs font-semibold text-text-primary">{citation.title}</span>
        <span className="mt-0.5 block font-mono text-[0.6875rem] text-text-muted">
          Approved report{label ? ` · ${label}` : ""}
        </span>
        <span className="mt-2 block max-h-40 overflow-y-auto border-l-2 border-accent pl-2 text-xs italic text-text-secondary">
          &ldquo;{citation.excerpt}&rdquo;
        </span>
        <Link
          href={
            citation.report_kind === "run"
              ? runHref(citation.report_id)
              : sessionHref(citation.report_id)
          }
          className="pointer-events-auto mt-2 inline-block font-mono text-[0.6875rem] font-medium text-accent hover:underline"
        >
          Open the report and its sources →
        </Link>
      </span>
    </span>
  );
}

export function MemoryAnswer({
  markdown,
  citations,
}: {
  markdown: string;
  citations: MemoryCitation[];
}) {
  const byIndex = useMemo(() => {
    const map = new Map<number, MemoryCitation>();
    for (const c of citations) {
      const n = Number(c.marker.replace(/^R/, ""));
      if (!Number.isNaN(n)) map.set(n, c);
    }
    return map;
  }, [citations]);

  const resolved = useMemo(() => new Set(byIndex.keys()), [byIndex]);
  const rehypePlugins = useMemo(() => [makeMarkerPlugin(resolved, "R")], [resolved]);

  const components = useMemo<Components>(
    () => ({
      cite({ node }) {
        const props = (node?.properties ?? {}) as { dataIndex?: string; dataResolved?: string };
        const n = Number(props.dataIndex);
        const citation = byIndex.get(n);
        if (props.dataResolved !== "1" || !citation) return <UnverifiedChip n={n} prefix="R" />;
        return <MemoryChip citation={citation} />;
      },
      a({ href, children }) {
        return (
          <a href={href} target="_blank" rel="noopener noreferrer">
            {children}
          </a>
        );
      },
    }),
    [byIndex],
  );

  return (
    <div className="prose prose-sm dark:prose-invert max-w-none break-words">
      <Markdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={rehypePlugins as never}
        components={components}
      >
        {markdown}
      </Markdown>
    </div>
  );
}
