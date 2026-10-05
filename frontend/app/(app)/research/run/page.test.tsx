import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { RunGraph } from "@/lib/types";

import RunPage from "./page";

/**
 * Every `dt`/`dd` on the run page sits inside a `dl`.
 *
 * The Evidence Chain Overview put its four figure pairs in a plain grid `div`, which is not
 * valid HTML: a term/description pair has no meaning outside a description list, and
 * assistive technology reads it as loose text. This renders the page for a finished run —
 * the state the overview appears in — and checks every pair on it, not only the one block.
 */

const current = vi.hoisted(() => ({ graph: null as unknown }));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams("id=run-1"),
}));
vi.mock("@/components/ActiveProject", () => ({ useActiveProject: () => ({ active: null }) }));
vi.mock("@/hooks/runs", async (original) => ({
  ...(await original<typeof import("@/hooks/runs")>()),
  useRun: () => ({
    data: current.graph,
    isLoading: false,
    error: null,
    refetch: vi.fn(),
    isFetching: false,
  }),
  useRunStream: () => ({ events: [], degraded: false }),
}));
// The workspace below the header has its own tests; only the header's markup is at issue.
vi.mock("@/components/runs/RunWorkspace", () => ({
  RunWorkspace: () => null,
  CancelButton: () => null,
}));
vi.mock("@/components/runs/RunProgress", () => ({ RunProgress: () => null }));

function graph(over: Partial<RunGraph> = {}): RunGraph {
  const base: RunGraph = {
    run: {
      id: "run-1",
      project_id: "p1",
      question: "Does grounding help?",
      status: "COMPLETED",
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
        cited_indices: [1],
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

describe("the run page's description lists", () => {
  it("shows the Evidence Chain Overview for a finished run", () => {
    current.graph = graph();
    render(<RunPage />);
    expect(screen.getByText("Evidence Chain Overview")).toBeInTheDocument();
  });

  it("puts every term and description inside a dl", () => {
    current.graph = graph();
    const { container } = render(<RunPage />);
    const pairs = container.querySelectorAll("dt, dd");
    expect(pairs.length).toBeGreaterThanOrEqual(8); // the overview's four figures
    for (const el of pairs) {
      expect(el.closest("dl"), `${el.tagName} "${el.textContent}" has no dl`).not.toBeNull();
    }
  });
});

/**
 * A demo run must never read as research on the question that was asked.
 *
 * The demo's report answers a fixed question whatever was typed, fully cited, so a reader who
 * skims past a two-word badge reads an unrelated, confident answer as research on their own
 * question — which is what happened: a question about one company came back as a report on
 * retrieval-augmented generation. The badge stays; the page also says it in a sentence.
 */
describe("a demo run's page", () => {
  it("says plainly that nothing was researched and the question never reached a model", () => {
    current.graph = graph({ run: { ...graph().run, demo: true } });
    render(<RunPage />);
    const notice = screen.getByRole("note", { name: /demo run/i });
    expect(notice).toHaveTextContent("Demo run — no LLM research was performed");
    expect(notice).toHaveTextContent(
      "Your question was not sent to a model. This report is a scripted demonstration",
    );
  });

  it("is not shown on a run a model actually researched", () => {
    current.graph = graph({ run: { ...graph().run, demo: false } });
    render(<RunPage />);
    expect(screen.queryByRole("note", { name: /demo run/i })).toBeNull();
  });
});
