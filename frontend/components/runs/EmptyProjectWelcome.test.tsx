import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { EmptyProjectWelcome } from "./EmptyProjectWelcome";

describe("EmptyProjectWelcome", () => {
  it("names the project and offers both first steps, neither presented as required first", () => {
    render(<EmptyProjectWelcome projectName="Agent Memory" />);
    expect(
      screen.getByRole("heading", { name: /Agent Memory is ready for its first research/ }),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Start research" })).toHaveAttribute(
      "href",
      "/research",
    );
    expect(screen.getByRole("link", { name: "Add corpus material" })).toHaveAttribute(
      "href",
      "/corpus",
    );
    expect(screen.getByText(/neither has to come first/)).toBeInTheDocument();
  });

  it("does not claim nothing was ever asked, since archived sessions are excluded from the check", () => {
    render(<EmptyProjectWelcome projectName="Agent Memory" />);
    expect(screen.getByText(/no active research or source material/)).toBeInTheDocument();
    expect(screen.queryByText(/Nothing has been asked/)).not.toBeInTheDocument();
  });
});
