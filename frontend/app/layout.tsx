import type { Metadata } from "next";

import { basePath } from "@/lib/pages-build";
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
  title: "Research Assistant",
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
