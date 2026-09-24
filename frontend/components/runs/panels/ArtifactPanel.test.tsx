import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { RunGraph, RunVerification } from "@/lib/types";

import { ArtifactPanel } from "./ArtifactPanel";

/**
 * The prompts a run ran under, reported beside the verifier's verdict (scope freeze §10,
 * D-3). A run whose agents were reconfigured passes every check — the hashes are real hashes
 * of what really ran — so a bare "every check passed" would say nothing about the
 * instructions behind it. Only the run's recorded provenance is used, and never prompt text.
 */

const verification = vi.hoisted(() => ({
  state: { data: undefined, isLoading: false, isError: false } as {
    data: RunVerification | undefined;
    isLoading: boolean;
    isError: boolean;
  },
}));

vi.mock("@/hooks/runs", () => ({
  useV2Verification: () => verification.state,
}));

const CHECKS = [
  "bundle_integrity",
  "report_integrity",
  "evidence_integrity",
  "citation_resolution",
  "claim_evidence_linkage",
  "approval_chain",
].map((name) => ({ name, passed: true, detail: null }));

const HASH = "9".repeat(64);

function verified(over: Partial<RunVerification> = {}): RunVerification {
  return {
    assembled: true,
    reason: null,
    passed: true,
    frozen: true,
    checks: CHECKS,
    bundle_version: 2,
    prompt_overrides_status: "NONE",
    prompt_provenance: [
      {
        purpose: "planner.main",
        role: "planner",
        policy: "OVERRIDABLE",
        overridden: false,
        effective_prompt_sha256: "1".repeat(64),
      },
      {
        purpose: "critic.citation_verify",
        role: "critic",
        policy: "PROTECTED",
        overridden: false,
        effective_prompt_sha256: "2".repeat(64),
      },
    ],
    ...over,
  };
}

const GRAPH = {
  run: { id: "run-1" },
  plans: [],
  sources: [],
  evidence: [],
  revisions: [],
  claims: [],
  claim_evidence_links: [],
  contradictions: [],
  reviews: [],
  artifact: {
    id: "a1",
    artifact_hash: "f".repeat(64),
    format_version: 2,
    review_id: "rv1",
    review_gate: "REPORT",
    review_decision: "APPROVED",
    revision_id: "r1",
    demo: false,
    created_at: "2026-09-24T00:00:00Z",
  },
} as unknown as RunGraph;

function show(state: Partial<typeof verification.state>) {
  verification.state = { data: undefined, isLoading: false, isError: false, ...state };
  return render(<ArtifactPanel graph={GRAPH} />);
}

beforeEach(() => {
  verification.state = { data: undefined, isLoading: false, isError: false };
});

describe("prompt provenance beside the verdict", () => {
  it("says nothing extra for a run on shipped prompts", () => {
    show({ data: verified() });
    expect(screen.queryByText(/Custom instructions/)).not.toBeInTheDocument();
    expect(screen.getByText(/Every check passed against the frozen bundle/)).toBeInTheDocument();
  });

  it("names each replaced role with its hash, above the checks", () => {
    show({
      data: verified({
        prompt_overrides_status: "APPLIED",
        prompt_provenance: [
          {
            purpose: "critic.research",
            role: "critic",
            policy: "OVERRIDABLE",
            overridden: true,
            effective_prompt_sha256: HASH,
          },
        ],
      }),
    });
    const note = screen.getByRole("note");
    expect(note).toHaveTextContent("Custom instructions in force");
    expect(note).toHaveTextContent("Critic");
    expect(screen.getByLabelText(`Critic prompt SHA-256: ${HASH}`)).toBeInTheDocument();
    expect(note).toHaveTextContent(/not that they were sound/);
    // Above the verdict, not below it.
    const firstCheck = screen.getByText("Bundle integrity");
    expect(note.compareDocumentPosition(firstCheck) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("never shows prompt text or an internal purpose name", () => {
    const { container } = show({
      data: verified({
        prompt_overrides_status: "APPLIED",
        prompt_provenance: [
          {
            purpose: "critic.research",
            role: "critic",
            policy: "OVERRIDABLE",
            overridden: true,
            effective_prompt_sha256: HASH,
          },
        ],
      }),
    });
    const text = container.textContent ?? "";
    expect(text).not.toContain("critic.research");
    expect(text).not.toContain("citation_verify");
    expect(text).not.toContain("effective_prompt");
  });

  it("reports overrides that could not be used", () => {
    show({ data: verified({ prompt_overrides_status: "UNUSABLE" }) });
    expect(screen.getByRole("note")).toHaveTextContent(
      /configured for this run but could not be used, so it ran on the shipped prompts/,
    );
    expect(screen.queryByText(/Custom instructions in force/)).not.toBeInTheDocument();
  });

  it("says nothing for a v1 bundle, which recorded no prompts", () => {
    show({
      data: verified({ bundle_version: 1, prompt_overrides_status: null, prompt_provenance: [] }),
    });
    expect(screen.queryByRole("note")).not.toBeInTheDocument();
  });
});

describe("the verifier's own states are unchanged", () => {
  it("still shows loading", () => {
    show({ isLoading: true });
    expect(screen.getByText(/Running the verifier/)).toBeInTheDocument();
    expect(screen.queryByRole("note")).not.toBeInTheDocument();
  });

  it("still says a failed request is not a failed check", () => {
    show({ isError: true });
    expect(screen.getByText(/this page failing to ask, not a check failing/)).toBeInTheDocument();
  });

  it("still says an unassembled bundle is not a failure", () => {
    show({ data: { assembled: false, reason: "NO_REVISION", passed: null, checks: [] } });
    expect(screen.getByText(/This is not a failure/)).toBeInTheDocument();
    expect(screen.queryByRole("note")).not.toBeInTheDocument();
  });
});
