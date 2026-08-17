/**
 * Parsing the engine's corpus locator (docs/07 §2, Phase 6).
 *
 * Corpus evidence cites `corpus://<document-id>#chars=<start>-<end>[&page=<n>]`
 * (backend/research_engine/corpus.py). The scheme is not one a browser can follow, so a
 * corpus citation used to render an `<a href="corpus://…">` labelled "Open source ↗"
 * that did nothing at all when clicked — a dead link is worse than no link, because it
 * says the source is checkable and then refuses to show it.
 *
 * The id is in the URL, so resolving a citation to a previewable document needs no
 * lookup table: parse, build the download URL, open the drawer.
 */

export interface CorpusLocator {
  documentId: string;
  /** 1-based page for paginated formats; null for text formats, which have none. */
  page: number | null;
  /** Character offsets of the cited span. Offsets are the load-bearing locator; the
   *  page exists so a human can flip to the right place. */
  start: number | null;
  end: number | null;
}

const PREFIX = "corpus://";

function intOrNull(value: string | undefined): number | null {
  if (value === undefined) return null;
  const n = Number.parseInt(value, 10);
  return Number.isNaN(n) ? null : n;
}

/**
 * The locator a URL describes, or `null` if it is not one.
 *
 * `null` for anything unparseable, including a `corpus://` URL with no document id —
 * a `documentId: ""` would build a URL that 404s and would look like a working preview
 * right up until someone clicked it.
 */
export function parseCorpusLocator(url: string): CorpusLocator | null {
  if (!url || !url.startsWith(PREFIX)) return null;

  const rest = url.slice(PREFIX.length);
  const hashAt = rest.indexOf("#");
  const documentId = hashAt === -1 ? rest : rest.slice(0, hashAt);
  if (!documentId) return null;

  const fragment = hashAt === -1 ? "" : rest.slice(hashAt + 1);
  const params = new URLSearchParams(fragment);
  const chars = params.get("chars");
  const [start, end] = chars ? chars.split("-") : [];

  return {
    documentId,
    page: intOrNull(params.get("page") ?? undefined),
    start: intOrNull(start),
    end: intOrNull(end),
  };
}
