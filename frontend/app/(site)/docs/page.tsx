import Link from "next/link";

import { docCategories } from "@/lib/docs";
import { pageUrls } from "@/lib/pages-build";

export const metadata = {
  // The root layout's `title.template` appends " · Research Assistant" — see app/layout.tsx.
  title: "Documentation",
  description:
    "Documentation for the Multi-Agent Research Assistant: getting started, the user " +
    "guide, architecture, deployment, and the full API and export-format reference.",
  ...pageUrls("/docs"),
};

/** One line per category explaining what a reader will find, so the index is a map rather
 *  than a second copy of the sidebar. */
const BLURBS: Record<string, string> = {
  "": "Orientation pages that do not belong to one section.",
  "getting-started":
    "What this is, how to run it, and how to configure a model — including a local one.",
  "user-guide": "Using the product: running research, approving it, and reading the citations.",
  architecture: "How the system is put together, and why the boundaries fall where they do.",
  deployment: "Running it for real: Docker, a public deployment, and day-to-day operations.",
  developers: "Setting up to work on the code, testing it, and the conventions it holds to.",
  reference: "Exact contracts — endpoints, the event stream, the export format, every setting.",
  research: "Measurement methodology, kept separate from the product documentation.",
  project: "Where this is going, and what changed in each release.",
};

export default function DocsIndexPage() {
  const categories = docCategories();
  const total = categories.reduce((n, c) => n + c.docs.length, 0);

  if (total === 0) {
    // The docs tree ships with the image; an empty set means the build could not see it.
    // Saying so beats rendering a convincing but empty index.
    return (
      <div className="border border-border bg-bg-surface p-8 text-center">
        <p className="text-sm font-medium text-text-primary">Documentation is unavailable</p>
        <p className="mt-1 text-xs text-text-muted">
          The <code className="font-mono">docs/</code> tree was not found at build time.
        </p>
      </div>
    );
  }

  return (
    <div className="max-w-3xl">
      <h1 className="font-serif text-3xl font-bold tracking-tight text-text-primary">
        Documentation
      </h1>
      <p className="mt-2 text-sm leading-relaxed text-text-muted">
        Documentation for the Multi-Agent Research Assistant. Nothing here is aspirational: every
        statement describes what is built, or is marked explicitly as planned. New here? Start with{" "}
        <Link href="/docs/getting-started/overview" className="text-accent hover:underline">
          Overview
        </Link>
        , then{" "}
        <Link href="/docs/getting-started/quick-start" className="text-accent hover:underline">
          Quick start
        </Link>
        .
      </p>
      <p className="mt-1 font-mono text-xs text-text-muted">{total} documents</p>

      <div className="mt-8 flex flex-col gap-8">
        {categories.map((category) => (
          <section key={category.key} aria-labelledby={`cat-${category.key || "overview"}`}>
            <h2
              id={`cat-${category.key || "overview"}`}
              className="font-mono text-xs font-semibold uppercase tracking-wider text-text-secondary"
            >
              {category.label}
            </h2>
            {BLURBS[category.key] && (
              <p className="mt-1 text-xs leading-relaxed text-text-muted">{BLURBS[category.key]}</p>
            )}
            <ul className="mt-3 divide-y divide-border border border-border bg-bg-surface">
              {category.docs.map((doc) => (
                <li key={doc.slug}>
                  <Link
                    href={`/docs/${doc.slug}`}
                    className="flex items-center justify-between gap-3 px-4 py-2.5 transition-colors hover:bg-bg-elevated"
                  >
                    <span className="min-w-0 truncate font-serif text-sm font-medium text-text-primary">
                      {doc.title}
                    </span>
                    <span className="shrink-0 font-mono text-[0.6875rem] text-text-muted">
                      {doc.slug}
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          </section>
        ))}
      </div>
    </div>
  );
}
