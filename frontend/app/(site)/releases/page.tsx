import Link from "next/link";

import { pageUrls } from "@/lib/pages-build";
import { RELEASES } from "@/lib/releases";

/**
 * Release history — what changed, and what is still wrong.
 *
 * Every entry carries a "Known gaps" list alongside its improvements, and that pairing is
 * the point. This project's claim is that a false measurement is worse than no
 * measurement; a changelog that only lists wins is the same failure in a different
 * surface. The people reading this page are deciding whether to trust the thing.
 */

export const metadata = {
  // The root layout's `title.template` appends " · Research Assistant" — see app/layout.tsx.
  title: "Releases",
  description:
    "Every release, what improved since the last one, and the known gaps each shipped with.",
  ...pageUrls("/releases"),
};

export default function ReleasesPage() {
  return (
    <main className="mx-auto w-full max-w-3xl px-4 py-12 sm:px-6">
      <header>
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
      </header>

      <ol className="mt-10 space-y-10">
        {RELEASES.map((release) => (
          <li key={release.version} className="border-l-2 border-border pl-5">
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

            <h3 className="mt-5 font-mono text-[0.6875rem] uppercase tracking-widest text-text-muted">
              What improved
            </h3>
            <ul className="mt-2 space-y-2">
              {release.improved.map((item) => (
                <li
                  key={item}
                  className="flex gap-2.5 text-sm leading-relaxed text-text-secondary"
                >
                  <span aria-hidden style={{ color: "var(--success)" }}>
                    +
                  </span>
                  <span>{item}</span>
                </li>
              ))}
            </ul>

            {release.known.length > 0 && (
              <>
                <h3 className="mt-5 font-mono text-[0.6875rem] uppercase tracking-widest text-text-muted">
                  Known gaps in this release
                </h3>
                <ul className="mt-2 space-y-2">
                  {release.known.map((item) => (
                    <li
                      key={item}
                      className="flex gap-2.5 text-sm leading-relaxed text-text-muted"
                    >
                      <span aria-hidden style={{ color: "var(--warning)" }}>
                        !
                      </span>
                      <span>{item}</span>
                    </li>
                  ))}
                </ul>
              </>
            )}

            {!release.unreleased && (
              <Link
                href="/download"
                className="mt-4 inline-flex font-mono text-xs text-accent transition-opacity hover:opacity-80"
              >
                Downloads and checksums for {release.version} →
              </Link>
            )}
          </li>
        ))}
      </ol>
    </main>
  );
}
