import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import DownloadPage from "./page";

/**
 * A release published for macOS only (from v3.1.0) never gets a Windows or Linux button that
 * would 404. Those cards offer the newest build their platform has and say why.
 */

const MAC_ONLY = vi.hoisted(() => "9.9.9");

vi.mock("@/lib/releases", async (original) => {
  const real = await original<typeof import("@/lib/releases")>();
  const RELEASES: import("@/lib/releases").Release[] = [
    {
      version: `v${MAC_ONLY}`,
      date: "2099-01-01",
      headline: "macOS only.",
      improved: [],
      improvedSummary: "",
      known: [],
      knownSummary: "",
      platforms: ["macos"],
    },
    ...real.RELEASES,
  ];
  return { ...real, RELEASES, latestRelease: () => RELEASES.find((r) => !r.unreleased) ?? null };
});

describe("a macOS-only release on the download page", () => {
  it("links the .dmg at that version and no other installer of it", () => {
    render(<DownloadPage />);
    const hrefs = screen.getAllByRole("link").map((a) => a.getAttribute("href") ?? "");
    const ofIt = hrefs.filter((h) => h.includes(`/v${MAC_ONLY}/`));
    expect(ofIt).toEqual([
      expect.stringMatching(new RegExp(`Research\\.Assistant_${MAC_ONLY}_aarch64\\.dmg$`)),
    ]);
  });

  it("offers Windows and Linux their newest build, and says why", () => {
    render(<DownloadPage />);
    const hrefs = screen.getAllByRole("link").map((a) => a.getAttribute("href") ?? "");
    expect(hrefs.some((h) => h.endsWith(".msi") && !h.includes(MAC_ONLY))).toBe(true);
    expect(hrefs.some((h) => h.endsWith(".AppImage") && !h.includes(MAC_ONLY))).toBe(true);
    expect(screen.getAllByText(new RegExp(`v${MAC_ONLY} was published for macOS only`))).toHaveLength(2);
  });
});
