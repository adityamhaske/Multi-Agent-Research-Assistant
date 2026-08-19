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
const planMutate = vi.fn();
vi.mock("@/hooks/v2", () => {
  return {
    useV2ReportReview: () => ({ mutate, isPending: false, isError: false, error: null }),
    useV2PlanReview: () => ({ mutate: planMutate, isPending: false, isError: false, error: null }),
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


describe("Plan gate", () => {
  const awaitingPlan = () =>
    graph({
      run: { ...graph().run, status: "AWAITING_PLAN" },
      plans: [
        {
          id: "pl1",
          version: 1,
          tasks: [
            {
              id: 1,
              query: "survey memory architectures",
              rationale: "",
              subtopics: [],
              include: false,
              source_hint: "",
            },
          ],
          outline_sections: ["Findings", "Limitations"],
          origin: "MODEL_PROPOSED",
          approved_at: null,
        },
      ],
      revisions: [],
      claims: [],
      claim_evidence_links: [],
    });

  it("opens on the plan when the design gate is waiting", () => {
    view(awaitingPlan());
    expect(screen.getByText("Research plan")).toBeInTheDocument();
    expect(screen.getByText("survey memory architectures")).toBeInTheDocument();
    expect(screen.getByText("Findings")).toBeInTheDocument();
  });

  it("never implies the plan approval approves a report or an artifact", () => {
    view(awaitingPlan());
    expect(screen.getByText(/Approving the plan starts the research/)).toBeInTheDocument();
    expect(screen.getByText(/approve a report and creates no artifact/)).toBeInTheDocument();
    expect(screen.queryByText("Verified artifact")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Approve report" })).not.toBeInTheDocument();
  });

  it("sends the plan approval", async () => {
    view(awaitingPlan());
    fireEvent.click(screen.getByRole("button", { name: "Approve plan" }));
    await waitFor(() => expect(planMutate).toHaveBeenCalledWith({ decision: "APPROVED" }));
  });

  it("sends requested changes with the feedback typed", async () => {
    view(awaitingPlan());
    fireEvent.change(screen.getByLabelText("Changes to request"), {
      target: { value: "Cover the adversarial split." },
    });
    fireEvent.click(screen.getByRole("button", { name: "Request changes" }));
    await waitFor(() =>
      expect(planMutate).toHaveBeenCalledWith({
        decision: "REWORK_REQUESTED",
        feedback: "Cover the adversarial split.",
      }),
    );
  });

  it("closes the gate controls once the plan has been decided", () => {
    view(
      graph({
        run: { ...graph().run, status: "RUNNING" },
        plans: [
          {
            id: "pl1",
            version: 1,
            tasks: [
              { id: 1, query: "q", rationale: "", subtopics: [], include: false, source_hint: "" },
            ],
            outline_sections: [],
            origin: "MODEL_PROPOSED",
            approved_at: "2026-08-18T00:00:00Z",
          },
        ],
        reviews: [
          {
            id: "rv-plan",
            sequence: 1,
            gate: "PLAN",
            decision: "APPROVED",
            revision_id: null,
            plan_version_id: "pl1",
            feedback: null,
            reviewed_hash: "e".repeat(64),
            created_at: "2026-08-18T00:00:00Z",
          },
        ],
      }),
    );
    fireEvent.click(screen.getByRole("tab", { name: "Plan" }));
    expect(screen.queryByRole("button", { name: "Approve plan" })).not.toBeInTheDocument();
    // The closed gate names the decision that closed it, rather than saying only that the
    // gate is shut: "approved" and "reworked" are different histories.
    expect(screen.getByText(/You approved this plan/)).toBeInTheDocument();
  });
});

describe("gate routing", () => {
  it("moves to the review when a watched run REACHES the gate", () => {
    // The defect the end-to-end journey found: the opening tab was chosen once, so a run
    // watched from RUNNING to AWAITING_REVIEW left the decision behind another tab.
    const running = graph({
      run: { ...graph().run, status: "RUNNING" },
      revisions: [],
      claims: [],
      claim_evidence_links: [],
    });
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const { rerender } = render(
      <QueryClientProvider client={qc}>
        <RunWorkspace graph={running} />
      </QueryClientProvider>,
    );
    expect(screen.queryByText("What you are approving")).not.toBeInTheDocument();

    rerender(
      <QueryClientProvider client={qc}>
        <RunWorkspace graph={graph()} />
      </QueryClientProvider>,
    );
    expect(screen.getByText("What you are approving")).toBeInTheDocument();
  });

  it("does not yank the user off a tab they chose while nothing is waiting", () => {
    const done = graph({ run: { ...graph().run, status: "COMPLETED" } });
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const { rerender } = render(
      <QueryClientProvider client={qc}>
        <RunWorkspace graph={done} />
      </QueryClientProvider>,
    );
    fireEvent.click(screen.getByRole("tab", { name: /Sources/ }));
    expect(screen.getByText("Retrieved, not cited")).toBeInTheDocument();

    rerender(
      <QueryClientProvider client={qc}>
        <RunWorkspace graph={{ ...done, run: { ...done.run, cost_usd: 0.02 } }} />
      </QueryClientProvider>,
    );
    expect(screen.getByText("Retrieved, not cited")).toBeInTheDocument();
  });
});

/**
 * The workspace as a *control*, not just a renderer.
 *
 * These cover the four things the first version got wrong about being one: the tab strip
 * was `role="tab"` and nothing else (so a keyboard user could reach it and not move within
 * it), the chosen tab lived only in component state (so refresh, Back and a shared link all
 * lost the reader's place), the report was pre-wrapped plain text (so a citation that
 * resolved to nothing looked exactly like one that resolved), and following a claim into
 * the evidence ledger filtered it silently.
 */
describe("workspace navigation", () => {
  it("wires each tab to its panel, with one tab stop for the whole strip", () => {
    view(graph());
    const selected = screen.getByRole("tab", { selected: true });
    expect(selected).toHaveAttribute("aria-controls", "run-panel-review");
    expect(selected).toHaveAttribute("tabindex", "0");

    const other = screen.getByRole("tab", { name: /Evidence/ });
    expect(other).toHaveAttribute("tabindex", "-1");

    const panel = screen.getByRole("tabpanel");
    expect(panel).toHaveAttribute("id", "run-panel-review");
    expect(panel).toHaveAttribute("aria-labelledby", "run-tab-review");
  });

  it("moves between tabs with the arrow keys", () => {
    view(graph());
    const strip = screen.getByRole("tablist");
    fireEvent.keyDown(strip, { key: "ArrowRight" });
    expect(screen.getByRole("tab", { selected: true })).toHaveAccessibleName(/Artifact/);
    fireEvent.keyDown(strip, { key: "Home" });
    expect(screen.getByRole("tab", { selected: true })).toHaveAccessibleName(/Report/);
  });

  it("opens on the tab a deep link names", () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <RunWorkspace graph={graph()} initialTab="sources" />
      </QueryClientProvider>,
    );
    expect(screen.getByText("Retrieved, not cited")).toBeInTheDocument();
  });

  it("reports a tab a person picked, so the page can put it in the URL", () => {
    const onTabChange = vi.fn();
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <RunWorkspace graph={graph()} onTabChange={onTabChange} />
      </QueryClientProvider>,
    );
    fireEvent.click(screen.getByRole("tab", { name: /Claims/ }));
    expect(onTabChange).toHaveBeenCalledWith("claims");
  });

  it("does not rewrite the URL when a gate re-routes the view by itself", () => {
    const onTabChange = vi.fn();
    const running = graph({ run: { ...graph().run, status: "RUNNING" } });
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const { rerender } = render(
      <QueryClientProvider client={qc}>
        <RunWorkspace graph={running} onTabChange={onTabChange} />
      </QueryClientProvider>,
    );
    rerender(
      <QueryClientProvider client={qc}>
        <RunWorkspace graph={graph()} onTabChange={onTabChange} />
      </QueryClientProvider>,
    );
    expect(screen.getByText("What you are approving")).toBeInTheDocument();
    expect(onTabChange).not.toHaveBeenCalled();
  });
});

describe("the evidence chain", () => {
  it("renders the report as markdown, with a resolved citation and a visible ⚠ for one that is not", () => {
    view(
      graph({
        revisions: [
          {
            id: "r1",
            version: 1,
            report_markdown: "# Findings\n\nGrounding raised accuracy [1], unlike [9].",
            report_hash: "b".repeat(64),
            evidence_watermark: 1,
            created_at: "2026-08-18T00:00:00Z",
          },
        ],
      }),
    );
    fireEvent.click(screen.getByRole("tab", { name: /Report/ }));

    // Markdown, not a literal "#".
    expect(screen.getByRole("heading", { name: "Findings" })).toBeInTheDocument();
    // [1] resolves to source 1 and becomes a chip that names it.
    expect(
      screen.getByRole("button", { name: /Source 1: Paper One/ }),
    ).toBeInTheDocument();
    // [9] resolves to nothing, and says so rather than rendering clean.
    expect(screen.getByTitle(/Citation \[9\] does not resolve to a source/)).toBeInTheDocument();
    expect(
      screen.getByText(/1 of 2 citation markers in this text resolve to nothing/),
    ).toBeInTheDocument();
  });

  it("says a filtered evidence ledger is filtered, and offers the way back", () => {
    view(graph());
    fireEvent.click(screen.getByRole("tab", { name: /Claims/ }));
    fireEvent.click(screen.getByText("1 supporting evidence item"));
    fireEvent.click(screen.getByText(/Inspect this claim's evidence in full/));

    expect(screen.getByText(/showing the 1 evidence item behind one claim, out of 1/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Show all evidence" }));
    expect(screen.queryByText(/showing the 1 evidence item/)).not.toBeInTheDocument();
  });

  it("spells out a claim's verification state instead of printing the wire enum", () => {
    view(graph());
    fireEvent.click(screen.getByRole("tab", { name: /Claims/ }));
    const chip = screen.getAllByText("Verification not run")[0]!;
    expect(chip.getAttribute("title")).toMatch(/not a judgement that the claim is true or false/i);
    expect(screen.queryByText("UNCHECKED")).not.toBeInTheDocument();
  });

  it("groups cited sources apart from ones the report never referenced", () => {
    view(graph());
    fireEvent.click(screen.getByRole("tab", { name: /Sources/ }));
    expect(screen.getByRole("heading", { name: /Cited sources \(1\)/ })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /Retrieved, never cited \(1\)/ })).toBeInTheDocument();
  });

  it("does not claim the detector ran when there is no record either way", () => {
    view(graph({ contradictions: [] }));
    fireEvent.click(screen.getByRole("tab", { name: /Contradictions/ }));
    expect(screen.getByText("No conflicting claims recorded")).toBeInTheDocument();
    // The old copy asserted "The detector ran and surfaced no pair" from an empty list.
    expect(screen.queryByText(/The detector ran and surfaced no pair/)).not.toBeInTheDocument();
    expect(screen.getByText(/records itself as unavailable/)).toBeInTheDocument();
  });

  it("reports a detector that could not run as a gap, not as a clean bill of health", () => {
    view(
      graph({
        contradictions: [
          {
            id: "x0",
            source_a_id: null,
            source_b_id: null,
            evidence_a_id: null,
            evidence_b_id: null,
            quote_a: null,
            quote_b: null,
            summary_a: null,
            summary_b: null,
            nature: null,
            dimension: "UNCLASSIFIED",
            detection_state: "DETECTOR_UNAVAILABLE",
            review_state: "UNREVIEWED",
          },
        ],
      }),
    );
    fireEvent.click(screen.getByRole("tab", { name: /Contradictions/ }));
    expect(screen.getByText(/could not run for this run/)).toBeInTheDocument();
    expect(screen.getByText(/not a clean bill of health/)).toBeInTheDocument();
  });
});

describe("the review gate", () => {
  it("shows the hash the approval will sign", () => {
    view(graph());
    expect(screen.getByText(/Approving signs this exact text/)).toBeInTheDocument();
    expect(screen.getByLabelText(/Report hash being approved/)).toBeInTheDocument();
  });

  it("previews the verifier's verdict before the decision, marked as a preview", () => {
    view(graph());
    expect(screen.getByText("What the verifier would say")).toBeInTheDocument();
    expect(screen.getByText(/nothing is frozen until you approve/)).toBeInTheDocument();
  });
});
