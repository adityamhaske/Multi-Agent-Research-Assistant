import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { MemoryAnswer } from "./memoryCitations";
import type { MemoryCitation } from "./types";

/**
 * Project-chat citations (docs/14 §5).
 *
 * The claim this milestone makes is "every answer traces back to a report a human
 * approved". These tests are where that claim is checkable in the UI: a marker either
 * resolves to a real report — with the excerpt it was drawn from — or renders as visibly
 * unverified. Silently inert text is the one outcome that must never happen, because it
 * looks identical to a working citation while proving nothing.
 */

const citation = (over: Partial<MemoryCitation> = {}): MemoryCitation => ({
  marker: "R1",
  session_id: "3f2504e0-4f89-11d3-9a0c-0305e82c3301",
  title: "How fast did solar capacity grow in 2025?",
  created_at: "2026-07-14T10:30:00Z",
  excerpt: "Global solar photovoltaic capacity grew 32 percent during 2025 [1].",
  ...over,
});

describe("MemoryAnswer citations", () => {
  it("renders a resolved [R1] as a chip carrying the report and its excerpt", () => {
    render(<MemoryAnswer markdown="Capacity grew sharply [R1]." citations={[citation()]} />);

    const chip = screen.getByRole("button", { name: /approved report: how fast did solar/i });
    expect(chip).toHaveTextContent("[R1]");
    expect(screen.getByText(/grew 32 percent during 2025/)).toBeInTheDocument();
  });

  it("links the chip to the report so the original sources stay one hop away", () => {
    render(<MemoryAnswer markdown="Capacity grew sharply [R1]." citations={[citation()]} />);

    const link = screen.getByRole("link", { name: /open the report/i });
    expect(link).toHaveAttribute(
      "href",
      "/session/3f2504e0-4f89-11d3-9a0c-0305e82c3301",
    );
  });

  it("flags a marker with no retrieved excerpt as unverified rather than hiding it", () => {
    render(<MemoryAnswer markdown="An unbacked claim [R9]." citations={[citation()]} />);

    const unverified = screen.getByTitle(/citation \[R9\] does not resolve/i);
    expect(unverified).toHaveTextContent("⚠[R9]");
    expect(screen.queryByRole("button", { name: /approved report/i })).toBeNull();
  });

  it("splits a grouped [R1, R2] into one chip per report", () => {
    render(
      <MemoryAnswer
        markdown="Two reports agree [R1, R2]."
        citations={[citation(), citation({ marker: "R2", title: "Second report" })]}
      />,
    );

    expect(screen.getByRole("button", { name: /how fast did solar/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /second report/i })).toBeInTheDocument();
  });

  it("leaves markers inside code blocks alone", () => {
    render(
      <MemoryAnswer markdown={"Literal:\n\n```\nuse [R1] here\n```"} citations={[citation()]} />,
    );

    expect(screen.queryByRole("button", { name: /approved report/i })).toBeNull();
    expect(screen.getByText(/use \[R1\] here/)).toBeInTheDocument();
  });

  it("renders an answer with no citations without inventing any", () => {
    render(
      <MemoryAnswer
        markdown="The research approved in this project doesn't cover that."
        citations={[]}
      />,
    );

    expect(screen.getByText(/doesn't cover that/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /approved report/i })).toBeNull();
  });

  it("does not confuse a report's own [1] markers with retrieval markers", () => {
    // Excerpts keep the source markers the report used, and they surface in the popover.
    // Only [R{n}] belongs to the chat layer; a bare [1] in the answer is not a chip here.
    render(<MemoryAnswer markdown="Bare marker [1] stays text." citations={[citation()]} />);

    expect(screen.queryByRole("button", { name: /approved report/i })).toBeNull();
    expect(screen.getByText(/bare marker \[1\] stays text/i)).toBeInTheDocument();
  });
});
