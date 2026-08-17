import { describe, expect, it } from "vitest";

import { STATUS_META, STATUS_ORDER, statusMeta } from "./status";
import type { SessionStatus } from "./types";

/**
 * The regression this pins actually happened: Phase 4 added `AWAITING_PLAN` to the badge
 * and not to the history page's filter list, so a session parked at the design gate could
 * be seen but never filtered for — and that is the status a user is most likely to be
 * scanning the list to find.
 */

describe("status vocabulary", () => {
  it("covers every status the app can render, in pipeline order", () => {
    // If a status is added to the union and not here, `STATUS_META` fails to typecheck.
    // This asserts the other direction: the ordered list has not fallen behind the map.
    expect(new Set(STATUS_ORDER)).toEqual(new Set(Object.keys(STATUS_META)));
    expect(STATUS_ORDER).toHaveLength(Object.keys(STATUS_META).length);
  });

  it("gives every status a distinct human label", () => {
    const labels = STATUS_ORDER.map((s) => statusMeta(s).label);
    expect(new Set(labels).size).toBe(labels.length);
  });

  it("marks both human gates as waiting on the user, and nothing else", () => {
    const waiting = STATUS_ORDER.filter((s) => statusMeta(s).needsYou);
    expect(waiting).toEqual(["AWAITING_PLAN", "AWAITING_APPROVAL"]);
  });

  it("falls back rather than throwing on a status from a newer backend", () => {
    // A client can be older than the API it talks to. An unknown status must render
    // *something* neutral, not crash the history page.
    expect(statusMeta("SOMETHING_NEW" as SessionStatus).label).toBe("Queued");
  });
});
