import type { Metadata } from "next";

import { pageUrls } from "@/lib/pages-build";

/**
 * Metadata host for `/download`.
 *
 * `page.tsx` is a client component (`useSyncExternalStore` to detect the visitor's OS), and
 * a file cannot both declare `"use client"` and export `metadata` — Next's metadata export
 * is resolved server-side before any client rendering happens. This layout is the smallest
 * fix: a server component that contributes nothing but the `metadata` the page itself
 * cannot, the same split `docs/layout.tsx` already uses for a different reason.
 */
export const metadata: Metadata = {
  // The root layout's `title.template` appends " · Research Assistant" — see app/layout.tsx.
  title: "Download",
  description:
    "Get the Multi-Agent Research Assistant desktop app for macOS, Windows or Linux — " +
    "or run the full stack yourself with Docker.",
  ...pageUrls("/download"),
};

export default function DownloadLayout({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
