import { describe, expect, it } from "vitest";

import { V2_STATUS_META, RUN_STATUS_ORDER, runStatusMeta } from "./runStatus";
import type { RunStatus } from "./types";

/**
 * One vocabulary for a run's status, used by the badge, the header sentence, the History
 * filters and the run card.
 *
 * The session equivalent drifted exactly once — `AWAITING_PLAN` was added to the badge and not
 * to the filter list, so the run a user was most likely scanning for could be seen and not
 * filtered for. `Record<RunStatus, …>` makes the type checker catch the first half of
 * that; these tests catch the second.
 */

const ALL: RunStatus[] = [
  "PENDING",
  "RUNNING",
  "AWAITING_PLAN",
  "AWAITING_REVIEW",
  "COMPLETED",
  "FAILED",
  "CANCELLED",
];

describe("Run status vocabulary", () => {
  it("covers every status the backend can report, in the order given", () => {
    expect([...RUN_STATUS_ORDER].sort()).toEqual([...ALL].sort());
  });

  it("gives every status both a badge label and a full sentence", () => {
    for (const status of ALL) {
      expect(V2_STATUS_META[status].label).toMatch(/\S/);
      expect(V2_STATUS_META[status].sentence).toMatch(/\S/);
    }
  });

  it("marks exactly the two gates as waiting on a person", () => {
    const needsYou = ALL.filter((s) => V2_STATUS_META[s].needsYou);
    expect(needsYou.sort()).toEqual(["AWAITING_PLAN", "AWAITING_REVIEW"]);
  });

  it("marks exactly the two statuses where the server still has something to say", () => {
    const live = ALL.filter((s) => V2_STATUS_META[s].live);
    expect(live.sort()).toEqual(["PENDING", "RUNNING"]);
  });

  it("never claims a cancelled or failed run produced an artifact", () => {
    expect(V2_STATUS_META.CANCELLED.sentence).not.toMatch(/artifact/i);
    expect(V2_STATUS_META.FAILED.sentence).not.toMatch(/artifact/i);
    expect(V2_STATUS_META.COMPLETED.sentence).toMatch(/artifact/i);
  });

  it("survives a status it has not been taught, without inventing one", () => {
    const meta = runStatusMeta("SOMETHING_NEW");
    expect(meta.label).toBe("something new");
    expect(meta.sentence).toMatch(/does not recognise/);
    // The important half: it must not silently map onto a status the run is not in.
    expect(meta.label).not.toBe(V2_STATUS_META.COMPLETED.label);
    expect(meta.needsYou).toBeUndefined();
  });
});
