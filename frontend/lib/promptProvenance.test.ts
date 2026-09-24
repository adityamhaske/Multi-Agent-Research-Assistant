import { describe, expect, it } from "vitest";

import type { PromptProvenanceEntry, RunVerification } from "@/lib/types";

import { provenanceNotice } from "./promptProvenance";

function entry(over: Partial<PromptProvenanceEntry>): PromptProvenanceEntry {
  return {
    purpose: "planner.main",
    role: "planner",
    policy: "OVERRIDABLE",
    overridden: false,
    effective_prompt_sha256: "a".repeat(64),
    ...over,
  };
}

function verification(over: Partial<RunVerification>): RunVerification {
  return {
    assembled: true,
    reason: null,
    passed: true,
    checks: [],
    bundle_version: 2,
    prompt_overrides_status: "NONE",
    prompt_provenance: [
      entry({}),
      entry({ purpose: "critic.citation_verify", role: "critic", policy: "PROTECTED" }),
    ],
    ...over,
  };
}

describe("provenanceNotice", () => {
  it("says nothing for a run on shipped prompts", () => {
    expect(provenanceNotice(verification({}))).toEqual({ replaced: [], unusable: false });
  });

  it("names each replaced prompt by role, with its hash", () => {
    const n = provenanceNotice(
      verification({
        prompt_overrides_status: "APPLIED",
        prompt_provenance: [
          entry({ overridden: true, effective_prompt_sha256: "b".repeat(64) }),
          entry({ purpose: "critic.research", role: "critic", overridden: true }),
          entry({ purpose: "critic.citation_verify", role: "critic", policy: "PROTECTED" }),
        ],
      }),
    );
    expect(n.replaced).toEqual([
      { role: "Planner", hash: "b".repeat(64) },
      { role: "Critic", hash: "a".repeat(64) },
    ]);
    expect(n.unusable).toBe(false);
  });

  it("never exposes an internal purpose name", () => {
    const n = provenanceNotice(
      verification({ prompt_provenance: [entry({ purpose: "critic.research", role: "critic", overridden: true })] }),
    );
    expect(JSON.stringify(n)).not.toContain("critic.research");
  });

  it("says nothing when overrides applied but reached no recorded purpose", () => {
    // A chat-only override is APPLIED and reaches no research purpose.
    expect(provenanceNotice(verification({ prompt_overrides_status: "APPLIED" }))).toEqual({
      replaced: [],
      unusable: false,
    });
  });

  it("reports overrides that could not be used", () => {
    expect(provenanceNotice(verification({ prompt_overrides_status: "UNUSABLE" }))).toEqual({
      replaced: [],
      unusable: true,
    });
  });

  it("says nothing for a v1 bundle, which recorded no prompts", () => {
    expect(
      provenanceNotice(
        verification({ bundle_version: 1, prompt_overrides_status: null, prompt_provenance: [] }),
      ),
    ).toEqual({ replaced: [], unusable: false });
  });

  it("says nothing when the verifier did not run or has not answered", () => {
    expect(provenanceNotice(undefined)).toEqual({ replaced: [], unusable: false });
    expect(
      provenanceNotice({ assembled: false, reason: "NO_REVISION", passed: null, checks: [] }),
    ).toEqual({ replaced: [], unusable: false });
  });
});
