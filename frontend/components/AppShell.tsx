"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { useMe } from "@/hooks/queries";
import { ApiError } from "@/lib/api";
import { isDesktop } from "@/lib/desktop";

import { TopNav } from "./TopNav";

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
    <div className="flex min-h-screen flex-col">
      <TopNav user={user} />
      <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-6">{children}</main>
    </div>
  );
}
