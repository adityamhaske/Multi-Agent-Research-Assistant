"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { useMe } from "@/hooks/queries";
import { ApiError } from "@/lib/api";

import { TopNav } from "./TopNav";

/**
 * Client half of the auth shell. The server layout ((app)/layout.tsx) already
 * redirects requests with no access cookie, so this is the belt-and-braces case:
 * if `/auth/me` still resolves to 401 after the client's silent refresh attempt,
 * the session is truly gone — bounce to /login. Otherwise render the app chrome
 * with the resolved user.
 */
export function AppShell({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const { data: user, error } = useMe();

  useEffect(() => {
    if (error instanceof ApiError && error.status === 401) {
      router.replace("/login");
    }
  }, [error, router]);

  return (
    <div className="flex min-h-screen flex-col">
      <TopNav user={user} />
      <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-6">{children}</main>
    </div>
  );
}
