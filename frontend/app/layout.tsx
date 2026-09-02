import type { Metadata } from "next";

import { basePath, isPagesBuild, siteUrl } from "@/lib/pages-build";
import { Inter, JetBrains_Mono } from "next/font/google";

import { Providers } from "@/components/Providers";
import "./globals.css";

// Self-hosted via next/font — no render-blocking external CSS import (docs/03, docs/07 §1).
const inter = Inter({
  subsets: ["latin"],
  variable: "--font-inter",
  display: "swap",
});

const jetbrainsMono = JetBrains_Mono({
  subsets: ["latin"],
  variable: "--font-jetbrains-mono",
  display: "swap",
});

export const metadata: Metadata = {
  // `siteUrl` always resolves to a valid absolute URL (it has a non-Pages-build fallback —
  // see `lib/pages-build.ts`), even though only the Pages build's value is meaningful. Next
  // requires *some* `metadataBase` to resolve the auto-generated `opengraph-image` route
  // into an absolute URL and otherwise falls back to `http://localhost:3000` with a build
  // warning on every target; a slightly-wrong base on the two targets nothing crawls (see
  // `robots.ts`) is a smaller cost than that warning on every build.
  metadataBase: new URL(siteUrl),
  title: {
    default: "Research Assistant — cited research you can actually verify",
    // Applied to every page's own `title` string; a page that wants the bare default
    // (the homepage) omits `title` entirely rather than repeating it; see `page.tsx`.
    template: "%s · Research Assistant",
  },
  description:
    "A multi-agent research pipeline: plan, gather cited evidence, critique, and synthesize a reviewable report.",
  // Prefixed with `basePath`, which is empty in the server and desktop builds and
  // `/<repo>` on GitHub Pages. Next does not apply basePath to these metadata paths, so
  // the published site emitted `href="/icon.svg"` and the browser resolved it against the
  // domain root — one level above where Pages actually serves the file. The icon was
  // there and returning 200 at its real URL the whole time; nothing was linking to it.
  icons: {
    icon: `${basePath}/icon.svg`,
    shortcut: `${basePath}/icon.svg`,
    apple: `${basePath}/icon.svg`,
  },
  // Structural defaults only — no `title`/`description` here. Those two are left for each
  // page's own `title`/`description` to fill via Next's per-route fallback (`pageUrls` in
  // `lib/pages-build.ts` explains why setting them here would break that). `siteName`,
  // `type` and `card` merge down to every page that does not redefine `openGraph`/`twitter`
  // itself, which is every page in this app.
  openGraph: {
    type: "website",
    siteName: "Multi-Agent Research Assistant",
    locale: "en_US",
  },
  twitter: {
    card: "summary_large_image",
  },
  // Belt-and-suspenders alongside `robots.ts`: a `<meta name="robots">` tag survives even
  // if a reverse proxy in front of a self-hosted deployment ever drops or rewrites
  // `/robots.txt`. Only the Pages build is meant to be found by a search engine at all.
  robots: isPagesBuild
    ? { index: true, follow: true }
    : { index: false, follow: false },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html
      lang="en"
      className={`${inter.variable} ${jetbrainsMono.variable}`}
      suppressHydrationWarning
    >
      <body className="min-h-screen bg-bg-base text-text-primary antialiased">
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
