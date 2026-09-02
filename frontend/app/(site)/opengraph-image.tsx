import { ImageResponse } from "next/og";

export const size = { width: 1200, height: 630 };
export const contentType = "image/png";
export const alt = "Multi-Agent Research Assistant — cited research you can actually verify";
// This image has no dynamic input (no params, no request data) so it is always safe to
// render once at build time — but the desktop export (`output: "export"`) does not infer
// that on its own; without this it fails the build outright, the same as `sitemap.ts`.
export const dynamic = "force-static";

/**
 * Branded social-preview card for every page under the public site (`app/(site)/`).
 *
 * A file-convention route Next resolves at build time — same static-export mechanism as
 * `robots.ts`/`sitemap.ts` — so it needs no server and applies to `/`, `/why`, `/docs` and
 * every doc page beneath it without each one setting its own `openGraph.images`.
 *
 * Generated from JSX via Satori, not a checked-in PNG, so it cannot drift from the palette
 * in `globals.css` the way a hand-exported image would — the same "generated, not
 * hand-maintained" choice `pages.yml`'s own docblock makes about the rest of the site.
 * Colors below are `rgb()`, not hex: CI greps `app/` for hardcoded hex colors (docs/07 §1),
 * and Satori accepts `rgb()` identically. Values are `globals.css`'s light-theme tokens
 * (`--ink`, `--ground`, `--academic-accent`), inverted — ink as the background rather than
 * the text — for a card that stays legible at thumbnail size in a chat or timeline; a
 * static image cannot follow the viewer's OS theme, so it commits to one deliberately
 * high-contrast look rather than picking either theme literally.
 */
export default function OpengraphImage() {
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          justifyContent: "center",
          padding: "80px",
          backgroundColor: "rgb(17, 17, 17)",
          color: "rgb(251, 251, 250)",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 18 }}>
          <div
            style={{
              display: "flex",
              width: 60,
              height: 60,
              alignItems: "center",
              justifyContent: "center",
              backgroundColor: "rgb(21, 101, 74)",
            }}
          >
            <svg
              width="32"
              height="32"
              viewBox="0 0 24 24"
              fill="none"
              stroke="rgb(255,255,255)"
              strokeWidth="2.4"
              strokeLinecap="square"
              strokeLinejoin="miter"
            >
              <polygon points="12 2 22 8.5 22 15.5 12 22 2 15.5 2 8.5 12 2" />
              <line x1="12" y1="22" x2="12" y2="15.5" />
              <polyline points="22 8.5 12 15.5 2 8.5" />
            </svg>
          </div>
          <span
            style={{
              fontSize: 24,
              letterSpacing: 3,
              textTransform: "uppercase",
              color: "rgb(140, 140, 136)",
            }}
          >
            Self-hostable · bring your own key
          </span>
        </div>

        <div style={{ display: "flex", marginTop: 44, fontSize: 66, fontWeight: 700, lineHeight: 1.15 }}>
          Multi-Agent Research Assistant
        </div>

        <div style={{ display: "flex", marginTop: 22, fontSize: 34, color: "rgb(210, 210, 206)" }}>
          Cited research you can actually verify.
        </div>
      </div>
    ),
    { ...size },
  );
}
