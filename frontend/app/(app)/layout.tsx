import { cookies } from "next/headers";
import { redirect } from "next/navigation";

import { AppShell } from "@/components/AppShell";

/**
 * Server-side auth guard for every authenticated page (docs/07 §2). A missing access
 * cookie means "not logged in here" — redirect before any app chrome renders. Token
 * validity / silent refresh is handled client-side by AppShell + the API client, so a
 * merely-expired access token recovers without a login round-trip.
 */
export default async function AppLayout({ children }: { children: React.ReactNode }) {
  const store = await cookies();
  if (!store.has("access_token")) redirect("/login");
  return <AppShell>{children}</AppShell>;
}
