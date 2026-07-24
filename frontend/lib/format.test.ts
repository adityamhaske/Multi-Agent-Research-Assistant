import { describe, expect, it } from "vitest";

import { formatCost, formatDuration, formatNumber, relativeTime } from "./format";

describe("formatCost", () => {
  it("shows sub-cent costs at 4dp so cheap runs aren't rendered as free", () => {
    expect(formatCost(0.0034)).toBe("$0.0034");
  });

  it("shows normal costs at 2dp", () => {
    expect(formatCost(1.239)).toBe("$1.24");
  });

  it("handles zero and missing values", () => {
    expect(formatCost(0)).toBe("$0.00");
    expect(formatCost(null)).toBe("$0.00");
    expect(formatCost(undefined)).toBe("$0.00");
  });
});

describe("formatDuration", () => {
  it("renders seconds under a minute", () => {
    expect(formatDuration(42.34)).toBe("42.3s");
  });

  it("renders minutes and seconds past a minute", () => {
    expect(formatDuration(135)).toBe("2m 15s");
  });

  it("renders an em dash when unknown", () => {
    expect(formatDuration(null)).toBe("—");
    expect(formatDuration(undefined)).toBe("—");
  });
});

describe("formatNumber", () => {
  it("groups thousands", () => {
    expect(formatNumber(1234567)).toBe("1,234,567");
  });

  it("treats nullish as zero", () => {
    expect(formatNumber(null)).toBe("0");
  });
});

describe("relativeTime", () => {
  const now = Date.parse("2026-07-23T12:00:00Z");

  it("labels the last minute as just now", () => {
    expect(relativeTime("2026-07-23T11:59:30Z", now)).toBe("just now");
  });

  it("renders minutes, hours and days", () => {
    expect(relativeTime("2026-07-23T11:30:00Z", now)).toBe("30m ago");
    expect(relativeTime("2026-07-23T09:00:00Z", now)).toBe("3h ago");
    expect(relativeTime("2026-07-20T12:00:00Z", now)).toBe("3d ago");
  });

  it("never renders a negative age for clock skew", () => {
    expect(relativeTime("2026-07-23T12:00:30Z", now)).toBe("just now");
  });

  it("passes through an unparseable value", () => {
    expect(relativeTime("nonsense", now)).toBe("nonsense");
  });
});
