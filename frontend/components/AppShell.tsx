"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { useMe } from "@/hooks/queries";
import { ApiError } from "@/lib/api";
import { isDesktop } from "@/lib/desktop";

import { SideNav } from "./SideNav";

/**
 * Client half of the auth shell. The server layout ((app)/layout.tsx) already
 * redirects requests with no access cookie, so this is the belt-and-braces case:
 * if `/auth/me` still resolves to 401 after the client's silent refresh attempt,
 * the session is truly gone — bounce to /login. Otherwise render the app chrome
 * with the resolved user.
 *
 * Desktop builds have no /login to bounce to: a 401 there means the shell's
 * handshake token is broken, and the error state below is the honest surface.
 */
export function AppShell({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const { data: user, error } = useMe();

  useEffect(() => {
    if (error instanceof ApiError && error.status === 401 && !isDesktop) {
      router.replace("/login");
    }
  }, [error, router]);

  if (isDesktop && error instanceof ApiError && error.status === 401) {
    return (
      <div className="flex min-h-screen items-center justify-center px-4">
        <div className="card max-w-md text-center">
          <h1 className="text-lg font-semibold text-text-primary">Desktop service unreachable</h1>
          <p className="mt-2 text-sm text-text-secondary">
            The local research service rejected this window&apos;s launch token. Quit and
            reopen the app — a fresh launch issues a fresh token.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div
      // The density preference had a Settings control that saved it and CSS tokens that
      // responded to it, and nothing in between: `[data-density="compact"]` was never
      // put on the DOM, so choosing "compact" persisted a value the app never read.
      // Applied on the shell rather than <html> because the tokens are inherited and
      // this is the outermost element the client actually owns (docs/07 §2, Phase 7).
      data-density={user?.preferences?.density ?? "comfortable"}
      className="flex min-h-screen flex-col md:flex-row bg-bg-base"
    >
      <SideNav user={user} />
      <main className="flex-1 w-full min-w-0">
        <div className="mx-auto w-full max-w-6xl px-4 py-6 md:px-8">
          {children}
        </div>
      </main>
    </div>
  );
}
