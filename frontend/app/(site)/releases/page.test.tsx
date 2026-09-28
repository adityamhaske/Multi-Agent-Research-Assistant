import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { RELEASES, REPOSITORY_URL, releaseAnchor, releaseTagUrl } from "@/lib/releases";

import ReleasesPage from "./page";

/**
 * The releases page: a version index that reaches every entry, summaries that stand in for
 * folded lists, and the ways out to GitHub.
 *
 * Checked against the real release history rather than a fixture, so an entry added
 * without a summary — or a list that stops being reachable behind its fold — fails here
 * rather than shipping as a release that appears to have changed nothing.
 */

function entry(version: string): HTMLElement {
  const el = document.getElementById(releaseAnchor(version));
  if (!el) throw new Error(`no entry for ${version}`);
  return el;
}

describe("ReleasesPage", () => {
  afterEach(() => {
    window.location.hash = "";
  });

  it("indexes every version, and every index link lands on its entry", () => {
    render(<ReleasesPage />);
    const nav = screen.getByRole("navigation", { name: "Versions" });
    const links = within(nav).getAllByRole("link");

    expect(links).toHaveLength(RELEASES.length);
    RELEASES.forEach((release, i) => {
      expect(links[i]).toHaveTextContent(release.version);
      expect(links[i]).toHaveAttribute("href", `#${releaseAnchor(release.version)}`);
      expect(entry(release.version)).toBeInTheDocument();
    });
  });

  it("marks the newest tagged release as the latest in the index, and nothing else", () => {
    render(<ReleasesPage />);
    const nav = screen.getByRole("navigation", { name: "Versions" });
    const marked = within(nav)
      .getAllByRole("link")
      .filter((a) => /latest/i.test(a.textContent ?? ""));
    expect(marked).toHaveLength(1);
    expect(marked[0]).toHaveTextContent(RELEASES.find((r) => !r.unreleased)!.version);
  });

  it("offers every version in the narrow-screen dropdown, and choosing one jumps to it", () => {
    render(<ReleasesPage />);
    const select = screen.getByLabelText(/jump to version/i) as HTMLSelectElement;
    const values = Array.from(select.options).map((o) => o.value);
    expect(values).toEqual(RELEASES.map((r) => releaseAnchor(r.version)));
    for (const value of values) expect(document.getElementById(value)).toBeInTheDocument();

    const target = RELEASES[RELEASES.length - 1].version;
    fireEvent.change(select, { target: { value: releaseAnchor(target) } });
    expect(window.location.hash).toBe(`#${releaseAnchor(target)}`);
  });

  it("offers the repository before the first version", () => {
    render(<ReleasesPage />);
    const button = screen.getByRole("link", { name: /view on github/i });
    expect(button).toHaveAttribute("href", REPOSITORY_URL);
    // Before, in document order — not somewhere in the footer.
    const first = entry(RELEASES[0].version);
    expect(button.compareDocumentPosition(first) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it.each(RELEASES.map((r) => [r.version, r] as const))(
    "%s shows both summaries and folds every item beneath them",
    (_, release) => {
      render(<ReleasesPage />);
      const el = entry(release.version);
      expect(within(el).getByText(release.improvedSummary)).toBeInTheDocument();

      const folds = el.querySelectorAll("details");
      expect(folds).toHaveLength(release.known.length > 0 ? 2 : 1);
      // Closed by default: the summary is what a reader meets first.
      folds.forEach((fold) => expect(fold).not.toHaveAttribute("open"));

      const [improved, known] = Array.from(folds);
      for (const item of release.improved) {
        expect(within(improved).getByText(item)).toBeInTheDocument();
      }
      if (release.known.length > 0) {
        expect(within(el).getByText(release.knownSummary)).toBeInTheDocument();
        for (const item of release.known) {
          expect(within(known).getByText(item)).toBeInTheDocument();
        }
      }
    },
  );

  it("links every tagged version to its release on GitHub", () => {
    render(<ReleasesPage />);
    for (const release of RELEASES.filter((r) => !r.unreleased)) {
      const link = within(entry(release.version)).getByRole("link", {
        name: new RegExp(`${release.version.replace(/\./g, "\\.")} on github`, "i"),
      });
      expect(link).toHaveAttribute("href", releaseTagUrl(release.version));
    }
  });
});
