"use client";

import { useSearchParams } from "next/navigation";
import { Suspense } from "react";

import { SessionView } from "@/components/session/SessionView";

/**
 * Desktop session route (docs/13 §7).
 *
 * `output: export` can only ship pages it actually generated, and the session ids of
 * future runs are unknowable at build time — Next even rejects a dynamic route whose
 * `generateStaticParams` produces zero paths. So the desktop build links here
 * (`/session?id=…`, via `sessionHref`) instead of `/session/[sessionId]`. Same
 * `SessionView`, same SSE handling, same citation UX; only the URL shape differs.
 * The web build never links here.
 *
 * The route files under `app-routes/` are variant-exclusive:
 * `scripts/prepare-session-routes.mjs` links the one matching the build target
 * into `app/(app)/session/`.
 */
function SessionFromQuery() {
  const sessionId = useSearchParams().get("id") ?? "";

  if (!sessionId) {
    return (
      <div className="card text-center">
        <p className="text-sm text-text-secondary">No session selected.</p>
      </div>
    );
  }
  return <SessionView sessionId={sessionId} />;
}

export default function SessionQueryPage() {
  // useSearchParams in a static export must sit under a Suspense boundary or the
  // build refuses to emit the page.
  return (
    <Suspense
      fallback={
        <div className="space-y-4">
          <div className="card h-16 animate-pulse" aria-hidden />
          <div className="card h-64 animate-pulse" aria-hidden />
          <span className="sr-only">Loading session…</span>
        </div>
      }
    >
      <SessionFromQuery />
    </Suspense>
  );
}
