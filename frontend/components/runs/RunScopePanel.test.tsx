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

  // AC-9: the run page shows the counts recorded on the row, not counts of its own.
  it("shows the recorded grounding counts, and why a run without a clean record stopped", () => {
    const { rerender } = render(
      <RunScopePanel
        run={run({
          corpus_mode: true,
          grounding_report: {
            status: "complete",
            claims_supported: 6,
            claims_rejected: 1,
            units_dropped: 2,
          },
        } as Partial<Run>)}
      />,
    );
    expect(
      screen.getByText(
        /6 supported, 1 kept out of the answer, 2 passage\(s\) removed/,
      ),
    ).toBeInTheDocument();

    rerender(
      <RunScopePanel
        run={run({
          corpus_mode: true,
          grounding_report: { status: "unmeasured", claims_unmeasured: 3 },
        } as Partial<Run>)}
      />,
    );
    expect(
      screen.getByText(
        /3 claim\(s\) could not be checked, so the report was not offered/,
      ),
    ).toBeInTheDocument();

    rerender(
      <RunScopePanel
        run={run({
          corpus_mode: true,
          grounding_report: { status: "no_evidence" },
        } as Partial<Run>)}
      />,
    );
    expect(
      screen.getByText(/Nothing was answered from outside them/),
    ).toBeInTheDocument();
  });

  it("says nothing for a run that searched the web", () => {
    const { container } = render(<RunScopePanel run={run({})} />);
    expect(container).toBeEmptyDOMElement();
  });
});
