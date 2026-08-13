import { cookies } from "next/headers";
import { redirect } from "next/navigation";

import { AppShell } from "@/components/AppShell";
import { isDesktop } from "@/lib/desktop";

/**
 * Server-side auth guard for every authenticated page (docs/07 §2). A missing access
 * cookie means "not logged in here" — redirect before any app chrome renders. Token
 * validity / silent refresh is handled client-side by AppShell + the API client, so a
 * merely-expired access token recovers without a login round-trip.
 *
 * Desktop builds compile this guard out (docs/13 §7): there is no login and no
 * cookie — a static export couldn't read cookies anyway. The flag is inlined at
 * build time, so the desktop bundle ships without this branch at all.
 */
export default async function AppLayout({ children }: { children: React.ReactNode }) {
  if (!isDesktop) {
    const store = await cookies();
    if (!store.has("access_token")) redirect("/login");
  }
  return <AppShell>{children}</AppShell>;
}
