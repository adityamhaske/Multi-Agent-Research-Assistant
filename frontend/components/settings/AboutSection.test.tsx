import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AboutSection } from "./AboutSection";

/**
 * The update check has four answers, and only one of them is "you are up to date".
 *
 * The backend keeps a check that *ran* apart from one that could not (offline, rate
 * limited, GitHub down) — `app/services/updates.py`. This asserts the UI carries that
 * distinction through to the screen rather than flattening it, because the flattened
 * version is not merely less informative: it tells an offline user they are current, and
 * the consequence is that they never update.
 *
 * Also pinned here: the check runs on the button and not on mount. An app whose pitch is
 * local-first should not reach the network because someone opened a settings page.
 */

const capabilities = vi.hoisted(() => ({ value: { update_check: true } as Record<string, unknown> }));
const version = vi.hoisted(() => ({
  value: {
    version: "2.0.2",
    git_sha: "6adfa16cc73e82a32ffe6d66d38ac08bc6012ed1",
    dirty: false,
    contract_version: "0e26f0c64bd18f18",
    built_at: "2026-08-31T22:05:09+00:00",
  } as Record<string, unknown> | undefined,
}));
const check = vi.hoisted(() => ({
  mutate: vi.fn(),
  data: undefined as unknown,
  isPending: false,
  isError: false,
}));

vi.mock("@/hooks/queries", () => ({
  useCapabilities: () => capabilities.value,
  useVersion: () => ({ data: version.value }),
  useUpdateCheck: () => check,
}));

beforeEach(() => {
  capabilities.value = { update_check: true };
  check.mutate = vi.fn();
  check.data = undefined;
  check.isPending = false;
  check.isError = false;
});

describe("AboutSection", () => {
  it("shows what this build is, so a bug report can name the commit", () => {
    render(<AboutSection />);
    expect(screen.getByText("2.0.2")).toBeInTheDocument();
    // Short SHA — the full 40 characters are unreadable and nobody types them.
    expect(screen.getByText("6adfa16cc")).toBeInTheDocument();
  });

  it("does not check for updates until asked", () => {
    render(<AboutSection />);
    expect(check.mutate).not.toHaveBeenCalled();
  });

  it("checks when the button is pressed", async () => {
    render(<AboutSection />);
    await userEvent.click(screen.getByRole("button", { name: /check for updates/i }));
    expect(check.mutate).toHaveBeenCalledOnce();
  });

  it("reports a newer release with a link to it", () => {
    check.data = {
      state: "update_available",
      running_version: "2.0.2",
      latest_version: "2.0.3",
      release_url: "https://github.com/o/r/releases/tag/v2.0.3",
      detail: "",
    };
    render(<AboutSection />);
    const link = screen.getByRole("link", { name: /2\.0\.3 is available/i });
    expect(link).toHaveAttribute("href", "https://github.com/o/r/releases/tag/v2.0.3");
  });

  it("says you are current when the check actually ran", () => {
    check.data = {
      state: "up_to_date",
      running_version: "2.0.3",
      latest_version: "2.0.3",
      release_url: null,
      detail: "",
    };
    render(<AboutSection />);
    expect(screen.getByText(/on the latest release/i)).toBeInTheDocument();
  });

  it("never claims you are up to date when the check failed", () => {
    check.data = {
      state: "check_failed",
      running_version: "2.0.2",
      latest_version: null,
      release_url: null,
      detail: "Could not reach GitHub: ConnectError.",
    };
    render(<AboutSection />);

    expect(screen.getByText(/could not check for updates/i)).toBeInTheDocument();
    // The reason is shown: a failure a user cannot see the cause of is one they cannot act on.
    expect(screen.getByText(/ConnectError/)).toBeInTheDocument();
    // The assertion this file exists for.
    expect(screen.queryByText(/on the latest release/i)).not.toBeInTheDocument();
  });

  it("says an unstamped build cannot be compared, rather than guessing", () => {
    check.data = {
      state: "unknown_local_version",
      running_version: "unknown",
      latest_version: "2.0.3",
      release_url: "https://github.com/o/r/releases/tag/v2.0.3",
      detail: "This build did not record its own version.",
    };
    render(<AboutSection />);
    expect(screen.getByText(/did not record its version/i)).toBeInTheDocument();
    expect(screen.queryByText(/on the latest release/i)).not.toBeInTheDocument();
  });

  it("hides the check entirely on a host that does not offer it", () => {
    // The server reports `update_check: false` — it is updated by pulling an image. The
    // build facts above still render; only the control that host cannot honour is gone.
    capabilities.value = { update_check: false };
    render(<AboutSection />);
    expect(screen.queryByRole("button", { name: /check for updates/i })).not.toBeInTheDocument();
    expect(screen.getByText("2.0.2")).toBeInTheDocument();
  });
});
