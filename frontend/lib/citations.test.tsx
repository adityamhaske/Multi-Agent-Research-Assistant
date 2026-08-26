import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Report, SourcesPanel, domainOf } from "./citations";
import { EXPECTED_CITED_INDICES, REAL_REPORT_BODY } from "./__fixtures__/realReport";
import type { Source } from "./types";

const source = (over: Partial<Source> = {}): Source => ({
  index: 1,
  url: "https://nasa.gov/report",
  title: "Atmospheric Study",
  snippet: "Rayleigh scattering dominates at short wavelengths.",
  ...over,
});

describe("domainOf", () => {
  it("strips protocol and www", () => {
    expect(domainOf("https://www.example.com/a/b?c=1")).toBe("example.com");
  });

  it("returns the input unchanged when it isn't a URL", () => {
    expect(domainOf("not a url")).toBe("not a url");
  });
});

describe("Report citations", () => {
  it("renders a resolved [n] marker as a chip carrying the source snippet and link", () => {
    render(<Report markdown="The sky appears blue [1]." sources={[source()]} />);

    const chip = screen.getByRole("button", { name: /source 1: atmospheric study/i });
    expect(chip).toHaveTextContent("[1]");

    // Popover content: verbatim supporting snippet + safe outbound link.
    expect(screen.getByText(/rayleigh scattering dominates/i)).toBeInTheDocument();
    const link = screen.getByRole("link", { name: /open source/i });
    expect(link).toHaveAttribute("href", "https://nasa.gov/report");
    expect(link).toHaveAttribute("rel", expect.stringContaining("noopener"));
  });

  it("flags an unresolved marker as visibly unverified instead of hiding it", () => {
    render(<Report markdown="An unbacked claim [7]." sources={[source()]} />);

    const unverified = screen.getByTitle(/citation \[7\] does not resolve/i);
    expect(unverified).toHaveTextContent("⚠[7]");
    expect(screen.queryByRole("button", { name: /source 7/i })).toBeNull();
  });

  it("renders multiple distinct citations in one paragraph", () => {
    render(
      <Report
        markdown="First [1] then second [2]."
        sources={[source(), source({ index: 2, title: "Second Source", url: "https://b.org/x" })]}
      />,
    );
    expect(screen.getByRole("button", { name: /source 1/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /source 2: second source/i })).toBeInTheDocument();
  });

  // ── Grouped citation markers (docs/12 M5) ────────────────────────────────────
  //
  // Found by the first real-model eval. The synthesizer writes `[1, 3]` when a sentence
  // rests on several sources; the old single-number pattern silently left those as inert
  // text — no chip, no link, and no ⚠ either, so an unresolvable citation could render
  // with the product never admitting it. 42% of citation references in the measured
  // report were inside grouped brackets.

  it("renders a grouped [1, 3] marker as one chip per source", () => {
    render(
      <Report
        markdown="Both agree on this point [1, 3]."
        sources={[source(), source({ index: 3, title: "Third Source", url: "https://c.org/y" })]}
      />,
    );

    expect(screen.getByRole("button", { name: /source 1: atmospheric study/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /source 3: third source/i })).toBeInTheDocument();
  });

  it("renders every source in a long grouped marker", () => {
    const sources = [1, 2, 3, 4, 6].map((index) =>
      source({ index, title: `Source ${index}`, url: `https://s${index}.example/x` }),
    );
    render(<Report markdown="A well-supported claim [1, 2, 3, 4, 6]." sources={sources} />);

    for (const index of [1, 2, 3, 4, 6]) {
      expect(screen.getByRole("button", { name: new RegExp(`source ${index}:`, "i") })).toBeInTheDocument();
    }
  });

  it("still flags an unresolved number inside a group — the failure that used to hide", () => {
    render(<Report markdown="Partly backed [1, 99]." sources={[source()]} />);

    expect(screen.getByRole("button", { name: /source 1/i })).toBeInTheDocument();
    expect(screen.getByTitle(/citation \[99\] does not resolve/i)).toHaveTextContent("⚠[99]");
  });

  it("parses grouped markers regardless of internal spacing", () => {
    const sources = [source(), source({ index: 3, title: "Third", url: "https://c.org/y" })];
    for (const markdown of ["Claim [1,3].", "Claim [1, 3].", "Claim [1 , 3]."]) {
      const { unmount } = render(<Report markdown={markdown} sources={sources} />);
      expect(screen.getByRole("button", { name: /source 1/i })).toBeInTheDocument();
      expect(screen.getByRole("button", { name: /source 3/i })).toBeInTheDocument();
      unmount();
    }
  });

  it("leaves bracketed numbers inside code spans alone", () => {
    render(<Report markdown="Index it with `arr[2]` directly." sources={[source({ index: 2 })]} />);

    expect(screen.queryByRole("button", { name: /source 2/i })).toBeNull();
    expect(screen.getByText("arr[2]")).toBeInTheDocument();
  });

  it("renders markdown structure (headings, lists) via the typography pipeline", () => {
    render(<Report markdown={"# Findings\n\n- alpha\n- beta"} sources={[]} />);
    expect(screen.getByRole("heading", { name: "Findings" })).toBeInTheDocument();
    expect(screen.getAllByRole("listitem")).toHaveLength(2);
  });
});

describe("SourcesPanel", () => {
  it("lists numbered sources with domain and snippet", () => {
    render(<SourcesPanel sources={[source(), source({ index: 2, url: "https://arxiv.org/abs/1" })]} />);

    expect(screen.getByRole("heading", { name: /sources \(2\)/i })).toBeInTheDocument();
    expect(screen.getByText("[1]")).toBeInTheDocument();
    expect(screen.getAllByText("nasa.gov").length).toBeGreaterThan(0);
    expect(screen.getByText("arxiv.org")).toBeInTheDocument();
  });

  it("renders nothing when there are no sources", () => {
    const { container } = render(<SourcesPanel sources={[]} />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe("Report against the real report that exposed the bug", () => {
  // End-to-end on the actual document from eval-2026-07-31, not a hand-written sample.
  // Before the fix this rendered 42 of its 84 citation references as inert text.
  const sources: Source[] = [...new Set(EXPECTED_CITED_INDICES)].map((index) =>
    source({
      index,
      title: `Source ${index}`,
      url: `https://example.com/${index}`,
      snippet: `Snippet for source ${index}.`,
    }),
  );

  it("renders every one of the 84 citation references as a resolved chip", () => {
    render(<Report markdown={REAL_REPORT_BODY} sources={sources} />);

    const chips = screen.getAllByRole("button", { name: /^source \d+:/i });
    expect(chips).toHaveLength(EXPECTED_CITED_INDICES.length);
    expect(EXPECTED_CITED_INDICES).toHaveLength(84);
  });

  it("leaves no citation unrendered — nothing falls through as inert text", () => {
    const { container } = render(<Report markdown={REAL_REPORT_BODY} sources={sources} />);

    // Any surviving `[1, 3]`-shaped text means the renderer skipped a citation.
    expect(container.textContent ?? "").not.toMatch(/\[\d+\s*,\s*\d+/);
  });

  it("flags unresolved indices inside groups when sources are missing", () => {
    // Only source 1 exists; every other cited index must show ⚠ rather than vanish.
    render(<Report markdown={REAL_REPORT_BODY} sources={[source({ index: 1 })]} />);

    const warned = screen.getAllByTitle(/does not resolve to a source/i);
    const expectedWarnings = EXPECTED_CITED_INDICES.filter((n) => n !== 1).length;
    expect(warned).toHaveLength(expectedWarnings);
  });
});

describe("multi-snippet sources (docs/12 M5, defect D3)", () => {
  // A source backs ~8 claims per report. Showing only the first extracted snippet meant
  // hovering a citation could surface text unrelated to the sentence it was attached to —
  // breaking the product's central promise.

  it("shows every snippet a source contributed", () => {
    render(
      <Report
        markdown="A claim [1]."
        sources={[
          source({
            snippet: "Postgres won DBMS of the Year five times.",
            snippets: [
              "Postgres won DBMS of the Year five times.",
              "JSONB uses a decomposed binary format with GIN indexing.",
            ],
          }),
        ]}
      />,
    );

    expect(screen.getByText(/dbms of the year/i)).toBeInTheDocument();
    expect(screen.getByText(/decomposed binary format/i)).toBeInTheDocument();
  });

  it("falls back to the single snippet field for sessions stored before it was a list", () => {
    render(
      <Report
        markdown="A claim [1]."
        sources={[source({ snippet: "Only stored snippet.", snippets: undefined })]}
      />,
    );
    expect(screen.getByText(/only stored snippet/i)).toBeInTheDocument();
  });

  it("renders no empty quotation when a source has no snippet at all", () => {
    const { container } = render(
      <Report markdown="A claim [1]." sources={[source({ snippet: "", snippets: [] })]} />,
    );
    expect(container.textContent).not.toMatch(/“”|""/);
  });

  it("lists every snippet in the sources panel too", () => {
    render(
      <SourcesPanel
        sources={[source({ snippet: "First.", snippets: ["First.", "Second."] })]}
      />,
    );
    expect(screen.getByText(/first\./i)).toBeInTheDocument();
    expect(screen.getByText(/second\./i)).toBeInTheDocument();
  });
});
