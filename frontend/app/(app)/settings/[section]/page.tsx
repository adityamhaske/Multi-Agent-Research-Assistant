import { SectionContent } from "./SectionContent";

// A Server Component wrapper is required here — `generateStaticParams` cannot be
// exported from a "use client" file (the desktop static export needs it; see
// AGENTS.md's note on `/session/[sessionId]` for the same constraint), so the actual
// section UI lives in the client component this renders.
export function generateStaticParams() {
  // A fixed, known set — unlike `/session/[sessionId]`'s unbounded ids.
  return [
    "models",
    "connections",
    "search",
    "research",
    "projects",
    "appearance",
    "advanced",
  ].map((section) => ({ section }));
}

export default async function SettingsSectionPage({
  params,
}: {
  params: Promise<{ section: string }>;
}) {
  const { section } = await params;
  return <SectionContent section={section} />;
}
