"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import type { User } from "@/lib/types";

import { AccountMenu } from "./AccountMenu";
import { ProjectSwitcher } from "./ProjectSwitcher";

function NavLink({ href, label }: { href: string; label: string }) {
  const pathname = usePathname();
  const active = pathname === href || pathname.startsWith(`${href}/`);
  return (
    <Link
      href={href}
      aria-current={active ? "page" : undefined}
      className={`relative rounded-lg px-3 py-1.5 text-sm transition-colors ${
        active
          ? "font-medium text-text-primary"
          : "text-text-muted hover:text-text-primary"
      }`}
    >
      {label}
      {/* Underline marker rather than a filled pill — quieter, and it doesn't
          compete with the primary action button on the page. */}
      {active && (
        <span
          aria-hidden
          className="absolute inset-x-3 -bottom-[13px] h-0.5 rounded-full bg-accent"
        />
      )}
    </Link>
  );
}

export function TopNav({ user }: { user?: User }) {
  return (
    <header className="sticky top-0 z-30 border-b border-border bg-bg-base/85 backdrop-blur-md">
      <nav className="mx-auto flex h-14 max-w-6xl items-center gap-1 px-4 sm:px-6">
        <Link
          href="/dashboard"
          className="mr-5 flex items-center gap-2 text-[0.9375rem] font-semibold tracking-[-0.01em] text-text-primary"
        >
          <span
            aria-hidden
            className="flex h-6 w-6 items-center justify-center rounded-md bg-accent text-[0.8125rem] text-accent-contrast"
          >
            ◇
          </span>
          <span className="hidden sm:inline">Research Assistant</span>
        </Link>

        {/* Only the working surfaces live here; account lives in the menu. */}
        <NavLink href="/dashboard" label="Dashboard" />
        <NavLink href="/history" label="History" />
        <NavLink href="/chat" label="Chat" />

        {/* Scope selector sits with the nav: every surface below it is project-scoped. */}
        <div className="ml-3 hidden sm:block">
          <ProjectSwitcher />
        </div>

        <div className="ml-auto flex items-center">
          {user ? (
            <AccountMenu user={user} />
          ) : (
            <div className="h-8 w-8 animate-pulse rounded-full bg-bg-elevated" aria-hidden />
          )}
        </div>
      </nav>
    </header>
  );
}
