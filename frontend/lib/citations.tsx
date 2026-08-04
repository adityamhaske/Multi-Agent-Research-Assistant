"use client";

import { useMemo } from "react";
import Markdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";

import type { Source } from "./types";

/**
 * Citations UX (docs/07 §5) — the product's differentiator.
 *
 * Inline `[n]` markers in the report/draft are turned into small superscript chips
 * with a hover/focus popover carrying the source's title, domain and the verbatim
 * supporting snippet. A marker whose number has no matching source renders a visible
 * ⚠ "unverified" chip — we surface pipeline bugs instead of hiding them.
 *
 * The `[n]` → chip transform is a tiny hand-written rehype plugin that walks the HAST
 * and replaces citation runs inside text nodes with `<cite>` elements. Doing it at the
 * tree level (not by regex on the markdown string) keeps code blocks untouched and
 * never corrupts surrounding markup. No raw-HTML rehype plugin is used — the markdown
 * pipeline stays sanitized by construction and CI guards against one (docs/06 §5).
 */

// ─── HAST (minimal shapes we touch) ─────────────────────────────────────────────
interface HastText {
  type: "text";
  value: string;
}
interface HastElement {
  type: "element";
  tagName: string;
  properties?: Record<string, unknown>;
  children: HastNode[];
}
type HastNode =
  | HastText
  | HastElement
  | { type: string; value?: string; children?: HastNode[]; properties?: Record<string, unknown>; tagName?: string };

/**
 * Citation markers, including *grouped* ones.
 *
 * The synthesizer routinely writes `[1, 3]` or `[1, 2, 3, 4, 6]` when a sentence draws on
 * several sources — standard academic style, and the prompt never forbade it. An earlier
 * single-number-only pattern (`\[(\d+)\]`) silently failed to match those: the text stayed
 * inert, no chip rendered, no link, and — worst of all — no ⚠ either, so a citation could
 * fail to resolve without the UI ever admitting it. On a measured real report, 42% of all
 * citation references were inside grouped brackets and therefore invisible.
 *
 * Matching the group and emitting one chip per number is what keeps "every claim is
 * traceable, and we show you when it isn't" true rather than aspirational.
 */
const CITE_TEST = /\[\d+(?:\s*,\s*\d+)*\]/;
const CITE_RE = /\[(\d+(?:\s*,\s*\d+)*)\]/g;
const SKIP_TAGS = new Set(["code", "pre", "cite", "a"]);

function citeNode(n: number, resolved: Set<number>): HastNode {
  return {
    type: "element",
    tagName: "cite",
    properties: { dataIndex: String(n), dataResolved: resolved.has(n) ? "1" : "0" },
    children: [{ type: "text", value: `[${n}]` }],
  };
}

function splitCitations(value: string, resolved: Set<number>): HastNode[] {
  const out: HastNode[] = [];
  CITE_RE.lastIndex = 0;
  let last = 0;
  let m: RegExpExecArray | null;
  while ((m = CITE_RE.exec(value)) !== null) {
    if (m.index > last) out.push({ type: "text", value: value.slice(last, m.index) });
    // `[1, 3]` becomes two independent chips, so each source gets its own popover and
    // each unresolved number gets its own ⚠ rather than one verdict for the whole group.
    for (const part of m[1].split(",")) {
      out.push(citeNode(Number(part.trim()), resolved));
    }
    last = m.index + m[0].length;
  }
  if (last < value.length) out.push({ type: "text", value: value.slice(last) });
  return out;
}

function makeCitationPlugin(resolved: Set<number>) {
  const transform = (node: HastNode): void => {
    if (node.type === "element" && SKIP_TAGS.has((node as HastElement).tagName)) return;
    const children = (node as HastElement).children;
    if (!Array.isArray(children)) return;
    const next: HastNode[] = [];
    for (const child of children) {
      if (child.type === "text" && typeof child.value === "string" && CITE_TEST.test(child.value)) {
        next.push(...splitCitations(child.value, resolved));
      } else {
        transform(child);
        next.push(child);
      }
    }
    (node as HastElement).children = next;
  };
  return () => (tree: HastNode) => transform(tree);
}

// ─── Rendering ──────────────────────────────────────────────────────────────────

export function domainOf(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

/**
 * Every snippet this source contributed, newest schema first.
 *
 * Falls back to the single legacy `snippet` for sessions stored before `snippets` existed
 * (docs/12 M5, defect D3), so an old report still renders its citation popovers.
 */
export function snippetsOf(source: Source): string[] {
  if (source.snippets?.length) return source.snippets;
  return source.snippet ? [source.snippet] : [];
}

function CitationChip({ source }: { source: Source }) {
  const snippets = snippetsOf(source);
  return (
    <span className="group relative inline-block align-baseline">
      <button
        type="button"
        aria-label={`Source ${source.index}: ${source.title || domainOf(source.url)}`}
        className="align-super text-[0.65em] font-semibold leading-none text-accent rounded-sm px-1 py-0.5 bg-accent-muted hover:brightness-110 transition"
      >
        [{source.index}]
      </button>
      <span
        role="tooltip"
        className="pointer-events-none invisible absolute bottom-full left-1/2 z-20 mb-2 w-72 -translate-x-1/2 rounded-lg border border-border bg-bg-elevated p-3 text-left opacity-0 shadow-lg transition-opacity duration-150 group-hover:visible group-hover:opacity-100 group-focus-within:visible group-focus-within:opacity-100"
      >
        <span className="block text-xs font-semibold text-text-primary">
          {source.title || domainOf(source.url)}
        </span>
        <span className="mt-0.5 block text-[0.7rem] text-text-muted">{domainOf(source.url)}</span>
        {snippets.map((text, i) => (
          <span
            key={i}
            className="mt-2 block border-l-2 border-border pl-2 text-xs italic text-text-secondary"
          >
            &ldquo;{text}&rdquo;
          </span>
        ))}
        <a
          href={source.url}
          target="_blank"
          rel="noopener noreferrer"
          className="pointer-events-auto mt-2 inline-block text-[0.7rem] font-medium text-accent hover:underline"
        >
          Open source ↗
        </a>
      </span>
    </span>
  );
}

function UnverifiedChip({ n }: { n: number }) {
  return (
    <span
      title={`Citation [${n}] does not resolve to a source — unverified`}
      className="mx-0.5 inline-flex items-center gap-0.5 rounded-sm px-1 align-super text-[0.65em] font-semibold text-danger"
      style={{ backgroundColor: "color-mix(in srgb, var(--danger) 15%, transparent)" }}
    >
      ⚠[{n}]
    </span>
  );
}

export function Report({ markdown, sources }: { markdown: string; sources: Source[] }) {
  const sourceByIndex = useMemo(() => {
    const map = new Map<number, Source>();
    for (const s of sources) map.set(s.index, s);
    return map;
  }, [sources]);

  const resolved = useMemo(() => new Set(sourceByIndex.keys()), [sourceByIndex]);
  const rehypePlugins = useMemo(() => [makeCitationPlugin(resolved)], [resolved]);

  const components = useMemo<Components>(
    () => ({
      cite({ node }) {
        const props = (node?.properties ?? {}) as { dataIndex?: string; dataResolved?: string };
        const n = Number(props.dataIndex);
        const source = sourceByIndex.get(n);
        if (props.dataResolved !== "1" || !source) return <UnverifiedChip n={n} />;
        return <CitationChip source={source} />;
      },
      // External links always open safely.
      a({ href, children }) {
        return (
          <a href={href} target="_blank" rel="noopener noreferrer">
            {children}
          </a>
        );
      },
    }),
    [sourceByIndex],
  );

  return (
    <div className="prose prose-sm dark:prose-invert max-w-none break-words">
      <Markdown
        remarkPlugins={[remarkGfm]}
        // The plugin builds our own HAST elements — this is not raw-HTML passthrough.
        rehypePlugins={rehypePlugins as never}
        components={components}
      >
        {markdown}
      </Markdown>
    </div>
  );
}

export function SourcesPanel({ sources }: { sources: Source[] }) {
  if (!sources.length) return null;
  return (
    <section aria-labelledby="sources-heading" className="mt-8 border-t border-border pt-6">
      <h2 id="sources-heading" className="mb-4 text-sm font-semibold text-text-primary">
        Sources ({sources.length})
      </h2>
      <ol className="space-y-3">
        {sources.map((s) => (
          <li key={s.index} className="flex gap-3 text-sm">
            <span className="mt-0.5 shrink-0 font-mono text-xs text-accent">[{s.index}]</span>
            <div className="min-w-0">
              <a
                href={s.url}
                target="_blank"
                rel="noopener noreferrer"
                className="font-medium text-text-primary hover:text-accent hover:underline"
              >
                {s.title || domainOf(s.url)}
              </a>
              <span className="ml-2 text-xs text-text-muted">{domainOf(s.url)}</span>
              {snippetsOf(s).map((text, i) => (
                <p key={i} className="mt-1 line-clamp-3 text-xs italic text-text-secondary">
                  &ldquo;{text}&rdquo;
                </p>
              ))}
            </div>
          </li>
        ))}
      </ol>
    </section>
  );
}
