import { cookies } from "next/headers";
import { redirect } from "next/navigation";

import { ActiveProjectProvider } from "@/components/ActiveProject";
import { AppShell } from "@/components/AppShell";
import { isDesktop } from "@/lib/desktop";

/**
 * Server-side auth guard for every authenticated page (docs/07 "Components"). A missing access
 * cookie means "not logged in here" — redirect before any app chrome renders. Token
 * validity / silent refresh is handled client-side by AppShell + the API client, so a
 * merely-expired access token recovers without a login round-trip.
 *
 * Desktop builds compile this guard out (docs/13 §7): there is no login and no
 * cookie — a static export couldn't read cookies anyway. The flag is inlined at
 * build time, so the desktop bundle ships without this branch at all.
 *
 * The active project is provided here, not in the root providers: it is a query, and the
 * public site shares the root layout with no API behind it on GitHub Pages.
 */
export default async function AppLayout({ children }: { children: React.ReactNode }) {
  if (!isDesktop) {
    const store = await cookies();
    if (!store.has("access_token")) redirect("/login");
  }
  return (
    <ActiveProjectProvider>
      <AppShell>{children}</AppShell>
    </ActiveProjectProvider>
  );
}
