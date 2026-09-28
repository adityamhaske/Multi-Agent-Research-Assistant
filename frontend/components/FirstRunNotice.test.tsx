import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { FirstRunNotice } from "./FirstRunNotice";

/**
 * The notice offers only a keyless path the build really has.
 *
 * It used to say "tick Demo run under Options". There is no such control: the only
 * "Demo run" in the interface is the badge on a run that already used scripted models. A
 * self-hosted stack's keyless path is `./start.sh --fake`; the desktop app has none, so
 * there the notice offers no alternative at all.
 */

const readiness = vi.hoisted(() => ({ value: { ready: false, local_reachable: false } as object }));
const host = vi.hoisted(() => ({ desktop: false }));

vi.mock("@/hooks/queries", () => ({ useReadiness: () => ({ data: readiness.value }) }));
vi.mock("@/lib/desktop", () => ({
  get isDesktop() {
    return host.desktop;
  },
}));

beforeEach(() => {
  readiness.value = { ready: false, local_reachable: false };
  host.desktop = false;
});

describe("the keyless path the notice offers", () => {
  it("names the real demo command on a self-hosted stack", () => {
    render(<FirstRunNotice />);
    expect(screen.getByText("./start.sh --fake")).toBeInTheDocument();
    expect(screen.getByRole("note")).toHaveTextContent(/stamped as a demo/);
  });

  it("never points at a Demo run control under Options, which does not exist", () => {
    render(<FirstRunNotice />);
    expect(screen.getByRole("note")).not.toHaveTextContent(/Demo run/);
    expect(screen.getByRole("note")).not.toHaveTextContent(/under Options/);
  });

  it("offers no keyless path on the desktop, which has none", () => {
    host.desktop = true;
    render(<FirstRunNotice />);
    expect(screen.getByRole("note")).not.toHaveTextContent(/start\.sh/);
    expect(screen.getByRole("note")).not.toHaveTextContent(/Demo run/);
    expect(screen.getByRole("link", { name: "Connect a model" })).toHaveAttribute(
      "href",
      "/settings",
    );
  });

  it("is not shown once a model can be reached", () => {
    readiness.value = { ready: true, local_reachable: false };
    const { container } = render(<FirstRunNotice />);
    expect(container).toBeEmptyDOMElement();
  });
});
