"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

const TABS = [
  { href: "/profile", label: "Profile" },
  { href: "/settings", label: "Settings" },
];

/**
 * Shared chrome for the account area. Profile and Settings are siblings, so they
 * get one page header and one segmented switcher rather than each inventing its
 * own layout.
 */
export function AccountShell({
  title,
  description,
  children,
}: {
  title: string;
  description: string;
  children: ReactNode;
}) {
  const pathname = usePathname();

  return (
    <div className="mx-auto max-w-3xl">
      <header className="mb-6">
        <h1 className="font-serif text-2xl font-bold tracking-tight text-text-primary">{title}</h1>
        <p className="mt-1 text-sm text-text-muted">{description}</p>
      </header>

      <nav aria-label="Account sections" className="mb-6">
        <div className="segmented">
          {TABS.map((tab) => {
            const active = pathname === tab.href;
            return (
              <Link
                key={tab.href}
                href={tab.href}
                aria-current={active ? "page" : undefined}
                className="segmented-item font-mono text-xs uppercase tracking-wider"
              >
                {tab.label}
              </Link>
            );
          })}
        </div>
      </nav>

      <div className="space-y-5">{children}</div>
    </div>
  );
}
