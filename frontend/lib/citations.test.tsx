import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Report, SourcesPanel, domainOf } from "./citations";
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
