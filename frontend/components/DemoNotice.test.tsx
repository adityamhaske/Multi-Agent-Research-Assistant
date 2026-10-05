import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { DemoNotice } from "./DemoNotice";

vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: React.ReactNode }) => (
    <a href={href}>{children}</a>
  ),
}));

/**
 * One notice for runs and sessions, so the two cannot drift into saying different things.
 *
 * It must not send someone to Settings as if that were the whole fix: when the *server* runs in
 * demo mode, every run is a demo and a key saved in Settings is never used.
 */
describe("DemoNotice", () => {
  it("names what did not happen before anything else", () => {
    render(<DemoNotice />);
    const notice = screen.getByRole("note", { name: /demo run/i });
    expect(notice).toHaveTextContent("Demo run — no LLM research was performed");
    expect(notice).toHaveTextContent(
      "Your question was not sent to a model. This report is a scripted demonstration",
    );
  });

  it("says where demo mode comes from when it is the server, not the user", () => {
    render(<DemoNotice />);
    expect(screen.getByRole("note", { name: /demo run/i })).toHaveTextContent(
      /server .* demo mode/i,
    );
    expect(screen.getByRole("link", { name: "Settings" })).toHaveAttribute("href", "/settings");
  });
});
