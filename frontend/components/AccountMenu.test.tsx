import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { AccountMenu } from "./AccountMenu";
import { firstNameOf } from "@/lib/user";
import type { User } from "@/lib/types";

vi.mock("next/navigation", () => ({ usePathname: () => "/research", useRouter: () => ({ push: vi.fn(), replace: vi.fn() }) }));
vi.mock("next-themes", () => ({ useTheme: () => ({ resolvedTheme: "light", setTheme: vi.fn() }) }));
vi.mock("@/hooks/queries", () => ({
  useLogout: () => ({ mutate: vi.fn(), isPending: false }),
  // A host WITH accounts, so the menu renders its full set — these tests are about what the
  // chrome must never show (the address), which is the harder case to keep honest.
  useCapabilities: () => ({ accounts: true }),
}));

const EMAIL = "ada.lovelace@analytical-engine.org";

function user(overrides: Partial<User> = {}): User {
  return {
    id: "u1",
    email: EMAIL,
    display_name: "Ada",
    created_at: "2026-01-01T00:00:00Z",
    ...overrides,
  } as User;
}

/**
 * The sidebar is on screen for the whole session — in every screen share, every
 * screenshot, and over every shoulder. An email address is the one identifier in this
 * app that is also a credential somewhere else, and identifying the signed-in account
 * does not need it: the display name and the avatar do that. It belongs on Profile,
 * which the user opens deliberately.
 */
describe("AccountMenu keeps the address out of the chrome", () => {
  it("does not render the email in the resting sidebar row", () => {
    render(<AccountMenu user={user()} />);
    expect(screen.getByText("Ada")).toBeInTheDocument();
    expect(screen.queryByText(EMAIL)).toBeNull();
  });

  it("does not render the email once the menu is opened either", async () => {
    render(<AccountMenu user={user()} />);
    await userEvent.click(screen.getByRole("button", { name: /ada/i }));

    expect(screen.getByRole("menu", { name: "Account" })).toBeInTheDocument();
    expect(screen.queryByText(EMAIL)).toBeNull();
    // Profile is where it lives, so the way to it stays one click from here.
    expect(screen.getByRole("menuitem", { name: /profile/i })).toHaveAttribute(
      "href",
      "/profile",
    );
  });

  it("does not leak the address through a tooltip when collapsed", () => {
    const { container } = render(<AccountMenu user={user()} collapsed />);
    const titles = [...container.querySelectorAll("[title]")].map((n) => n.getAttribute("title"));
    expect(titles.some((t) => t?.includes("@"))).toBe(false);
  });

  it("still names an account that has no display name, without showing the address", () => {
    render(<AccountMenu user={user({ display_name: null })} />);
    // The local part is a derived label, not the address: it cannot be sent to.
    expect(screen.getByText(firstNameOf(user({ display_name: null })))).toBeInTheDocument();
    expect(screen.queryByText(EMAIL)).toBeNull();
  });
});
