/**
 * Desktop runtime adapter (docs/12 M9, docs/13 §7).
 *
 * `NEXT_PUBLIC_DESKTOP=1` flips the build into the desktop variant: static export,
 * no login, bearer-token API calls to the local sidecar. The flag is inlined at
 * build time, so in the web build every branch here collapses to dead code and the
 * server path is bit-for-bit what it was before.
 *
 * The sidecar handshake (per-launch ephemeral port + bearer token, docs/13 §7) is
 * injected by the Tauri shell at launch — either as a query string on the loaded
 * URL (`?sidecar=http://127.0.0.1:54321&token=…`) or as a `window.__DESKTOP__`
 * global installed before the app scripts run. Either way it is read exactly once,
 * lazily, on first browser-side access; SPA navigations must never lose it.
 */

export const isDesktop = process.env.NEXT_PUBLIC_DESKTOP === "1";

export interface SidecarConfig {
  baseUrl: string;
  token: string;
}

declare global {
  interface Window {
    __DESKTOP__?: Partial<SidecarConfig>;
  }
}

/**
 * Pure resolver, unit-testable without a window. The injected global wins over the
 * query string so a shell can migrate mechanisms without breaking older bundles.
 */
export function resolveSidecar(
  search: string,
  injected?: Partial<SidecarConfig> | null,
): SidecarConfig | null {
  const params = new URLSearchParams(search);
  const baseUrl = injected?.baseUrl ?? params.get("sidecar");
  const token = injected?.token ?? params.get("token");
  if (!baseUrl || !token) return null;
  return { baseUrl: baseUrl.replace(/\/+$/, ""), token };
}

let cached: SidecarConfig | null | undefined;

/** The handshake, memoized. `null` outside the browser or when the shell gave none. */
export function sidecarConfig(): SidecarConfig | null {
  if (!isDesktop) return null;
  if (cached === undefined) {
    cached =
      typeof window === "undefined"
        ? null
        : resolveSidecar(window.location.search, window.__DESKTOP__);
  }
  return cached;
}

/** Test-only: forget the memoized handshake (the web build never needs this). */
export function _resetSidecarCache(): void {
  cached = undefined;
}

/** The API base the rest of the app calls against. */
export function apiBase(): string {
  const cfg = sidecarConfig();
  return cfg ? `${cfg.baseUrl}/api/v1` : "/api/v1";
}

/** Bearer auth in desktop mode; the web build authenticates with httpOnly cookies. */
export function authHeaders(): Record<string, string> {
  const cfg = sidecarConfig();
  return cfg ? { Authorization: `Bearer ${cfg.token}` } : {};
}

/**
 * SSE URL for native EventSource, which cannot set headers — the token travels as
 * `?access_token=`, the one concession the sidecar's token middleware makes
 * (docs/13 §7). `path` already includes the `/api/v1` prefix.
 */
export function streamUrl(path: string): string {
  const cfg = sidecarConfig();
  if (!cfg) return path;
  const sep = path.includes("?") ? "&" : "?";
  return `${cfg.baseUrl}${path}${sep}access_token=${encodeURIComponent(cfg.token)}`;
}

/**
 * Session links. The web build keeps its dynamic `/session/[sessionId]` route; the
 * static export cannot resolve a dynamic segment it never generated, so the desktop
 * build routes through the static `/session?id=` page instead.
 */
export function sessionHref(sessionId: string): string {
  return isDesktop ? `/session?id=${sessionId}` : `/session/${sessionId}`;
}
