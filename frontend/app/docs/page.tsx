import Link from "next/link";

import { docCategories } from "@/lib/docs";

export const metadata = { title: "Documentation · Research Assistant" };

/** One line per category explaining what a reader will find, so the index is a map rather
 *  than a second copy of the sidebar. */
const BLURBS: Record<string, string> = {
  "": "Start here — what the documentation set covers and how it is organised.",
  product: "What is being built and for whom, the design system, and the release plan.",
  architecture:
    "Topology, the agent graph, the data and API contracts, and the local-first design.",
  engineering: "Security, testing, deployment, and the standards this codebase holds itself to.",
  guides: "Step-by-step setup for running the assistant on your own hardware.",
  "deep-dive": "Long-form explainers: end-to-end walkthroughs, high- and low-level design.",
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
        These documents are the build contract for the Multi-Agent Research Assistant. Code that
        contradicts them is wrong, and nothing here is aspirational — every statement describes
        what is built, or is marked explicitly as planned.
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
