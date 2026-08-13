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
 * Account menu in the top nav.
 *
 * Replaces a bare <details> element, which looked like a menu but had none of the
 * behavior: no outside-click dismissal, no Escape, no focus return, no menu
 * semantics for screen readers. This is a real menu.
 */
export function AccountMenu({ user }: { user: User }) {
  const router = useRouter();
  const pathname = usePathname();
  const logout = useLogout();
  const { resolvedTheme, setTheme } = useTheme();

  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);

  // Close on outside click / Escape, and return focus to the trigger so keyboard
  // users don't get dumped at the top of the document.
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

  // Navigating away should never leave a menu hanging open — including via browser
  // back/forward, which no click handler would catch. Done as a render-phase reset
  // (React's adjust-state-on-prop-change) rather than an effect, so there's no
  // extra render pass.
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

  return (
    <div ref={rootRef} className="relative">
      <button
        ref={triggerRef}
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="menu"
        aria-expanded={open}
        className="flex items-center gap-2 rounded-full border border-transparent py-1 pl-1 pr-2.5 text-sm text-text-secondary transition-colors hover:border-border hover:bg-bg-surface hover:text-text-primary"
      >
        <Avatar user={user} size={26} />
        <span className="hidden max-w-[9rem] truncate font-medium sm:inline">
          {firstNameOf(user)}
        </span>
        <svg
          aria-hidden
          viewBox="0 0 12 12"
          className={`h-3 w-3 shrink-0 text-text-muted transition-transform duration-150 ${open ? "rotate-180" : ""}`}
        >
          <path d="M2.5 4.5 6 8l3.5-3.5" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>

      {open && (
        <div
          role="menu"
          aria-label="Account"
          className="menu-surface animate-fade-in absolute right-0 z-40 mt-2 w-64 origin-top-right"
        >
          {/* Identity header — the full email lives here, not in the nav bar. */}
          <div className="flex items-center gap-3 px-2.5 py-2.5">
            <Avatar user={user} size={38} />
            <div className="min-w-0">
              <div className="truncate text-sm font-semibold text-text-primary">
                {user.display_name || firstNameOf(user)}
              </div>
              <div className="truncate text-xs text-text-muted" title={user.email}>
                {user.email}
              </div>
            </div>
          </div>

          <div className="menu-separator" />

          {/* Desktop has no login, no profile store, and no logout (docs/13 §7):
              the account surface shrinks to settings + appearance. */}
          {!isDesktop && (
            <Link href="/profile" role="menuitem" className="menu-item" onClick={() => setOpen(false)}>
              <MenuIcon path="M10 10a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7ZM3.5 17c0-2.9 2.9-5 6.5-5s6.5 2.1 6.5 5" />
              Profile
            </Link>
          )}
          <Link href="/settings" role="menuitem" className="menu-item" onClick={() => setOpen(false)}>
            <MenuIcon path="M10 12.5a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5Z M16.2 12a1.4 1.4 0 0 0 .28 1.55l.05.05a1.7 1.7 0 1 1-2.4 2.4l-.05-.05a1.4 1.4 0 0 0-1.55-.28 1.4 1.4 0 0 0-.85 1.28v.14a1.7 1.7 0 1 1-3.4 0v-.07a1.4 1.4 0 0 0-.92-1.28 1.4 1.4 0 0 0-1.55.28l-.05.05a1.7 1.7 0 1 1-2.4-2.4l.05-.05a1.4 1.4 0 0 0 .28-1.55 1.4 1.4 0 0 0-1.28-.85h-.14a1.7 1.7 0 1 1 0-3.4h.07a1.4 1.4 0 0 0 1.28-.92 1.4 1.4 0 0 0-.28-1.55l-.05-.05a1.7 1.7 0 1 1 2.4-2.4l.05.05a1.4 1.4 0 0 0 1.55.28h.07a1.4 1.4 0 0 0 .85-1.28v-.14a1.7 1.7 0 1 1 3.4 0v.07a1.4 1.4 0 0 0 .85 1.28 1.4 1.4 0 0 0 1.55-.28l.05-.05a1.7 1.7 0 1 1 2.4 2.4l-.05.05a1.4 1.4 0 0 0-.28 1.55v.07a1.4 1.4 0 0 0 1.28.85h.14a1.7 1.7 0 1 1 0 3.4h-.07a1.4 1.4 0 0 0-1.28.85Z" />
            Settings
          </Link>

          <div className="menu-separator" />

          <button
            type="button"
            role="menuitem"
            onClick={() => setTheme(isDark ? "light" : "dark")}
            className="menu-item justify-between"
          >
            <span className="flex items-center gap-2.5">
              <MenuIcon
                path={
                  isDark
                    ? "M10 3v1.5M10 15.5V17M17 10h-1.5M4.5 10H3M14.95 5.05l-1.06 1.06M6.11 13.89l-1.06 1.06M14.95 14.95l-1.06-1.06M6.11 6.11 5.05 5.05M13 10a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z"
                    : "M16.5 11.4A6.6 6.6 0 0 1 8.6 3.5a6.6 6.6 0 1 0 7.9 7.9Z"
                }
              />
              Appearance
            </span>
            <span className="text-xs text-text-muted">{isDark ? "Dark" : "Light"}</span>
          </button>

          {!isDesktop && (
            <>
              <div className="menu-separator" />

              <button
                type="button"
                role="menuitem"
                data-danger="true"
                onClick={onSignOut}
                disabled={logout.isPending}
                className="menu-item"
              >
                {logout.isPending ? (
                  <span className="spinner" style={{ width: 14, height: 14 }} />
                ) : (
                  <MenuIcon path="M12.5 13.5 16 10l-3.5-3.5M16 10H7M11 3.5H5.5a1.5 1.5 0 0 0-1.5 1.5v10a1.5 1.5 0 0 0 1.5 1.5H11" />
                )}
                Sign out
              </button>
            </>
          )}
        </div>
      )}
    </div>
  );
}

function MenuIcon({ path }: { path: string }) {
  return (
    <svg aria-hidden viewBox="0 0 20 20" className="h-4 w-4 shrink-0 text-text-muted">
      <path
        d={path}
        fill="none"
        stroke="currentColor"
        strokeWidth="1.4"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
