import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { Run } from "@/lib/types";

import { RunScopePanel } from "./RunScopePanel";

/**
 * AC-11 (RFC V3.1 §6.3): the run page names what the run was limited to, and a run limited to
 * selected files on cloud routes is never presented as offline. The two badges answer
 * different questions — which evidence, and where the models ran — and only the run's own
 * record decides each.
 */

function run(fields: Partial<Run>): Run {
  return {
    corpus_mode: false,
    offline: false,
    corpus_selection: null,
    grounding_report: null,
    ...fields,
  } as Run;
}

describe("RunScopePanel", () => {
  it("shows a selection run on cloud routes as limited to its files, not as offline", () => {
    render(<RunScopePanel run={run({ corpus_mode: true })} />);
    expect(screen.getByText("Only selected files")).toBeInTheDocument();
    expect(screen.queryByText(/offline/i)).not.toBeInTheDocument();
  });

  it("shows Offline only when the run recorded it", () => {
    render(<RunScopePanel run={run({ corpus_mode: true, offline: true })} />);
    expect(screen.getByText("Offline")).toBeInTheDocument();
  });

  it("says nothing for a run that searched the web", () => {
    const { container } = render(<RunScopePanel run={run({})} />);
    expect(container).toBeEmptyDOMElement();
  });
});
