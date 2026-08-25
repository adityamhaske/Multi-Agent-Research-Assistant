import { describe, expect, it } from "vitest";

import { isProjectEmpty } from "./projectEmptiness";

const settled = (count: number) => ({
  isLoading: false,
  isError: false,
  data: { any: "answer" },
  count,
});
const loading = { isLoading: true, isError: false, data: undefined, count: 0 };
const errored = { isLoading: false, isError: true, data: undefined, count: 0 };
/** Offline: React Query pauses the fetch — neither loading nor errored, and no data. */
const paused = { isLoading: false, isError: false, data: undefined, count: 0 };

describe("isProjectEmpty", () => {
  it("is empty only when every source has answered, and answered zero", () => {
    expect(isProjectEmpty([settled(0), settled(0), settled(0)])).toBe(true);
  });

  it("is not empty when any source reports something", () => {
    expect(isProjectEmpty([settled(0), settled(2), settled(0)])).toBe(false);
  });

  it("is not empty while a source is still loading — an unread source is not a zero", () => {
    expect(isProjectEmpty([settled(0), loading, settled(0)])).toBe(false);
  });

  it("is not empty when a source failed — a failed read measured nothing", () => {
    expect(isProjectEmpty([settled(0), errored, settled(0)])).toBe(false);
  });

  it("is not empty when a source is paused offline, which reports neither loading nor error", () => {
    // The state that a `!isLoading && !isError` check would wrongly score as settled: an
    // offline reader with a real project must not be shown the first-run welcome.
    expect(isProjectEmpty([paused, paused, paused])).toBe(false);
  });

  it("does not treat a failed read as empty even when every other source is genuinely zero", () => {
    // The trap this function exists to prevent: three zeroes and one unknown is not four
    // zeroes, and must never greet a returning user with a first-run welcome.
    expect(isProjectEmpty([settled(0), settled(0), errored])).toBe(false);
  });
});
