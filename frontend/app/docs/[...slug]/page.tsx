import Link from "next/link";
import { notFound } from "next/navigation";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { allDocs, docOrder, getDoc, rewriteDocLinks } from "@/lib/docs";

/**
 * One document.
 *
 * Statically generated per document, so the shipped image needs no filesystem access and
 * the desktop static export gets the same pages for free.
 *
 * Rendering goes through `react-markdown` with raw-HTML passthrough left off, which CI
 * enforces by grep (docs/06 §5). These files are trusted repo content, but the report
 * renderer next door handles model-generated Markdown, and one safe pipeline is easier to
 * keep safe than two that differ only by who is trusted today.
 */

export const dynamicParams = false;

export function generateStaticParams() {
  return allDocs().map((doc) => ({ slug: doc.slug.split("/") }));
}

export async function generateMetadata({ params }: { params: Promise<{ slug: string[] }> }) {
  const { slug } = await params;
  const doc = getDoc(slug.join("/"));
  return { title: doc ? `${doc.title} · Docs` : "Docs" };
}

/** Heading ids so section links (and the docs' own `#anchor` links) resolve. */
function slugifyHeading(children: React.ReactNode): string {
  return String(children)
    .toLowerCase()
    .replace(/[^\w\s-]/g, "")
    .trim()
    .replace(/\s+/g, "-");
}

export default async function DocPage({ params }: { params: Promise<{ slug: string[] }> }) {
  const { slug: parts } = await params;
  const slug = parts.join("/");
  const doc = getDoc(slug);
  if (!doc) notFound();

  const order = docOrder();
  const index = order.findIndex((d) => d.slug === slug);
  const prev = index > 0 ? order[index - 1] : null;
  const next = index >= 0 && index < order.length - 1 ? order[index + 1] : null;

  // The source files link each other by relative path, which only resolves on GitHub.
  const body = rewriteDocLinks(doc.body, doc.slug);

  return (
    <article className="min-w-0">
      <div className="mb-6 font-mono text-[0.6875rem] uppercase tracking-widest text-text-muted">
        <Link href="/docs" className="hover:text-text-primary">
          Docs
        </Link>
        {doc.category && <span> / {doc.category.replace("-", " ")}</span>}
      </div>

      <div
        className="prose prose-sm max-w-none dark:prose-invert
                   prose-headings:font-serif prose-headings:tracking-tight
                   prose-h1:text-3xl prose-h1:mb-3
                   prose-h2:mt-10 prose-h2:border-b prose-h2:border-border prose-h2:pb-1.5
                   prose-code:font-mono prose-code:text-[0.85em] prose-code:before:content-none prose-code:after:content-none
                   prose-pre:border prose-pre:border-border prose-pre:bg-bg-elevated
                   prose-pre:text-text-primary [&_pre_code]:text-text-primary
                   prose-table:text-sm prose-th:font-mono prose-th:text-xs prose-th:uppercase prose-th:tracking-wider
                   prose-a:text-accent prose-a:no-underline hover:prose-a:underline"
      >
        <ReactMarkdown
          remarkPlugins={[remarkGfm]}
          components={{
            h2: ({ children }) => <h2 id={slugifyHeading(children)}>{children}</h2>,
            h3: ({ children }) => <h3 id={slugifyHeading(children)}>{children}</h3>,
            // Wide tables scroll inside their own container rather than pushing the page
            // sideways — several of these documents carry very wide comparisons.
            table: ({ children }) => (
              <div className="overflow-x-auto">
                <table>{children}</table>
              </div>
            ),
          }}
        >
          {body}
        </ReactMarkdown>
      </div>

      {(prev || next) && (
        <nav
          aria-label="Document navigation"
          className="mt-12 flex items-stretch gap-3 border-t border-border pt-6"
        >
          {prev ? (
            <Link
              href={`/docs/${prev.slug}`}
              className="flex-1 border border-border bg-bg-surface px-4 py-3 transition-colors hover:bg-bg-elevated"
            >
              <div className="font-mono text-[0.6875rem] uppercase tracking-wider text-text-muted">
                ← Previous
              </div>
              <div className="mt-0.5 text-sm font-medium text-text-primary">{prev.title}</div>
            </Link>
          ) : (
            <div className="flex-1" />
          )}
          {next ? (
            <Link
              href={`/docs/${next.slug}`}
              className="flex-1 border border-border bg-bg-surface px-4 py-3 text-right transition-colors hover:bg-bg-elevated"
            >
              <div className="font-mono text-[0.6875rem] uppercase tracking-wider text-text-muted">
                Next →
              </div>
              <div className="mt-0.5 text-sm font-medium text-text-primary">{next.title}</div>
            </Link>
          ) : (
            <div className="flex-1" />
          )}
        </nav>
      )}
    </article>
  );
}
