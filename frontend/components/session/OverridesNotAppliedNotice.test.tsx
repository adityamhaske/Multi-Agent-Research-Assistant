import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { OverridesNotAppliedNotice } from "./OverridesNotAppliedNotice";

/**
 * Scope freeze §8: a session that ignored configured prompt overrides must say so. The flag
 * is on the session row and in the API; this is what makes it reach the reader.
 */
describe("OverridesNotAppliedNotice", () => {
  it("tells the reader the session ran on the shipped prompts", () => {
    render(<OverridesNotAppliedNotice notApplied />);
    const note = screen.getByRole("note");
    expect(note).toHaveTextContent("Custom instructions not applied");
    expect(note).toHaveTextContent(/written with the shipped prompts/);
    expect(screen.getByRole("link", { name: "Settings → Agents" })).toHaveAttribute(
      "href",
      "/settings/agents",
    );
  });

  it("says nothing for a session that ignored nothing", () => {
    const { container } = render(<OverridesNotAppliedNotice notApplied={false} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("says nothing for a session recorded before the flag existed", () => {
    const { container } = render(<OverridesNotAppliedNotice notApplied={undefined} />);
    expect(container).toBeEmptyDOMElement();
  });
});
