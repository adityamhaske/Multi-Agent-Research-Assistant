"use client";

import { useState } from "react";

import type { User } from "@/lib/types";

/** Initials from a display name ("Ada Lovelace" → "AL") or email ("ada@x.io" → "A"). */
export function initialsFor(user: Pick<User, "display_name" | "email">): string {
  const name = (user.display_name ?? "").trim();
  if (name) {
    const parts = name.split(/\s+/).filter(Boolean);
    const letters = parts.length > 1 ? `${parts[0][0]}${parts[parts.length - 1][0]}` : parts[0][0];
    return letters.toUpperCase();
  }
  return (user.email?.[0] ?? "?").toUpperCase();
}

/**
 * User avatar: the uploaded image when there is one, otherwise derived initials.
 * A broken image URL falls back to initials rather than rendering a broken icon,
 * so the profile always looks complete.
 */
export function Avatar({
  user,
  size = 36,
  className = "",
}: {
  user: Pick<User, "display_name" | "email" | "avatar_url">;
  size?: number;
  className?: string;
}) {
  const [failed, setFailed] = useState(false);
  const showImage = Boolean(user.avatar_url) && !failed;
  const dimension = { width: size, height: size };

  if (showImage) {
    // Avatars are arbitrary user-supplied remote URLs; next/image would require
    // per-host remotePatterns config, which we can't know ahead of time.
    return (
      // eslint-disable-next-line @next/next/no-img-element
      <img
        src={user.avatar_url as string}
        alt=""
        onError={() => setFailed(true)}
        style={dimension}
        className={`shrink-0 object-cover border border-border ${className}`}
      />
    );
  }

  return (
    <span
      aria-hidden
      style={{ ...dimension, fontSize: Math.max(11, size * 0.4) }}
      className={`flex shrink-0 select-none items-center justify-center border border-border bg-accent-muted font-mono font-semibold text-accent ${className}`}
    >
      {initialsFor(user)}
    </span>
  );
}
