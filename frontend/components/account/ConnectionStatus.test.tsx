import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ConnectionStatus } from "./ConnectionStatus";

/**
 * `verdict === null` used to mean "render nothing at all", which hid the retest
 * trigger along with the status it drives — a key saved in an earlier page load
 * (no local mutation result, and the health query starts disabled) had no verdict
 * and therefore no way to ever be checked again short of replacing the key. These
 * pin the fix: the trigger must survive the no-verdict state whenever a caller
 * supplies one, and stay silent only when there is truly nothing to offer.
 */

describe("ConnectionStatus with no verdict yet", () => {
  it("renders nothing when there is no retest handler either", () => {
    const { container } = render(<ConnectionStatus verdict={null} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("still offers a way to test the connection", () => {
    render(<ConnectionStatus verdict={null} onRetest={vi.fn()} />);
    expect(screen.getByRole("button", { name: "Test connection" })).toBeInTheDocument();
  });

  it("triggers the retest callback on click, with no status line to show yet", async () => {
    const onRetest = vi.fn();
    render(<ConnectionStatus verdict={null} onRetest={onRetest} />);
    await userEvent.click(screen.getByRole("button", { name: "Test connection" }));
    expect(onRetest).toHaveBeenCalledTimes(1);
  });

  it("disables the trigger and says so while a retest is already in flight", () => {
    render(<ConnectionStatus verdict={null} onRetest={vi.fn()} retesting />);
    const button = screen.getByRole("button", { name: "Testing…" });
    expect(button).toBeDisabled();
  });

  it("shows a checking indicator instead, while the very first probe loads", () => {
    render(<ConnectionStatus verdict={null} onRetest={vi.fn()} loading />);
    expect(screen.getByText("Checking…")).toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });
});

describe("ConnectionStatus with a verdict", () => {
  const verdict = {
    state: "degraded" as const,
    reason: "The server answered but rejected the key.",
    checked_at: "2026-08-25T00:00:00Z",
    model_count: null,
  };

  it("shows the state, the verbatim reason, and still offers a retest", () => {
    render(<ConnectionStatus verdict={verdict} onRetest={vi.fn()} />);
    expect(screen.getByText("Reachable, not confirmed")).toBeInTheDocument();
    expect(screen.getByText(verdict.reason)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Test connection" })).toBeInTheDocument();
  });

  it("appends the model count only in the ok state", () => {
    render(<ConnectionStatus verdict={{ ...verdict, state: "ok", model_count: 47 }} />);
    expect(screen.getByText("· 47 models")).toBeInTheDocument();
  });
});
