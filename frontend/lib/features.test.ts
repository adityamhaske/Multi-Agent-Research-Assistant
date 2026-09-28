import { describe, expect, it } from "vitest";

import { getDoc } from "./docs";
import { FEATURES, isNew } from "./features";
import { RELEASES, latestRelease } from "./releases";

describe("landing-page features", () => {
  it("names only releases that exist", () => {
    const versions = new Set(RELEASES.map((r) => r.version));
    for (const f of FEATURES.filter((f) => f.since)) expect(versions).toContain(f.since);
  });

  it("marks a feature new only while its release is the one being offered", () => {
    const latest = latestRelease()!.version;
    for (const f of FEATURES) expect(isNew(f)).toBe(f.since === latest);
  });

  it("links every card to a page that exists", () => {
    for (const f of FEATURES) {
      expect(f.href.startsWith("/")).toBe(true);
      if (f.href.startsWith("/docs/")) {
        // A docs slug that no document answers to is a 404 on the Pages export.
        expect(getDoc(f.href.slice("/docs/".length).split("#")[0]), f.href).not.toBeNull();
      }
    }
  });
});
