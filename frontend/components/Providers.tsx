"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ThemeProvider } from "next-themes";
import { useState } from "react";
import { Toaster } from "react-hot-toast";

/**
 * App-wide client providers (docs/03: TanStack Query owns all server state;
 * next-themes owns the class-based theme; react-hot-toast replaces hand-rolled
 * toast state). Mounted once from the root layout.
 *
 * Nothing here may fetch: the public site (app/(site)/) renders inside these too, and on
 * GitHub Pages there is no API behind it. The active project is a query, so its provider
 * lives in the (app) layout instead.
 */
export function Providers({ children }: { children: React.ReactNode }) {
  // One QueryClient per browser session — created lazily so it survives re-renders
  // but is never shared across requests on the server.
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 30_000,
            retry: 1,
            refetchOnWindowFocus: false,
          },
        },
      }),
  );

  return (
    <QueryClientProvider client={queryClient}>
      {/* Light is the product default (docs/07 "Theming"); enableSystem=false so a
          dark-OS user still lands on the intended default until they toggle. */}
      <ThemeProvider attribute="class" defaultTheme="light" enableSystem={false}>
        {children}
        <Toaster
          position="bottom-right"
          toastOptions={{
            style: {
              background: "var(--bg-elevated)",
              color: "var(--text-primary)",
              border: "1px solid var(--border)",
              fontSize: "0.875rem",
            },
            success: { iconTheme: { primary: "var(--success)", secondary: "var(--bg-elevated)" } },
            error: { iconTheme: { primary: "var(--danger)", secondary: "var(--bg-elevated)" } },
          }}
        />
      </ThemeProvider>
    </QueryClientProvider>
  );
}
