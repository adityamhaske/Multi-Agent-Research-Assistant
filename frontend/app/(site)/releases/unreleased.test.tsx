import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import ReleasesPage from "./page";

/**
 * An entry merged to `main` before its tag exists (the two-stage release — see the download
 * page's `unreleased.test.tsx`) must not link to a tag or installers that do not exist yet,
 * and must say it is untagged wherever it is listed, the index included.
 */

const PENDING = vi.hoisted(() => "v9.9.9");

vi.mock("@/lib/releases", async (original) => {
  const real = await original<typeof import("@/lib/releases")>();
  const RELEASES = [
    {
      version: PENDING,
      date: "2099-01-01",
      headline: "Merged to main ahead of its tag.",
      improved: ["Something merged to main."],
      improvedSummary: "Something merged.",
      known: [],
      knownSummary: "",
      unreleased: true,
    },
    ...real.RELEASES,
  ];
  return { ...real, RELEASES, latestRelease: () => RELEASES.find((r) => !r.unreleased) ?? null };
});

describe("an unreleased version on the releases page", () => {
  it("links to neither GitHub nor the download page", () => {
    render(<ReleasesPage />);
    const el = document.getElementById(PENDING)!;
    expect(within(el).queryAllByRole("link")).toEqual([]);
    expect(within(el).getByText(/not yet tagged/i)).toBeInTheDocument();
  });

  it("is listed as untagged in the index, and is not the latest", () => {
    render(<ReleasesPage />);
    const nav = screen.getByRole("navigation", { name: "Versions" });
    const link = within(nav)
      .getAllByRole("link")
      .find((a) => a.getAttribute("href") === `#${PENDING}`);
    if (!link) throw new Error(`no index link for ${PENDING}`);
    expect(link).toHaveTextContent(/not yet tagged/i);
    expect(link).not.toHaveTextContent(/latest/i);
  });
});
