"use client";

import Link from "next/link";

/**
 * Says that a session ignored its owner's custom agent instructions (scope freeze §8).
 *
 * Sessions run on the earlier pipeline, which does not apply prompt overrides and is not
 * gaining them. The session records when it ignored some, and this is the reader of that
 * record: §8's invariant is that there must never be a silent prompt-override no-op, and a
 * flag nobody renders is still silent to the person it is for.
 *
 * The flag is the session's own, set when it started, never recomputed from current
 * settings — so it describes what this session did, whatever the user has saved since.
 */
export function OverridesNotAppliedNotice({ notApplied }: { notApplied: boolean | undefined }) {
  if (!notApplied) return null;
  return (
    <div
      role="note"
      className="border px-4 py-3"
      style={{ borderColor: "var(--warning-line)", backgroundColor: "var(--warning-soft)" }}
    >
      <p
        className="font-mono text-xs font-semibold uppercase tracking-wider"
        style={{ color: "var(--warning)" }}
      >
        Custom instructions not applied
      </p>
      <p className="mt-1 text-sm leading-relaxed text-text-secondary">
        You had custom agent instructions set when this session started, but sessions run on
        the earlier research pipeline, which does not use them — this report was written with
        the shipped prompts. Research you start now applies them. Manage them in{" "}
        <Link href="/settings/agents" className="text-accent hover:underline">
          Settings → Agents
        </Link>
        .
      </p>
    </div>
  );
}
