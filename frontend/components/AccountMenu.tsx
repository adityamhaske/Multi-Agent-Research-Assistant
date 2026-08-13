"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useTheme } from "next-themes";
import { useEffect, useRef, useState } from "react";
import toast from "react-hot-toast";

import { useLogout } from "@/hooks/queries";
import { isDesktop } from "@/lib/desktop";
import type { User } from "@/lib/types";

import { Avatar } from "./Avatar";

/** First name only — the nav shows who you are, not your whole identity. */
export function firstNameOf(user: Pick<User, "display_name" | "email">): string {
  const name = (user.display_name ?? "").trim();
  if (name) return name.split(/\s+/)[0];
  // No name set: fall back to the local part of the email, never the full address.
  const local = (user.email ?? "").split("@")[0] ?? "";
  return local.charAt(0).toUpperCase() + local.slice(1);
}

/**
 * Account menu for the sidebar.
 *
 * Supports expanded full-width profile card trigger and collapsed compact icon trigger.
 * Positions the popup menu upwards/outwards so it is never clipped or offscreen.
 */
export function AccountMenu({ user, collapsed = false }: { user: User; collapsed?: boolean }) {
  const router = useRouter();
  const pathname = usePathname();
  const logout = useLogout();
  const { resolvedTheme, setTheme } = useTheme();

  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);

  // Close on outside click / Escape, and return focus to the trigger
  useEffect(() => {
    if (!open) return;

    const onPointerDown = (e: PointerEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false);
    };
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setOpen(false);
        triggerRef.current?.focus();
      }
    };
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  // Navigating away should close the menu
  const [prevPath, setPrevPath] = useState(pathname);
  if (pathname !== prevPath) {
    setPrevPath(pathname);
    if (open) setOpen(false);
  }

  const onSignOut = async () => {
    setOpen(false);
    try {
      await logout.mutateAsync();
    } catch {
      /* best-effort: cookies are cleared server-side regardless */
    } finally {
      toast.success("Signed out");
      router.replace("/login");
    }
  };

  const isDark = resolvedTheme === "dark";
  const displayName = user.display_name?.trim() || firstNameOf(user);

  return (
    <div ref={rootRef} className="relative w-full">
      <button
        ref={triggerRef}
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="menu"
        aria-expanded={open}
        title={collapsed ? `${displayName} (${user.email})` : undefined}
        className={`group flex w-full items-center border border-transparent transition-all duration-150 ${
          collapsed
            ? "justify-center p-1.5 hover:bg-bg-elevated text-text-secondary hover:text-text-primary"
            : "gap-2.5 p-2 text-left hover:border-border hover:bg-bg-elevated/70 text-text-secondary hover:text-text-primary"
        } ${open ? "border-border bg-bg-elevated text-text-primary" : ""}`}
      >
        <Avatar user={user} size={collapsed ? 30 : 32} />
        {!collapsed && (
          <>
            <div className="min-w-0 flex-1">
              <div className="truncate text-xs font-semibold text-text-primary">
                {displayName}
              </div>
              <div className="truncate font-mono text-[0.6875rem] text-text-muted">
                {user.email}
              </div>
            </div>
            <svg
              aria-hidden
              viewBox="0 0 20 20"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.75"
              strokeLinecap="round"
              strokeLinejoin="round"
              className={`h-4 w-4 shrink-0 text-text-muted transition-transform duration-200 group-hover:text-text-primary ${
                open ? "rotate-180 text-text-primary" : ""
              }`}
            >
              <path d="m6 8 4 4 4-4" />
            </svg>
          </>
        )}
      </button>

      {open && (
        <div
          role="menu"
          aria-label="Account"
          className={`menu-surface animate-fade-in absolute z-50 w-64 ${
            collapsed
              ? "left-full bottom-0 ml-3 origin-bottom-left"
              : "bottom-full left-0 mb-2 origin-bottom-left"
          }`}
        >
          {/* Identity header */}
          <div className="flex items-center gap-3 px-3 py-2.5 bg-bg-elevated/40 border-b border-border">
            <Avatar user={user} size={36} />
            <div className="min-w-0 flex-1">
              <div className="truncate font-serif text-sm font-bold text-text-primary">
                {user.display_name || firstNameOf(user)}
              </div>
              <div className="truncate font-mono text-xs text-text-muted" title={user.email}>
                {user.email}
              </div>
            </div>
          </div>

          <div className="menu-separator my-1" />

          {/* Nav items */}
          {!isDesktop && (
            <Link
              href="/profile"
              role="menuitem"
              className="menu-item"
              onClick={() => setOpen(false)}
            >
              <svg
                aria-hidden
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.75"
                strokeLinecap="round"
                strokeLinejoin="round"
                className="h-4 w-4 text-text-muted"
              >
                <path d="M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2" />
                <circle cx="12" cy="7" r="4" />
              </svg>
              <span>Profile</span>
            </Link>
          )}

          <Link
            href="/settings"
            role="menuitem"
            className="menu-item"
            onClick={() => setOpen(false)}
          >
            <svg
              aria-hidden
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.75"
              strokeLinecap="round"
              strokeLinejoin="round"
              className="h-4 w-4 text-text-muted"
            >
              <path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z" />
              <circle cx="12" cy="12" r="3" />
            </svg>
            <span>Settings</span>
          </Link>

          <div className="menu-separator my-1" />

          {/* Theme switcher */}
          <button
            type="button"
            role="menuitem"
            onClick={() => setTheme(isDark ? "light" : "dark")}
            className="menu-item justify-between"
          >
            <span className="flex items-center gap-2.5">
              {isDark ? (
                <svg
                  aria-hidden
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="1.75"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  className="h-4 w-4 text-warning"
                >
                  <circle cx="12" cy="12" r="4" />
                  <path d="M12 2v2m0 16v2M4.93 4.93l1.41 1.41m11.32 11.32l1.41 1.41M2 12h2m16 0h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41" />
                </svg>
              ) : (
                <svg
                  aria-hidden
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="1.75"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  className="h-4 w-4 text-text-muted"
                >
                  <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
                </svg>
              )}
              <span>Appearance</span>
            </span>
            <span className="text-[0.6875rem] font-medium px-1.5 py-0.5 rounded bg-bg-elevated text-text-muted">
              {isDark ? "Dark" : "Light"}
            </span>
          </button>

          {!isDesktop && (
            <>
              <div className="menu-separator my-1" />

              <button
                type="button"
                role="menuitem"
                data-danger="true"
                onClick={onSignOut}
                disabled={logout.isPending}
                className="menu-item text-danger hover:bg-danger/10"
              >
                {logout.isPending ? (
                  <span className="spinner" style={{ width: 14, height: 14 }} />
                ) : (
                  <svg
                    aria-hidden
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="1.75"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    className="h-4 w-4"
                  >
                    <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
                    <polyline points="16 17 21 12 16 7" />
                    <line x1="21" y1="12" x2="9" y2="12" />
                  </svg>
                )}
                <span>Sign out</span>
              </button>
            </>
          )}
        </div>
      )}
    </div>
  );
}
