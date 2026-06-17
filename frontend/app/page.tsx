import { redirect } from "next/navigation";

export default function Home() {
  // Server-side: always send to /login; client-side redirect to /dashboard happens in login page
  redirect("/login");
}
