import { describe, expect, it } from "vitest";

import { firstNameOf } from "./user";

/**
 * The label that stands in for an account anywhere the address must not appear.
 */
describe("firstNameOf", () => {
  it("uses the first word of a display name", () => {
    expect(firstNameOf({ display_name: "Ada Lovelace", email: "ada@x.org" })).toBe("Ada");
  });

  it("falls back to the local part, never the whole address", () => {
    const label = firstNameOf({ display_name: null, email: "ada.lovelace@analytical.org" });
    expect(label).toBe("Ada.lovelace");
    expect(label).not.toContain("@");
    expect(label).not.toContain("analytical.org");
  });

  it("does not fall over on an account with neither", () => {
    expect(firstNameOf({ display_name: null, email: "" })).toBe("");
  });
});
