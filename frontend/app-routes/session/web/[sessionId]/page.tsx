import { SessionView } from "@/components/session/SessionView";

/**
 * Web session route (docs/13 §7). Dynamic segments are fine on the server build —
 * any id renders on demand (`dynamicParams` defaults to true).
 *
 * The route files under `app-routes/` are variant-exclusive: `scripts/prepare-session-routes.mjs`
 * links the one matching the build target into `app/(app)/session/`. The desktop
 * static export cannot ship dynamic segments at all (Next rejects a
 * `generateStaticParams` that produces zero paths), so that variant gets the
 * `/session?id=` route instead.
 */
export default async function SessionPage({
  params,
}: {
  params: Promise<{ sessionId: string }>;
}) {
  const { sessionId } = await params;
  return <SessionView sessionId={sessionId} />;
}
