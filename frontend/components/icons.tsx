/**
 * The shared icon vocabulary (docs/07 §2): 24×24 viewBox, 1.75 stroke, square
 * caps and miter joins — no rounded strokes, matching the square identity
 * (`--radius: 0` in globals.css). One file so nav, the activity feed and any
 * future surface draw from the same set instead of re-inventing glyphs per
 * component. Lifted out of `SideNav.tsx`, which held the only copies before
 * this file existed.
 */

type IconProps = { className?: string };

export function BrandLogo({ className }: IconProps) {
  return (
    <div
      className={`flex items-center justify-center bg-accent text-accent-contrast border border-accent ${
        className || "h-7 w-7"
      }`}
    >
      <svg
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2.2"
        strokeLinecap="square"
        strokeLinejoin="miter"
        className="h-4 w-4"
      >
        <polygon points="12 2 22 8.5 22 15.5 12 22 2 15.5 2 8.5 12 2" />
        <line x1="12" y1="22" x2="12" y2="15.5" />
        <polyline points="22 8.5 12 15.5 2 8.5" />
      </svg>
    </div>
  );
}

export function IconDashboard({ className }: IconProps) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.75"
      strokeLinecap="square"
      strokeLinejoin="miter"
      className={className || "h-5 w-5"}
    >
      <rect width="7" height="9" x="3" y="3" />
      <rect width="7" height="5" x="14" y="3" />
      <rect width="7" height="9" x="14" y="12" />
      <rect width="7" height="5" x="3" y="16" />
    </svg>
  );
}

export function IconCorpus({ className }: IconProps) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.75"
      strokeLinecap="square"
      strokeLinejoin="miter"
      className={className || "h-5 w-5"}
    >
      <path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1-2.5-2.5Z" />
      <path d="M6 6h10" />
      <path d="M6 10h10" />
      <path d="M6 14h6" />
    </svg>
  );
}

/** The project workspace: four panes of one thing (docs/07 §2, Phase 6). */
export function IconOverview({ className }: IconProps) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.75"
      strokeLinecap="square"
      strokeLinejoin="miter"
      className={className || "h-5 w-5"}
    >
      <path d="M3 3h8v6H3z" />
      <path d="M13 3h8v10h-8z" />
      <path d="M3 11h8v10H3z" />
      <path d="M13 15h8v6h-8z" />
    </svg>
  );
}

export function IconHistory({ className }: IconProps) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.75"
      strokeLinecap="square"
      strokeLinejoin="miter"
      className={className || "h-5 w-5"}
    >
      <path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8" />
      <path d="M3 3v5h5" />
      <path d="M12 7v5l4 2" />
    </svg>
  );
}

export function IconChat({ className }: IconProps) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.75"
      strokeLinecap="square"
      strokeLinejoin="miter"
      className={className || "h-5 w-5"}
    >
      <path d="M7.9 20A9 9 0 1 0 4 16.1L2 22Z" />
      <path d="M8 12h.01" />
      <path d="M12 12h.01" />
      <path d="M16 12h.01" />
    </svg>
  );
}

export function IconPlus({ className }: IconProps) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="square"
      strokeLinejoin="miter"
      className={className || "h-4 w-4"}
    >
      <line x1="12" y1="5" x2="12" y2="19" />
      <line x1="5" y1="12" x2="19" y2="12" />
    </svg>
  );
}

export function IconCollapse({ className, collapsed }: IconProps & { collapsed: boolean }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.75"
      strokeLinecap="square"
      strokeLinejoin="miter"
      className={className || "h-4 w-4"}
    >
      <rect width="18" height="18" x="3" y="3" />
      <path d="M9 3v18" />
      {collapsed ? <path d="m14 15 3-3-3-3" /> : <path d="m16 15-3-3 3-3" />}
    </svg>
  );
}

export function IconMenu({ className }: IconProps) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.75"
      strokeLinecap="square"
      strokeLinejoin="miter"
      className={className || "h-6 w-6"}
    >
      <line x1="4" x2="20" y1="12" y2="12" />
      <line x1="4" x2="20" y1="6" y2="6" />
      <line x1="4" x2="20" y1="18" y2="18" />
    </svg>
  );
}

export function IconClose({ className }: IconProps) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.75"
      strokeLinecap="square"
      strokeLinejoin="miter"
      className={className || "h-5 w-5"}
    >
      <path d="M18 6 6 18" />
      <path d="m6 6 12 12" />
    </svg>
  );
}

/* ─── Added for LiveFeed's detail blocks (docs/07 §2) ──────────────────────
 * These replace the 9 emoji section headers with the same stroke vocabulary
 * as the nav icons above, so the activity feed stops being the one place in
 * the app that draws from a different (emoji) icon set. */

export function IconThought({ className }: IconProps) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.75"
      strokeLinecap="square"
      strokeLinejoin="miter"
      className={className || "h-3.5 w-3.5"}
    >
      <path d="M12 3a6 6 0 0 0-3.7 10.7c.6.5 1.2 1.3 1.2 2.3h5a3 3 0 0 1 1.2-2.3A6 6 0 0 0 12 3Z" />
      <path d="M9 18h6" />
      <path d="M10 21h4" />
    </svg>
  );
}

export function IconTarget({ className }: IconProps) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.75"
      strokeLinecap="square"
      strokeLinejoin="miter"
      className={className || "h-3.5 w-3.5"}
    >
      <circle cx="12" cy="12" r="8" />
      <circle cx="12" cy="12" r="4" />
      <circle cx="12" cy="12" r="0.75" fill="currentColor" stroke="none" />
    </svg>
  );
}

export function IconSearch({ className }: IconProps) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.75"
      strokeLinecap="square"
      strokeLinejoin="miter"
      className={className || "h-3.5 w-3.5"}
    >
      <circle cx="10.5" cy="10.5" r="6.5" />
      <line x1="20" y1="20" x2="15.8" y2="15.8" />
    </svg>
  );
}

export function IconList({ className }: IconProps) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.75"
      strokeLinecap="square"
      strokeLinejoin="miter"
      className={className || "h-3.5 w-3.5"}
    >
      <rect x="4" y="3" width="16" height="18" />
      <line x1="7.5" y1="8" x2="16.5" y2="8" />
      <line x1="7.5" y1="12" x2="16.5" y2="12" />
      <line x1="7.5" y1="16" x2="13" y2="16" />
    </svg>
  );
}

export function IconBookOpen({ className }: IconProps) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.75"
      strokeLinecap="square"
      strokeLinejoin="miter"
      className={className || "h-3.5 w-3.5"}
    >
      <path d="M3 5.5S5 4 8.5 4 12 5.5 12 5.5v14S10 18 8.5 18 3 19.5 3 19.5v-14Z" />
      <path d="M21 5.5S19 4 15.5 4 12 5.5 12 5.5v14S14 18 15.5 18 21 19.5 21 19.5v-14Z" />
    </svg>
  );
}

export function IconGlobe({ className }: IconProps) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.75"
      strokeLinecap="square"
      strokeLinejoin="miter"
      className={className || "h-3.5 w-3.5"}
    >
      <circle cx="12" cy="12" r="9" />
      <path d="M3 12h18" />
      <path d="M12 3a15 15 0 0 1 0 18 15 15 0 0 1 0-18Z" />
    </svg>
  );
}

export function IconFileText({ className }: IconProps) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.75"
      strokeLinecap="square"
      strokeLinejoin="miter"
      className={className || "h-3.5 w-3.5"}
    >
      <path d="M6 2h9l4 4v16H6Z" />
      <path d="M14 2v5h5" />
      <line x1="9" y1="13" x2="16" y2="13" />
      <line x1="9" y1="17" x2="16" y2="17" />
    </svg>
  );
}

export function IconLibrary({ className }: IconProps) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.75"
      strokeLinecap="square"
      strokeLinejoin="miter"
      className={className || "h-3.5 w-3.5"}
    >
      <rect x="3" y="4" width="4.5" height="17" />
      <rect x="9.75" y="7" width="4.5" height="14" />
      <rect x="16.5" y="2" width="4.5" height="19" />
    </svg>
  );
}

export function IconScale({ className }: IconProps) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.75"
      strokeLinecap="square"
      strokeLinejoin="miter"
      className={className || "h-3.5 w-3.5"}
    >
      <line x1="12" y1="3" x2="12" y2="21" />
      <line x1="5" y1="7" x2="19" y2="7" />
      <line x1="8" y1="21" x2="16" y2="21" />
      <path d="M5 7 2 14h6L5 7Z" />
      <path d="M19 7 16 14h6L19 7Z" />
    </svg>
  );
}

export function IconWarningTriangle({ className }: IconProps) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.75"
      strokeLinecap="square"
      strokeLinejoin="miter"
      className={className || "h-3.5 w-3.5"}
    >
      <path d="M12 3 22 20H2Z" />
      <line x1="12" y1="9" x2="12" y2="14" />
      <line x1="12" y1="17" x2="12" y2="17.01" />
    </svg>
  );
}

export function IconEdit({ className }: IconProps) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.75"
      strokeLinecap="square"
      strokeLinejoin="miter"
      className={className || "h-3.5 w-3.5"}
    >
      <path d="M3 21v-4.25L16.5 3.25a1.5 1.5 0 0 1 2.12 0l2.13 2.13a1.5 1.5 0 0 1 0 2.12L7.25 21H3Z" />
      <path d="M15 5 19 9" />
    </svg>
  );
}
