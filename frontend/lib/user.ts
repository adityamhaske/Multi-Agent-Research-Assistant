import type { User } from "@/lib/types";

/**
 * A short label for the signed-in account.
 *
 * Pure, and in `lib/` rather than beside the account menu, because two surfaces derive
 * the same label and neither should have to import the other's component tree to do it.
 *
 * **Never the full address.** The local part is a derived label — it cannot be written to,
 * and it is not the identifier anyone reuses as a credential. The address itself belongs on
 * Profile, which a user opens deliberately, not in chrome that is on screen all session.
 */
export function firstNameOf(user: Pick<User, "display_name" | "email">): string {
  const name = (user.display_name ?? "").trim();
  if (name) return name.split(/\s+/)[0];
  const local = (user.email ?? "").split("@")[0] ?? "";
  return local.charAt(0).toUpperCase() + local.slice(1);
}
