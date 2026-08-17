import { describe, expect, it } from "vitest";

import { parseCorpusLocator } from "./corpusLocator";

/**
 * `corpus://<document-id>#chars=<start>-<end>[&page=<n>]` is the locator the engine
 * writes for corpus evidence (backend/research_engine/corpus.py). Parsing it is what
 * lets a citation open the document it came from instead of rendering an `<a href>` the
 * browser cannot follow — which is what a corpus citation did before: a dead link
 * labelled "Open source ↗".
 */

describe("parseCorpusLocator", () => {
  it("reads the document id and the page out of a full locator", () => {
    const loc = parseCorpusLocator("corpus://abc123#chars=100-450&page=3");
    expect(loc).toEqual({ documentId: "abc123", page: 3, start: 100, end: 450 });
  });

  it("handles a locator with no page — text formats have no page structure", () => {
    const loc = parseCorpusLocator("corpus://doc-9#chars=0-200");
    expect(loc).toEqual({ documentId: "doc-9", page: null, start: 0, end: 200 });
  });

  it("handles a bare locator with no fragment at all", () => {
    expect(parseCorpusLocator("corpus://doc-9")).toEqual({
      documentId: "doc-9",
      page: null,
      start: null,
      end: null,
    });
  });

  it("returns null for a web source, so a normal citation keeps its link", () => {
    expect(parseCorpusLocator("https://example.com/paper")).toBeNull();
    expect(parseCorpusLocator("")).toBeNull();
  });

  it("returns null rather than a half-parsed locator when the id is missing", () => {
    // A locator with no document id cannot open anything; a `{documentId: ""}` would
    // build a URL that 404s and look like a working preview until it was clicked.
    expect(parseCorpusLocator("corpus://")).toBeNull();
    expect(parseCorpusLocator("corpus://#chars=0-10")).toBeNull();
  });
});
