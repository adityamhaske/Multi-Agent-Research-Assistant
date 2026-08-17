import { describe, expect, it } from "vitest";

import { AUDIENCES, COMPETITORS, LOSSES, MECHANISMS, ROWS } from "./comparison";

/**
 * These do not test rendering — they test that the comparison stays *honest* as it is
 * edited.
 *
 * A competitive table is the easiest place in a codebase to quietly start lying: a row
 * gets reworded, a `no` becomes a `yes`, the losses section gets trimmed, and nothing
 * fails. That matters more here than in most products, because the whole claim is "a
 * false measurement is worse than no measurement" — a self-serving comparison page would
 * undercut the thesis it exists to argue.
 *
 * So the assertions are about shape and candour, not about specific marketing copy.
 */

describe("comparison data", () => {
  it("gives every row a verdict for every competitor", () => {
    // A missing key renders as an empty cell, which reads as "no" without saying it.
    for (const row of ROWS) {
      for (const c of COMPETITORS) {
        expect(row[c.key], `${row.dimension} → ${c.label}`).toBeDefined();
      }
    }
  });

  it("admits rows this product loses", () => {
    const lost = ROWS.filter((r) => r.ours === "no");
    expect(
      lost.length,
      "a table where we win every row is marketing, not a comparison",
    ).toBeGreaterThanOrEqual(3);
  });

  it("credits competitors with rows they win outright", () => {
    const competitorWins = ROWS.filter(
      (r) => r.ours !== "yes" && COMPETITORS.some((c) => r[c.key] === "yes"),
    );
    expect(competitorWins.length).toBeGreaterThanOrEqual(3);
  });

  it("keeps a substantive losses section", () => {
    expect(LOSSES.length).toBeGreaterThanOrEqual(4);
    // The interim citation-support number is the most load-bearing admission on the page:
    // it is the product's own headline metric, and it is not 100%.
    expect(LOSSES.join(" ")).toMatch(/90%/);
  });

  it("sends some readers elsewhere", () => {
    const elsewhere = AUDIENCES.filter((a) => a.elsewhere);
    expect(
      elsewhere.length,
      "an audience list with no 'use something else' is a funnel, not advice",
    ).toBeGreaterThanOrEqual(3);
    expect(elsewhere.some((a) => /notebooklm/i.test(a.verdict))).toBe(true);
  });

  it("points every mechanism at a checkable source", () => {
    // The claims are strong; each one names the file that implements it so a sceptical
    // reader can go and look rather than take the page's word for it.
    for (const m of MECHANISMS) {
      expect(m.source, m.claim).toMatch(/\.(py|ts|tsx)$/);
    }
  });
});
