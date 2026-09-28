import { describe, expect, it } from "vitest";

import { activeSection } from "./activeSection";

const VIEWPORT = 800;
const LINE = 120;

function pick(tops: number[], opts: { atBottom?: boolean; targetIndex?: number } = {}) {
  return activeSection({
    tops,
    readingLine: LINE,
    viewportHeight: VIEWPORT,
    atBottom: opts.atBottom ?? false,
    targetIndex: opts.targetIndex ?? -1,
  });
}

describe("activeSection", () => {
  it("marks the first section before any has reached the reading line", () => {
    expect(pick([300, 900, 1500])).toBe(0);
  });

  it("marks the last section whose top has scrolled past the reading line", () => {
    expect(pick([-900, -200, 110, 700])).toBe(2);
  });

  it("counts a section sitting exactly on the line as being read", () => {
    expect(pick([-400, LINE, 600])).toBe(1);
  });

  it("marks a section the reader jumped to even when the page ran out of scroll first", () => {
    // The foot of the page: sections 2 and 3 are on screen but can never reach the line.
    expect(pick([-700, -100, 300, 550], { atBottom: true, targetIndex: 2 })).toBe(2);
  });

  it("marks the last section at the foot of the page when no chosen one is on screen", () => {
    expect(pick([-700, -100, 300, 550], { atBottom: true })).toBe(3);
    expect(pick([-1700, -900, 300, 550], { atBottom: true, targetIndex: 0 })).toBe(3);
  });

  it("marks nothing when there is nothing to mark", () => {
    expect(pick([])).toBe(-1);
  });
});
