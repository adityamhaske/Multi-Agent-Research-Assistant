import type { NextConfig } from "next";

// Same-origin API proxy (docs/02 §1, docs/06 §6): the browser calls /api/* on the
// frontend origin, and Next forwards to the backend. This keeps auth cookies
// first-party and lets native EventSource authenticate — no CORS, no tokens in JS.
const BACKEND_ORIGIN = process.env.BACKEND_ORIGIN || "http://localhost:8000";
const isDev = process.env.NODE_ENV !== "production";

// Desktop variant (docs/13 §7): NEXT_PUBLIC_DESKTOP=1 builds a static export the
// Tauri shell serves from disk. No server means no rewrites, no response headers —
// the sidecar base URL comes from the shell handshake, and the shell's own security
// config (CSP, loopback-only) governs the WebView.
const isDesktop = process.env.NEXT_PUBLIC_DESKTOP === "1";

// `unsafe-eval` is DEV-ONLY: React's dev error overlay reconstructs callstacks with
// eval(); production never uses it, and the prod CSP stays strict (docs/06 §6).
const scriptSrc = isDev
  ? "script-src 'self' 'unsafe-inline' 'unsafe-eval'"
  : "script-src 'self' 'unsafe-inline'";

const securityHeaders = [
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "Referrer-Policy", value: "no-referrer" },
  { key: "Permissions-Policy", value: "geolocation=(), microphone=(), camera=()" },
  {
    key: "Content-Security-Policy",
    value: [
      "default-src 'self'",
      // Next injects small inline bootstrap scripts/styles.
      scriptSrc,
      "style-src 'self' 'unsafe-inline'",
      "img-src 'self' data:",
      "font-src 'self' data:",
      "connect-src 'self'",
      "frame-ancestors 'none'",
      "base-uri 'none'",
      "form-action 'self'",
    ].join("; "),
  },
];

const nextConfig: NextConfig = isDesktop
  ? {
      output: "export",
      // Trailing slashes make every route a real /route/index.html on disk, which
      // is what the shell's static file handler wants.
      trailingSlash: true,
      // No image optimization server exists in a static export.
      images: { unoptimized: true },
    }
  : {
      // Self-contained server bundle for the Docker image (docs/09 §1).
      output: "standalone",
      async rewrites() {
        return [{ source: "/api/:path*", destination: `${BACKEND_ORIGIN}/api/:path*` }];
      },
      async headers() {
        return [{ source: "/:path*", headers: securityHeaders }];
      },
    };

export default nextConfig;
