import Link from "next/link";

import { IconGitHub } from "@/components/icons";
import { ReleaseNav } from "@/components/site/ReleaseNav";
import { pageUrls } from "@/lib/pages-build";
import {
  REPOSITORY_URL,
  RELEASES,
  latestRelease,
  releaseAnchor,
  releaseTagUrl,
} from "@/lib/releases";

/**
 * Release history — what changed, and what is still wrong.
 *
 * Every entry carries a "Known gaps" list alongside its improvements, and that pairing is
 * the point. This project's claim is that a false measurement is worse than no
 * measurement; a changelog that only lists wins is the same failure in a different
 * surface. The people reading this page are deciding whether to trust the thing.
 *
 * Each list opens as its two- or three-line summary, with the full list one click below.
 * The fold is a native `<details>`, not a stateful toggle: it works before hydration and
 * with scripts off, and the browser's find-in-page opens it on a match — a gap a reader
 * searches for is never hidden from the search. The two summaries sit side by side in
 * weight, so folding the lists cannot quietly promote the good news over the bad.
 */

export const metadata = {
  // The root layout's `title.template` appends " · Research Assistant" — see app/layout.tsx.
  title: "Releases",
  description:
    "Every release, what improved since the last one, and the known gaps each shipped with.",
  ...pageUrls("/releases"),
};

// "All 1 known gap" reads as a mistake; a lone item is simply read in full.
function foldLabel(n: number, noun: string): string {
  return n === 1 ? "Read in full" : `All ${n} ${noun}s`;
}

/** A summary, then the full list folded beneath it. */
function FoldedList({
  heading,
  summary,
  items,
  noun,
  marker,
  markerColor,
  itemClassName,
}: {
  heading: string;
  summary: string;
  items: string[];
  noun: string;
  marker: string;
  markerColor: string;
  itemClassName: string;
}) {
  return (
    <section className="mt-5">
      <h3 className="font-mono text-[0.6875rem] uppercase tracking-widest text-text-muted">
        {heading}
      </h3>
      <p className="mt-2 text-sm leading-relaxed text-text-secondary">{summary}</p>
      <details className="group mt-2">
        <summary className="inline-flex cursor-pointer list-none items-center gap-1.5 font-mono text-xs text-text-muted transition-colors hover:text-text-primary [&::-webkit-details-marker]:hidden">
          <span aria-hidden className="inline-block w-2 text-center group-open:hidden">
            ▸
          </span>
          <span aria-hidden className="hidden w-2 text-center group-open:inline-block">
            ▾
          </span>
          {foldLabel(items.length, noun)}
        </summary>
        <ul className="mt-3 space-y-2 border-l border-border pl-4">
          {items.map((item) => (
            <li key={item} className={`flex gap-2.5 text-sm leading-relaxed ${itemClassName}`}>
              <span aria-hidden style={{ color: markerColor }}>
                {marker}
              </span>
              <span>{item}</span>
            </li>
          ))}
        </ul>
      </details>
    </section>
  );
}

export default function ReleasesPage() {
  const latest = latestRelease();
  const navItems = RELEASES.map((release) => ({
    id: releaseAnchor(release.version),
    version: release.version,
    label: release.unreleased ? "not yet tagged" : release.date,
    latest: release === latest,
  }));

  return (
    <main className="mx-auto w-full max-w-3xl px-4 py-12 sm:px-6 lg:grid lg:max-w-5xl lg:grid-cols-[minmax(0,1fr)_11rem] lg:gap-x-12">
      <header className="lg:col-start-1">
        <p className="font-mono text-[0.6875rem] uppercase tracking-widest text-text-muted">
          Changelog
        </p>
        <h1 className="mt-3 font-serif text-3xl font-bold tracking-tight text-text-primary sm:text-4xl">
          Releases
        </h1>
        <p className="mt-4 text-base leading-relaxed text-text-secondary">
          What improved in each release, and what it shipped with still broken.
          Every version is tagged in git and its installers are available on the{" "}
          <Link href="/download" className="text-accent hover:opacity-80">
            Download page
          </Link>{" "}
          with checksums.
        </p>
        {/* External, so an <a> rather than <Link>: it leaves the site. Styled as the
            site's secondary button — the same weight as "Source →" in the header, so it
            is findable without competing with the entries below it. */}
        <a
          href={REPOSITORY_URL}
          className="mt-6 inline-flex h-9 items-center gap-2 border border-border bg-bg-surface px-3 font-mono text-xs text-text-secondary transition-colors hover:bg-bg-elevated hover:text-text-primary"
        >
          <IconGitHub className="h-3.5 w-3.5" />
          View on GitHub
        </a>
      </header>

      {/* After the header in the DOM, so a narrow screen and a screen reader meet the
          index between the introduction and the first entry; the grid lifts it into the
          right-hand column from `lg` up, where it sticks below the site header. */}
      <aside className="mt-8 lg:col-start-2 lg:row-span-2 lg:row-start-1 lg:mt-0">
        <div className="lg:sticky lg:top-[4.5rem] lg:max-h-[calc(100vh-6rem)] lg:overflow-y-auto">
          <ReleaseNav items={navItems} />
        </div>
      </aside>

      <ol className="mt-10 space-y-10 lg:col-start-1">
        {RELEASES.map((release) => (
          <li
            key={release.version}
            id={releaseAnchor(release.version)}
            className="scroll-mt-20 border-l-2 border-border pl-5"
          >
            <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
              <h2 className="font-serif text-2xl font-bold tracking-tight text-text-primary">
                {release.version}
              </h2>
              {release.unreleased ? (
                <span
                  className="border px-1.5 py-0.5 font-mono text-[0.625rem] uppercase tracking-widest"
                  style={{
                    color: "var(--warning)",
                    borderColor: "var(--warning)",
                  }}
                >
                  on main, not yet tagged
                </span>
              ) : (
                <time
                  className="font-mono text-xs text-text-muted"
                  dateTime={release.date}
                >
                  {release.date}
                </time>
              )}
            </div>

            <p className="mt-2 text-sm leading-relaxed text-text-secondary">
              {release.headline}
            </p>

            <FoldedList
              heading="What improved"
              summary={release.improvedSummary}
              items={release.improved}
              noun="improvement"
              marker="+"
              markerColor="var(--success)"
              itemClassName="text-text-secondary"
            />

            {release.known.length > 0 && (
              <FoldedList
                heading="Known gaps in this release"
                summary={release.knownSummary}
                items={release.known}
                noun="known gap"
                marker="!"
                markerColor="var(--warning)"
                itemClassName="text-text-muted"
              />
            )}

            {/* No tag, no links: an unreleased entry has neither installers nor a GitHub
                release yet, and a link to either would 404. */}
            {!release.unreleased && (
              <div className="mt-4 flex flex-wrap gap-x-5 gap-y-1">
                <Link
                  href="/download"
                  className="inline-flex font-mono text-xs text-accent transition-opacity hover:opacity-80"
                >
                  Downloads and checksums for {release.version} →
                </Link>
                <a
                  href={releaseTagUrl(release.version)}
                  className="inline-flex font-mono text-xs text-text-muted transition-colors hover:text-text-primary"
                >
                  {release.version} on GitHub ↗
                </a>
              </div>
            )}
          </li>
        ))}
      </ol>
    </main>
  );
}
