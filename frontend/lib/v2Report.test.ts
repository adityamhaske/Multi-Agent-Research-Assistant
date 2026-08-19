import { describe, expect, it } from "vitest";

import { citedSources, markerResolution, markersIn } from "./v2Report";
import type { V2RunGraph } from "./types";

/**
 * The adapter that lets the V2 report reuse the citation renderer.
 *
 * Its whole job is one rule: **a source with no citation index does not get a number**.
 * Numbering an uncited source would make a `[3]` in the prose resolve to a page the report
 * never cited — which is the citation chip claiming provenance it does not have, on the one
 * surface where that claim is the product.
 */

function graph(over: Partial<V2RunGraph> = {}): V2RunGraph {
  return {
    run: {} as V2RunGraph["run"],
    plans: [],
    sources: [
      {
        id: "s1",
        url: "https://a.invalid/1",
        title: "One",
        kind: "WEB",
        retrieval_status: "FETCHED",
        citation_index: 2,
        corpus_document_id: null,
      },
      {
        id: "s2",
        url: "https://a.invalid/2",
        title: "Two",
        kind: "WEB",
        retrieval_status: "FETCHED",
        citation_index: 1,
        corpus_document_id: null,
      },
      {
        id: "s3",
        url: "https://a.invalid/3",
        title: "Never cited",
        kind: "WEB",
        retrieval_status: "FETCHED",
        citation_index: null,
        corpus_document_id: null,
      },
    ],
    evidence: [
      {
        id: "e1",
        source_id: "s1",
        sequence: 1,
        task_id: null,
        snippet: "first fact",
        content_hash: "a",
        key_fact: null,
        provenance_state: "ATTESTED",
        attested_against: null,
        attestation_run_at: null,
      },
      {
        id: "e2",
        source_id: "s1",
        sequence: 2,
        task_id: null,
        snippet: "second fact",
        content_hash: "b",
        key_fact: null,
        provenance_state: "ATTESTED",
        attested_against: null,
        attestation_run_at: null,
      },
      {
        id: "e3",
        source_id: "s1",
        sequence: 3,
        task_id: null,
        snippet: "first fact",
        content_hash: "c",
        key_fact: null,
        provenance_state: "ATTESTED",
        attested_against: null,
        attestation_run_at: null,
      },
      {
        id: "e4",
        source_id: "s3",
        sequence: 4,
        task_id: null,
        snippet: "from an uncited source",
        content_hash: "d",
        key_fact: null,
        provenance_state: "UNCHECKED",
        attested_against: null,
        attestation_run_at: null,
      },
      {
        id: "e5",
        source_id: "s2",
        sequence: 5,
        task_id: null,
        snippet: "",
        content_hash: "e",
        key_fact: null,
        provenance_state: "UNATTESTED",
        attested_against: null,
        attestation_run_at: null,
      },
    ],
    revisions: [],
    claims: [],
    claim_evidence_links: [],
    contradictions: [],
    reviews: [],
    artifact: null,
    ...over,
  };
}

describe("citedSources", () => {
  it("drops a source the report never cited rather than numbering it", () => {
    const sources = citedSources(graph());
    expect(sources.map((s) => s.index)).toEqual([1, 2]);
    expect(sources.some((s) => s.title === "Never cited")).toBe(false);
  });

  it("carries every distinct snippet from a source, so a popover shows the real text", () => {
    const two = citedSources(graph()).find((s) => s.index === 2)!;
    expect(two.snippets).toEqual(["first fact", "second fact"]);
    expect(two.snippet).toBe("first fact");
  });

  it("omits a blanked snippet instead of showing an empty quotation", () => {
    // The engine blanks a snippet it could not find in the retrieved text. An empty
    // quotation reads as "nothing to see"; the Evidence tab says what actually happened.
    const one = citedSources(graph()).find((s) => s.index === 1)!;
    expect(one.snippets).toEqual([]);
  });

  it("orders by citation number, not by retrieval order", () => {
    expect(citedSources(graph()).map((s) => s.index)).toEqual([1, 2]);
  });
});

describe("markersIn", () => {
  it("finds grouped markers, which are most of them in real reports", () => {
    expect(markersIn("a [1] b [2, 3] c [4,5]")).toEqual([1, 2, 3, 4, 5]);
  });

  it("counts a repeated marker once", () => {
    expect(markersIn("[1] and again [1]")).toEqual([1]);
  });

  it("finds none in text with no citations", () => {
    expect(markersIn("no citations here")).toEqual([]);
  });
});

describe("markerResolution", () => {
  const sources = citedSources(graph());

  it("returns null when the report cites nothing — unmeasured is not zero", () => {
    expect(markerResolution("A report that asserts nothing citable.", sources)).toBeNull();
  });

  it("separates markers that resolve from markers that do not", () => {
    expect(markerResolution("[1] and [2] and [9]", sources)).toEqual({
      resolved: 2,
      unresolved: 1,
      total: 3,
    });
  });

  it("reports a clean report as fully resolved", () => {
    expect(markerResolution("[1] [2]", sources)).toEqual({
      resolved: 2,
      unresolved: 0,
      total: 2,
    });
  });
});
