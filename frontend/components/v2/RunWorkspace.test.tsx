import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { V2RunGraph } from "@/lib/types";

import { RunWorkspace } from "./RunWorkspace";

/**
 * The workspace's job is to keep three distinctions visible, and these tests are about
 * exactly those:
 *
 *   retrieved ≠ verified · retrieved ≠ cited · a citation marker ≠ evidence
 *
 * A UI that collapsed any of them would still look fine. That is why each has a test that
 * fails on the *wording*, not just on the presence of a row.
 */

const mutate = vi.fn();
vi.mock("@/hooks/v2", () => {
  return {
    useV2ReportReview: () => ({ mutate, isPending: false, isError: false, error: null }),
    useV2Cancel: () => ({ mutate: vi.fn(), isPending: false, data: undefined }),
    useV2Verification: () => ({
      data: {
        assembled: true,
        reason: null,
        passed: true,
        frozen: true,
        checks: [
          { name: "bundle_integrity", passed: true, detail: null },
          { name: "report_integrity", passed: true, detail: null },
          { name: "evidence_integrity", passed: true, detail: null },
          { name: "citation_resolution", passed: true, detail: null },
          { name: "claim_evidence_linkage", passed: true, detail: null },
          { name: "approval_chain", passed: true, detail: null },
        ],
      },
      isLoading: false,
    }),
  };
});

function graph(over: Partial<V2RunGraph> = {}): V2RunGraph {
  const base: V2RunGraph = {
    run: {
      id: "run-1",
      project_id: "p1",
      question: "Does grounding help?",
      status: "AWAITING_REVIEW",
      depth: "fast",
      corpus_mode: false,
      demo: true,
      skip_plan_gate: true,
      model_routing: null,
      cost_usd: 0.01,
      tokens_input: 1,
      tokens_output: 1,
      elapsed_seconds: 2,
      citation_resolution_rate: null,
      error_message: null,
      cancelled_at: null,
      created_at: "2026-08-18T00:00:00Z",
      updated_at: "2026-08-18T00:00:00Z",
    },
    plans: [],
    sources: [
      {
        id: "s1",
        url: "https://a.invalid/one",
        title: "Paper One",
        kind: "WEB",
        retrieval_status: "FETCHED",
        citation_index: 1,
        corpus_document_id: null,
      },
      {
        id: "s2",
        url: "https://a.invalid/two",
        title: "Never referenced",
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
        task_id: "1",
        snippet: "Grounding raised accuracy by nine points.",
        content_hash: "a".repeat(64),
        key_fact: "accuracy up",
        provenance_state: "UNCHECKED",
        attested_against: null,
        attestation_run_at: null,
      },
    ],
    revisions: [
      {
        id: "r1",
        version: 1,
        report_markdown: "# Findings\n\nGrounding raised accuracy [1].",
        report_hash: "b".repeat(64),
        evidence_watermark: 1,
        created_at: "2026-08-18T00:00:00Z",
      },
    ],
    claims: [
      {
        id: "c1",
        revision_id: "r1",
        position: 0,
        text: "Grounding raised accuracy [1].",
        extraction_method: "DERIVED_FROM_REPORT",
        verification_state: "UNCHECKED",
        verification_method: "NOT_RUN",
        lineage_id: null,
      },
      {
        id: "c2",
        revision_id: "r1",
        position: 1,
        text: "An assertion nothing backs.",
        extraction_method: "DERIVED_FROM_REPORT",
        verification_state: "UNCHECKED",
        verification_method: "NOT_RUN",
        lineage_id: null,
      },
    ],
    claim_evidence_links: [
      { id: "l1", claim_id: "c1", evidence_id: "e1", stance: "SUPPORTS", origin: "CITATION_MARKER" },
    ],
    contradictions: [],
    reviews: [],
    artifact: null,
  };
  return { ...base, ...over };
}

function view(g: V2RunGraph) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <RunWorkspace graph={g} />
    </QueryClientProvider>,
  );
}

describe("RunWorkspace", () => {
  it("opens on Review when a draft is waiting, so the decision is not buried", () => {
    view(graph());
    expect(screen.getByText("What you are approving")).toBeInTheDocument();
  });

  it("opens on Artifact once one exists", () => {
    view(
      graph({
        artifact: {
          id: "a1",
          artifact_hash: "c".repeat(64),
          format_version: 1,
          review_id: "rv1",
          review_gate: "REPORT",
          review_decision: "APPROVED",
          revision_id: "r1",
          demo: true,
          created_at: "2026-08-18T00:00:00Z",
        },
      }),
    );
    expect(screen.getByText("Verified artifact")).toBeInTheDocument();
  });

  it("says unchecked evidence is unchecked, not verified", () => {
    view(graph());
    fireEvent.click(screen.getByRole("tab", { name: /Evidence/ }));
    const chip = screen.getByText("Unchecked");
    expect(chip).toBeInTheDocument();
    expect(chip.getAttribute("title")).toMatch(/not the same as verified/i);
  });

  it("marks a retrieved-but-uncited source and gives it no number", () => {
    view(graph());
    fireEvent.click(screen.getByRole("tab", { name: /Sources/ }));
    expect(screen.getByText("Retrieved, not cited")).toBeInTheDocument();
    expect(screen.getByText(/1 of 2 carry no citation number/)).toBeInTheDocument();
  });

  it("names claims that resolved to no evidence instead of hiding them", () => {
    view(graph());
    fireEvent.click(screen.getByRole("tab", { name: /Claims/ }));
    expect(screen.getByText(/No evidence resolved for this claim/)).toBeInTheDocument();
    expect(screen.getByText("1 supporting evidence item")).toBeInTheDocument();
  });

  it("warns about unsupported claims and unchecked evidence before approval", () => {
    view(graph());
    expect(screen.getByText("1 of 2")).toBeInTheDocument();
    expect(screen.getByText(/1 claim resolved to no evidence/)).toBeInTheDocument();
    expect(screen.getByText(/Unchecked is not verified/)).toBeInTheDocument();
  });

  it("does not print an unmeasured citation rate as a number", () => {
    view(graph());
    expect(screen.getByText("not measured")).toBeInTheDocument();
  });

  it("states that approval creates a verifiable artifact", () => {
    view(graph());
    expect(screen.getByText(/verifiable research artifact/)).toBeInTheDocument();
  });

  it("sends the approve decision", async () => {
    view(graph());
    fireEvent.click(screen.getByRole("button", { name: "Approve report" }));
    await waitFor(() => expect(mutate).toHaveBeenCalledWith({ decision: "APPROVED" }));
  });

  it("sends a rework with the feedback typed", async () => {
    view(graph());
    fireEvent.change(screen.getByLabelText("Feedback for a rework"), {
      target: { value: "Say which split." },
    });
    fireEvent.click(screen.getByRole("button", { name: "Request rework" }));
    await waitFor(() =>
      expect(mutate).toHaveBeenCalledWith({
        decision: "REWORK_REQUESTED",
        feedback: "Say which split.",
      }),
    );
  });

  it("renders each verifier check from the backend rather than asserting success", () => {
    view(
      graph({
        artifact: {
          id: "a1",
          artifact_hash: "c".repeat(64),
          format_version: 1,
          review_id: "rv1",
          review_gate: "REPORT",
          review_decision: "APPROVED",
          revision_id: "r1",
          demo: true,
          created_at: "2026-08-18T00:00:00Z",
        },
      }),
    );
    for (const label of [
      "Bundle integrity",
      "Report integrity",
      "Evidence integrity",
      "Citation resolution",
      "Claim / evidence linkage",
      "Approval chain",
    ]) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
  });

  it("shows a conflicting pair with both quotations and refuses to resolve it", () => {
    view(
      graph({
        contradictions: [
          {
            id: "x1",
            source_a_id: "s1",
            source_b_id: "s2",
            evidence_a_id: null,
            evidence_b_id: null,
            quote_a: "Accuracy rose.",
            quote_b: "Accuracy fell.",
            summary_a: "grounding helps",
            summary_b: "grounding hurts",
            nature: "they cannot both describe the same benchmark",
            dimension: "UNCLASSIFIED",
            detection_state: "DETECTED",
            review_state: "UNREVIEWED",
          },
        ],
      }),
    );
    fireEvent.click(screen.getByRole("tab", { name: /Contradictions/ }));
    expect(screen.getByText("Accuracy rose.")).toBeInTheDocument();
    expect(screen.getByText("Accuracy fell.")).toBeInTheDocument();
    expect(screen.getByText(/Surfaced, not resolved/)).toBeInTheDocument();
    expect(screen.getByText(/could not be matched to exactly one evidence item/)).toBeInTheDocument();
  });

  it("offers all three exports once an artifact exists", () => {
    view(
      graph({
        artifact: {
          id: "a1",
          artifact_hash: "c".repeat(64),
          format_version: 1,
          review_id: "rv1",
          review_gate: "REPORT",
          review_decision: "APPROVED",
          revision_id: "r1",
          demo: true,
          created_at: "2026-08-18T00:00:00Z",
        },
      }),
    );
    expect(screen.getByRole("link", { name: "Markdown" })).toHaveAttribute(
      "href",
      expect.stringContaining("/v2/runs/run-1/export.md"),
    );
    expect(screen.getByRole("link", { name: "PDF" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Verification bundle" })).toHaveAttribute(
      "href",
      expect.stringContaining("/v2/runs/run-1/bundle.json"),
    );
  });

  it("keeps earlier revisions visible as versions rather than replacing them", () => {
    view(
      graph({
        revisions: [
          {
            id: "r1",
            version: 1,
            report_markdown: "first draft",
            report_hash: "b".repeat(64),
            evidence_watermark: 1,
            created_at: "2026-08-18T00:00:00Z",
          },
          {
            id: "r2",
            version: 2,
            report_markdown: "second draft",
            report_hash: "d".repeat(64),
            evidence_watermark: 1,
            created_at: "2026-08-18T00:01:00Z",
          },
        ],
      }),
    );
    fireEvent.click(screen.getByRole("tab", { name: /Report/ }));
    expect(screen.getByText(/Revision 2 of 2/)).toBeInTheDocument();
    expect(screen.getByText(/never overwrites one/)).toBeInTheDocument();
  });
});
