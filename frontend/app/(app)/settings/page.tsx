import { redirect } from "next/navigation";

// /settings has no content of its own — it is the rail's default section (docs/07 §2,
// Phase 3), same redirect pattern as the root page.
export default function SettingsIndexPage() {
  redirect("/settings/models");
}
