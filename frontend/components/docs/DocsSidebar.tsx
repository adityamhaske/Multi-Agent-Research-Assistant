"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useMemo, useState } from "react";

import type { DocCategory } from "@/lib/docs";

/**
 * Docs navigation with filter-as-you-type.
 *
 * The filter matches titles only, and deliberately not body text: full-text search over
 * this corpus would mean shipping every document to the browser to answer a question the
 * reader can usually answer from a title. When a title match is not enough, the document
 * is one click away and the browser's own find-in-page beats anything reimplemented here.
 */
export function DocsSidebar({ categories }: { categories: DocCategory[] }) {
  const pathname = usePathname();
  const [filter, setFilter] = useState("");

  const shown = useMemo(() => {
    const q = filter.trim().toLowerCase();
    if (!q) return categories;
    return categories
      .map((c) => ({ ...c, docs: c.docs.filter((d) => d.title.toLowerCase().includes(q)) }))
      .filter((c) => c.docs.length > 0);
  }, [categories, filter]);

  return (
    <nav aria-label="Documentation" className="flex h-full flex-col gap-4">
      <div>
        <label htmlFor="docs-filter" className="sr-only">
          Filter documents
        </label>
        <input
          id="docs-filter"
          type="search"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          placeholder="Filter…"
          className="input-base h-8 w-full px-2.5 font-mono text-xs"
        />
      </div>

      {shown.length === 0 ? (
        <p className="px-1 font-mono text-xs text-text-muted">
          No document matches “{filter}”.
        </p>
      ) : (
        <div className="flex flex-col gap-5 overflow-y-auto pb-6">
          {shown.map((category) => (
            <div key={category.key}>
              <div className="mb-1.5 px-1 font-mono text-[0.6875rem] font-semibold uppercase tracking-wider text-text-muted">
                {category.label}
              </div>
              <ul className="flex flex-col">
                {category.docs.map((doc) => {
                  const href = `/docs/${doc.slug}`;
                  const active = pathname === href;
                  return (
                    <li key={doc.slug}>
                      <Link
                        href={href}
                        aria-current={active ? "page" : undefined}
                        className="block border-l-2 py-1 pl-2.5 pr-1 text-[0.8125rem] leading-snug transition-colors"
                        style={{
                          borderColor: active ? "var(--accent)" : "transparent",
                          color: active ? "var(--accent)" : "var(--text-secondary)",
                          fontWeight: active ? 600 : 400,
                        }}
                      >
                        {doc.title}
                      </Link>
                    </li>
                  );
                })}
              </ul>
            </div>
          ))}
        </div>
      )}
    </nav>
  );
}
