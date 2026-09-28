import { latestRelease } from "@/lib/releases";

/**
 * What the product does, for the landing page — a card each, and only what ships.
 *
 * Same honesty rules as `releases.ts` and `comparison.ts`. A feature is listed because the
 * current build does it, and a limit that decides whether it applies to *you* — a host
 * that lacks it, a measurement that is one run — goes in the same card rather than being
 * left for the docs to confess. A visitor reads this page to decide whether to install the
 * thing; a caveat they only meet after installing reads as a bait and switch.
 *
 * `since` is set only where the release that introduced a feature is on record, and a card
 * is marked "New" only while that release is the latest — so the badge retires itself at
 * the next tag instead of waiting for someone to remember it.
 */
export interface Feature {
  title: string;
  body: string;
  /** Where to read more: a site path. */
  href: string;
  /** The release that introduced it, spelled as in `RELEASES` (`v` prefix included). */
  since?: string;
}

export const FEATURES: Feature[] = [
  {
    title: "Your instructions for each agent",
    body: "Rewrite how the planner, executor, critic, synthesizer and follow-up chat behave. The checks that keep research honest cannot be rewritten, and a run’s verification bundle records exactly which instructions produced it.",
    href: "/docs/user-guide/agent-instructions",
    since: "v3.0.0",
  },
  {
    title: "A record, not just a report",
    body: "Evidence, sources, claims, the evidence each claim resolved to, and conflicting sources are records you can inspect. A claim that resolved to no evidence says so instead of looking supported.",
    href: "/docs/getting-started/research-record",
  },
  {
    title: "Any model, for each agent",
    body: "Route each agent to Google, Anthropic, OpenAI, OpenRouter, any OpenAI-compatible endpoint, or a local model through Ollama — on your own keys, with nothing proxied through a service of ours.",
    href: "/docs/getting-started/configuration",
  },
  {
    title: "Chat over approved research",
    body: "Project chat answers from the reports you approved in a project and cites the ones it used, so an answer traces back to the research behind it. Drafts and rejected work never reach it. Self-hosted server only.",
    href: "/docs/user-guide/projects-and-memory",
  },
  {
    title: "Desktop app or your own server",
    body: "Install on an Apple Silicon Mac, Windows or Linux with no Docker, database or login to set up, or self-host the full stack with one command. Desktop builds are unsigned, so macOS and Windows warn on first launch.",
    href: "/download",
  },
  {
    title: "Graded by an independent judge",
    body: "Citation support measured 96.4% on ten fixed questions, graded by a model from a different vendor than every model under test. One run on one model routing — and published as exactly that.",
    href: "/docs/research/citation-fidelity-benchmark",
    since: "v3.0.0",
  },
];

/** Whether a feature arrived in the release the site currently offers. */
export function isNew(feature: Feature): boolean {
  const latest = latestRelease();
  return feature.since !== undefined && latest !== null && feature.since === latest.version;
}
