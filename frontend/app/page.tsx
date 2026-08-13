import { cookies } from "next/headers";
import { redirect } from "next/navigation";

import { isDesktop } from "@/lib/desktop";

// Root entry (docs/07 §2): authed → /dashboard, else → /login. Server-side cookie
// check so there's no unauthenticated flash of app chrome. Desktop builds have no
// login (docs/13 §7) — the flag is inlined, so the cookie read compiles out.
export default async function Home() {
  if (!isDesktop) {
    const store = await cookies();
    if (!store.has("access_token")) redirect("/login");
  }
  redirect("/dashboard");
}
