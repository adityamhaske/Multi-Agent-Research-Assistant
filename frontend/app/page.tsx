import { cookies } from "next/headers";
import { redirect } from "next/navigation";

// Root entry (docs/07 §2): authed → /dashboard, else → /login. Server-side cookie
// check so there's no unauthenticated flash of app chrome.
export default async function Home() {
  const store = await cookies();
  redirect(store.has("access_token") ? "/dashboard" : "/login");
}
