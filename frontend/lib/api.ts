/**
 * Same-origin API client (docs/02 §1, docs/06 §6).
 *
 * The browser always calls `/api/v1/*` on the frontend origin; Next's `rewrites`
 * proxy forwards to the backend, keeping the httpOnly auth cookies first-party.
 * There are NO tokens in JS and NO hardcoded backend URL here — that is the whole
 * point of the proxy.
 *
 * On a 401 the client transparently attempts a single refresh (rotating cookie)
 * and replays the request once. Concurrent 401s share one in-flight refresh.
 */

const API_BASE = "/api/v1";

// Endpoints whose own 401 must NOT trigger a refresh (would loop or is meaningful).
const NO_REFRESH = new Set(["/auth/refresh", "/auth/login", "/auth/register", "/auth/logout"]);

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

let refreshInFlight: Promise<boolean> | null = null;

function refreshSession(): Promise<boolean> {
  if (!refreshInFlight) {
    refreshInFlight = fetch(`${API_BASE}/auth/refresh`, {
      method: "POST",
      credentials: "include",
    })
      .then((r) => r.ok)
      .catch(() => false)
      .finally(() => {
        refreshInFlight = null;
      });
  }
  return refreshInFlight;
}

async function extractDetail(res: Response): Promise<string> {
  try {
    const data = await res.clone().json();
    const detail = (data as { detail?: unknown })?.detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
      // FastAPI validation error array.
      return detail
        .map((d) => (typeof d === "object" && d && "msg" in d ? String((d as { msg: unknown }).msg) : String(d)))
        .join("; ");
    }
  } catch {
    /* not JSON */
  }
  return res.statusText || `Request failed (${res.status})`;
}

export interface ApiOptions extends Omit<RequestInit, "body"> {
  body?: unknown;
  /** Skip the automatic refresh-and-retry on 401. */
  skipRefresh?: boolean;
}

export async function apiFetch<T>(path: string, opts: ApiOptions = {}): Promise<T> {
  const { skipRefresh, body, headers, ...rest } = opts;

  const send = () =>
    fetch(`${API_BASE}${path}`, {
      credentials: "include",
      // Never serve a poll from the HTTP cache — status transitions must be seen.
      cache: "no-store",
      headers: {
        ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
        ...headers,
      },
      ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
      ...rest,
    });

  let res = await send();

  if (res.status === 401 && !skipRefresh && !NO_REFRESH.has(path)) {
    const refreshed = await refreshSession();
    if (refreshed) res = await send();
  }

  if (!res.ok) {
    throw new ApiError(res.status, await extractDetail(res));
  }

  if (res.status === 204) return undefined as T;
  const contentType = res.headers.get("content-type") ?? "";
  if (contentType.includes("application/json")) return (await res.json()) as T;
  return (await res.text()) as unknown as T;
}
