import type { Source, RunGraph } from "./types";

/**
 * The run graph, in the shape the citation renderer already speaks.
 *
 * `lib/citations.tsx` turns `[n]` markers into chips with the verbatim snippet behind
 * them, and renders a visible ⚠ for a marker that resolves to nothing. That machinery is
 * the product's central claim made interactive, and it was written against the session `Source`
 * shape. The run workspace was rendering its report as pre-wrapped plain text instead — no
 * headings, no chips, and, worse, **no ⚠**: a broken citation in a run's report looked exactly
 * like a working one.
 *
 * Adapting is right here and re-implementing would be wrong. Two renderers for one claim
 * is the "two homes for one rule" failure AGENTS.md is mostly about, and the second home
 * is always the one that loses the fix.
 *
 * The adapter is deliberately lossy in one direction only: it **drops** sources with no
 * citation index rather than numbering them. A retrieved-but-uncited source has no number,
 * and inventing one would make a marker resolve to a source the report never cited.
 */

/**
 * Cited sources, numbered by `citation_index`, carrying every evidence snippet extracted
 * from them.
 *
 * The snippets are what the popover shows, so a reader checking `[3]` sees the text the
 * run actually retrieved. Blank snippets are filtered out: the engine blanks one it could
 * not find in the retrieved text, and an empty quotation in a popover reads as "there is
 * nothing to see here" rather than as the honest "this could not be attested" the Evidence
 * tab says.
 */
export function citedSources(graph: RunGraph): Source[] {
  const snippetsBySource = new Map<string, string[]>();
  for (const e of graph.evidence) {
    if (!e.snippet) continue;
    const list = snippetsBySource.get(e.source_id) ?? [];
    // The same page commonly backs several facts; duplicates add nothing to a popover.
    if (!list.includes(e.snippet)) list.push(e.snippet);
    snippetsBySource.set(e.source_id, list);
  }

  return graph.sources
    .filter((s) => s.citation_index !== null)
    .map((s) => {
      const snippets = snippetsBySource.get(s.id) ?? [];
      return {
        index: s.citation_index as number,
        url: s.url,
        title: s.title ?? "",
        snippet: snippets[0] ?? "",
        snippets,
      };
    })
    .sort((a, b) => a.index - b.index);
}

/**
 * Which `[n]` markers the report text uses, whether or not they resolve.
 *
 * Used to say "3 of 14 citations in this report resolve to nothing" without waiting for
 * the backend's `citation_resolution_rate`, which is `null` — genuinely unmeasured — on
 * every run that finished before it was recorded. Counting markers in the text we are
 * about to render is a different measurement and is labelled as one: it is what *this
 * page* can see, not the run's recorded rate.
 *
 * Matches grouped markers (`[1, 3]`) for the same reason the renderer does: 42% of the
 * citation references in a measured real report were inside grouped brackets, and a
 * single-number pattern reported them as absent rather than as unresolved.
 */
export function markersIn(markdown: string): number[] {
  const found = new Set<number>();
  const all = /\[(\d+(?:\s*,\s*\d+)*)\]/g;
  let m: RegExpExecArray | null;
  while ((m = all.exec(markdown)) !== null) {
    for (const part of m[1].split(",")) {
      const n = Number(part.trim());
      if (Number.isFinite(n)) found.add(n);
    }
  }
  return [...found].sort((a, b) => a - b);
}

/**
 * How many distinct markers in this text resolve to a cited source, and how many do not.
 *
 * `null` when the report makes no citable claim at all — the unmeasured-vs-zero rule. A
 * report with no markers and a report whose every marker is broken are opposite findings,
 * and `0 / 0 = NaN` is not a third option.
 */
export function markerResolution(
  markdown: string,
  sources: Source[],
): { resolved: number; unresolved: number; total: number } | null {
  const markers = markersIn(markdown);
  if (markers.length === 0) return null;
  const known = new Set(sources.map((s) => s.index));
  const resolved = markers.filter((n) => known.has(n)).length;
  return { resolved, unresolved: markers.length - resolved, total: markers.length };
}
