import type { AgentRole, ModelCatalog } from "@/lib/types";

/**
 * What each of the five public agent roles is called and does — one home for the copy that
 * Settings → Models (which model a role uses) and Settings → Agents (how it behaves) both
 * show, so the two pages cannot describe the same role differently.
 */
export const ROLE_COPY: Record<AgentRole, { label: string; blurb: string }> = {
  planner: { label: "Planner", blurb: "Breaks your question into research tasks." },
  executor: { label: "Executor", blurb: "Runs the searches and gathers evidence." },
  critic: { label: "Critic", blurb: "Grades that evidence and sends weak work back." },
  synthesizer: { label: "Synthesizer", blurb: "Writes the cited report you read." },
  chat: { label: "Follow-up chat", blurb: "Answers questions about a finished report." },
};

/**
 * The model a role currently runs on, as a person should read it — for display only.
 *
 * Reads the catalog's effective routing, which is what a run would dial today. A route the
 * catalog does not list (a custom endpoint's model, say) shows its model id rather than
 * nothing; a catalog that has not loaded, or a role it does not route, shows null so the
 * caller can say so instead of guessing.
 */
export function roleModelLabel(catalog: ModelCatalog | undefined, role: AgentRole): string | null {
  const route = catalog?.effective_routing[role];
  if (!route) return null;
  const listed = catalog.models.find((m) => m.route === route);
  if (listed) return listed.display_name;
  const colon = route.indexOf(":");
  return colon >= 0 ? route.slice(colon + 1) : route;
}
