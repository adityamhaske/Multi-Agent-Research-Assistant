import { describe, expect, it } from "vitest";

import {
  RELEASES,
  REPOSITORY_URL,
  latestRelease,
  releaseAnchor,
  releaseTagUrl,
} from "./releases";

/**
 * The shape rules `releases.ts` states in prose, held where a new entry cannot skip them.
 *
 * The page shows each summary *instead of* its list until a reader opens the fold, so a
 * missing summary is a release that looks like it changed nothing, and a missing known-gaps
 * summary is a release that looks like it shipped clean. Neither is a styling problem.
 */

// Three lines of the releases page's text column at its widest; see the summary rule in
// releases.ts. Generous on purpose — the bound catches a pasted list, not a long sentence.
const SUMMARY_LIMIT = 340;

describe("release summaries", () => {
  it.each(RELEASES.map((r) => [r.version, r] as const))(
    "%s summarizes what improved in two or three lines",
    (_, release) => {
      expect(release.improvedSummary.trim()).not.toBe("");
      expect(release.improvedSummary).not.toContain("\n");
      expect(release.improvedSummary.length).toBeLessThanOrEqual(SUMMARY_LIMIT);
    },
  );

  it.each(RELEASES.map((r) => [r.version, r] as const))(
    "%s summarizes its known gaps whenever it has any",
    (_, release) => {
      if (release.known.length === 0) {
        expect(release.knownSummary).toBe("");
        return;
      }
      expect(release.knownSummary.trim()).not.toBe("");
      expect(release.knownSummary).not.toContain("\n");
      expect(release.knownSummary.length).toBeLessThanOrEqual(SUMMARY_LIMIT);
    },
  );

  it.each(RELEASES.map((r) => [r.version, r] as const))(
    "%s keeps each summary shorter than the list it stands in for",
    (_, release) => {
      expect(release.improvedSummary.length).toBeLessThan(release.improved.join(" ").length);
      if (release.known.length > 0) {
        expect(release.knownSummary.length).toBeLessThan(release.known.join(" ").length);
      }
    },
  );
});

describe("versions", () => {
  it("names every version exactly as its git tag", () => {
    for (const release of RELEASES) expect(release.version).toMatch(/^v\d+\.\d+\.\d+$/);
  });

  it("lists releases newest first, which is what latestRelease relies on", () => {
    const dates = RELEASES.map((r) => r.date);
    expect(dates).toEqual([...dates].sort().reverse());
    expect(latestRelease()).toBe(RELEASES.find((r) => !r.unreleased));
  });

  it("gives every version its own anchor", () => {
    const anchors = RELEASES.map((r) => releaseAnchor(r.version));
    expect(new Set(anchors).size).toBe(RELEASES.length);
  });

  it("links a tag to its release on GitHub", () => {
    expect(releaseTagUrl("v3.0.0")).toBe(`${REPOSITORY_URL}/releases/tag/v3.0.0`);
  });
});
