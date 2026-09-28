import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import DownloadPage from "./page";

/**
 * An entry marked `unreleased` is never offered for download (the two-stage release).
 *
 * A release entry merges to `main` — and Pages deploys it — before its tag exists, and the
 * installers only exist once the tag's workflows publish them. Offering the new version in
 * that window would send every visitor to an asset that 404s, which reads as a broken
 * product rather than a stale link. So the entry lands `unreleased`, and only the follow-up
 * that clears the flag, after the installers are verified, makes it downloadable.
 *
 * The other download tests derive "latest" with the same filter the page uses, so they would
 * agree with a page that stopped filtering. This one plants an unreleased version on top of
 * the real history and looks for it anywhere on the page.
 */

// Hoisted, because `vi.mock` below is hoisted above every ordinary declaration.
const PENDING = vi.hoisted(() => "9.9.9");

vi.mock("@/lib/releases", async (original) => {
  const real = await original<typeof import("@/lib/releases")>();
  const RELEASES = [
    {
      version: `v${PENDING}`,
      date: "2099-01-01",
      headline: "Merged, not yet tagged.",
      improved: [],
      known: [],
      unreleased: true,
    },
    ...real.RELEASES,
  ];
  return { ...real, RELEASES, latestRelease: () => RELEASES.find((r) => !r.unreleased) ?? null };
});

describe("an unreleased version on the download page", () => {
  it("is not in the version selector", () => {
    render(<DownloadPage />);
    const select = screen.getByLabelText(/version/i) as HTMLSelectElement;
    const offered = Array.from(select.options).map((o) => o.value);
    expect(offered).not.toContain(PENDING);
    expect(select.value).not.toBe(PENDING);
  });

  it("has no link to its assets or its source archive", () => {
    render(<DownloadPage />);
    const hrefs = screen.getAllByRole("link").map((a) => a.getAttribute("href") ?? "");
    expect(hrefs.filter((h) => h.includes(PENDING))).toEqual([]);
  });
});
