"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import toast from "react-hot-toast";

import { useLogout } from "@/hooks/queries";
import type { User } from "@/lib/types";

import { Avatar } from "./Avatar";
import { ThemeToggle } from "./ThemeToggle";

function NavLink({ href, label }: { href: string; label: string }) {
  const pathname = usePathname();
  const active = pathname === href || pathname.startsWith(`${href}/`);
  return (
    <Link
      href={href}
      aria-current={active ? "page" : undefined}
      className={`rounded-lg px-3 py-1.5 text-sm font-medium transition-colors ${
        active
          ? "bg-bg-elevated text-text-primary"
          : "text-text-secondary hover:bg-bg-elevated hover:text-text-primary"
      }`}
    >
      {label}
    </Link>
  );
}

export function TopNav({ user }: { user?: User }) {
  const router = useRouter();
  const logout = useLogout();

  const onLogout = async () => {
    try {
      await logout.mutateAsync();
    } catch {
      /* logout is best-effort; cookies are cleared server-side regardless */
    } finally {
      toast.success("Signed out");
      router.replace("/login");
    }
  };

  return (
    <header className="sticky top-0 z-30 border-b border-border bg-bg-base/80 backdrop-blur">
      <nav className="mx-auto flex h-14 max-w-6xl items-center gap-1 px-4">
        <Link href="/dashboard" className="mr-4 flex items-center gap-2 font-semibold text-text-primary">
          <span aria-hidden className="text-lg">
            🔬
          </span>
          <span className="hidden sm:inline">Research Assistant</span>
        </Link>

        <NavLink href="/dashboard" label="Dashboard" />
        <NavLink href="/history" label="History" />
        <NavLink href="/settings" label="Settings" />

        <div className="ml-auto flex items-center gap-1">
          <ThemeToggle />
          <details className="group relative">
            <summary
              className="flex h-9 cursor-pointer list-none items-center gap-2 rounded-lg px-2 text-sm text-text-secondary transition-colors hover:bg-bg-elevated hover:text-text-primary [&::-webkit-details-marker]:hidden"
              aria-label="Account menu"
            >
              {user ? (
                <Avatar user={user} size={24} />
              ) : (
                <span className="flex h-6 w-6 items-center justify-center rounded-full bg-accent-muted text-xs font-semibold text-accent">
                  ?
                </span>
              )}
              <span className="hidden max-w-[12rem] truncate md:inline">
                {user?.display_name || user?.email || "Account"}
              </span>
            </summary>
            <div className="absolute right-0 mt-1 w-56 rounded-lg border border-border bg-bg-elevated p-1 shadow-lg">
              {user && (
                <p className="truncate px-3 py-2 text-xs text-text-muted" title={user.email}>
                  {user.email}
                </p>
              )}
              <button
                type="button"
                onClick={onLogout}
                disabled={logout.isPending}
                className="flex w-full items-center gap-2 rounded-md px-3 py-2 text-left text-sm text-text-secondary transition-colors hover:bg-bg-surface hover:text-danger disabled:opacity-50"
              >
                {logout.isPending ? <span className="spinner" /> : "↩"} Sign out
              </button>
            </div>
          </details>
        </div>
      </nav>
    </header>
  );
}
