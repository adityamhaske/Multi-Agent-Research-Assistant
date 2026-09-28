import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { SessionDetail } from "@/lib/types";

import { StatusBar } from "./StatusBar";

/**
 * The session status bar is not a description list, and must not use its parts.
 *
 * An audit listed it with the run page as having `dt`/`dd` outside a `dl`. It does not: its
 * own `Stat` is built from `div` and `span`, unlike the run workspace's `Stat` primitive,
 * which renders a `dt`/`dd` pair for callers that wrap it in a `dl`. This pins that, so a
 * later swap to the primitive cannot bring the invalid structure in unnoticed.
 */

const session = {
  created_at: "2026-09-27T00:00:00Z",
  elapsed_seconds: 12,
  total_cost_usd: 0.01,
} as unknown as SessionDetail;

describe("StatusBar", () => {
  it("shows its three figures", () => {
    render(<StatusBar session={session} events={[]} running={false} />);
    for (const label of ["Elapsed", "Cost", "Tasks"]) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
  });

  it("has no term or description outside a dl", () => {
    const { container } = render(<StatusBar session={session} events={[]} running={false} />);
    for (const el of container.querySelectorAll("dt, dd")) {
      expect(el.closest("dl")).not.toBeNull();
    }
  });
});
