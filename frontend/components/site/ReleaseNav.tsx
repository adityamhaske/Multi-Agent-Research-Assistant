"use client";

import { useCallback, useSyncExternalStore } from "react";

import { activeSection } from "@/lib/activeSection";

/**
 * The releases page's version index: a dropdown under the header on a narrow screen, and a
 * sticky column beside the entries from `lg` up.
 *
 * Two controls rather than one list restyled per breakpoint, because they are different
 * controls: on a phone a row of eight links wraps into a wall above the first entry, and
 * the platform's own picker is the compact way to choose one of many. Only one is ever
 * displayed, and `display: none` takes the other out of the accessibility tree, so a screen
 * reader never meets the versions twice.
 *
 * Both follow the scroll position — the column highlights the version being read and the
 * dropdown shows it. It is read through `useSyncExternalStore` rather than set from an
 * effect (frontend/AGENTS.md): scroll position is external state, and the snapshot is a
 * plain id, so React re-renders only when the section being read changes, not on every
 * scroll event. The static export renders the first version as current — there is no
 * scroll position at build time — and the first client render corrects it.
 */

export interface ReleaseNavItem {
  id: string;
  version: string;
  /** The tag date, or why there is none. */
  label: string;
  latest: boolean;
}

// Below the 3.5rem sticky site header, with room for the 5rem scroll margin each entry
// carries — a version the reader just jumped to lands above this line and counts as read.
const READING_LINE = 120;

function subscribe(onChange: () => void): () => void {
  window.addEventListener("scroll", onChange, { passive: true });
  window.addEventListener("resize", onChange);
  window.addEventListener("hashchange", onChange);
  return () => {
    window.removeEventListener("scroll", onChange);
    window.removeEventListener("resize", onChange);
    window.removeEventListener("hashchange", onChange);
  };
}

/**
 * Move to a version the way following its link would — the fragment changes, so Back
 * returns to where the reader was. Setting the fragment it already has is a no-op in every
 * browser, which is the case after jumping to a version, scrolling away and choosing it
 * again; that one is scrolled to directly.
 */
function jumpTo(id: string) {
  if (window.location.hash === `#${id}`) {
    document.getElementById(id)?.scrollIntoView();
  } else {
    window.location.hash = id;
  }
}

export function ReleaseNav({ items }: { items: ReleaseNavItem[] }) {
  const read = useCallback((): string | null => {
    const ids = items.map((item) => item.id);
    const tops = ids.map(
      (id) => document.getElementById(id)?.getBoundingClientRect().top ?? Infinity,
    );
    const scrollable = document.documentElement.scrollHeight;
    // `scrollY > 0`: a page too short to scroll is "at the bottom" while still at the top,
    // and would mark the last entry before anyone had read the first.
    const atBottom =
      window.scrollY > 0 && window.innerHeight + window.scrollY >= scrollable - 2;
    const fragment = decodeURIComponent(window.location.hash.slice(1));
    const index = activeSection({
      tops,
      readingLine: READING_LINE,
      viewportHeight: window.innerHeight,
      atBottom,
      targetIndex: ids.indexOf(fragment),
    });
    return ids[index] ?? null;
  }, [items]);

  const active = useSyncExternalStore(subscribe, read, () => null);

  return (
    <>
      <div className="lg:hidden">
        <label
          htmlFor="release-version"
          className="font-mono text-[0.6875rem] font-semibold uppercase tracking-wider text-text-muted"
        >
          Jump to version
        </label>
        <select
          id="release-version"
          value={active ?? items[0]?.id ?? ""}
          onChange={(e) => jumpTo(e.target.value)}
          className="mt-2 h-10 w-full border border-border bg-bg-elevated px-2.5 font-mono text-xs text-text-primary focus:border-text-primary focus:outline-none"
        >
          {items.map((item) => (
            <option key={item.id} value={item.id}>
              {item.version} · {item.label}
              {item.latest ? " (latest)" : ""}
            </option>
          ))}
        </select>
      </div>

      <nav aria-label="Versions" className="hidden lg:block">
        <p className="font-mono text-[0.6875rem] font-semibold uppercase tracking-wider text-text-muted">
          Versions
        </p>
        <ul className="mt-2 flex flex-col">
          {items.map((item) => {
            const current = item.id === active;
            return (
              <li key={item.id}>
                <a
                  href={`#${item.id}`}
                  aria-current={current ? "true" : undefined}
                  className={`block border-l-2 py-1.5 pl-3 pr-1 font-mono text-xs transition-colors ${
                    current
                      ? "border-accent text-accent"
                      : "border-transparent text-text-secondary hover:text-text-primary"
                  }`}
                >
                  <span className="flex items-baseline gap-2">
                    <span className={current ? "font-semibold" : undefined}>{item.version}</span>
                    {item.latest && (
                      <span className="text-[0.625rem] uppercase tracking-wider text-text-muted">
                        latest
                      </span>
                    )}
                  </span>
                  <span className="block text-[0.6875rem] text-text-muted">{item.label}</span>
                </a>
              </li>
            );
          })}
        </ul>
      </nav>
    </>
  );
}
