import { ApiError } from "./api";
import { apiBase, authHeaders, isDesktop } from "./desktop";

/**
 * Fetch an export and hand it to the browser as a file.
 *
 * A plain `<a href="…/bundle.json">` works on the web host, where the httpOnly cookie
 * rides along with the navigation — and does not work on the desktop host at all, where
 * the sidecar authenticates with a per-launch bearer token that a link cannot carry. The
 * three V2 export controls were plain links, so on the desktop build every one of them
 * was a button that produced a 401 page (AGENTS.md, "two hosts, one contract": the desktop
 * copy is the one that gets forgotten).
 *
 * Going through `fetch` also buys the thing a link cannot give: a failure that can be
 * *reported*. A 501 from a deployment without the PDF libraries used to navigate the tab
 * away to a JSON error body.
 *
 * The anchor is still an anchor at the call site — it keeps the href, so middle-click and
 * "copy link" behave, and the keyboard and screen-reader semantics stay those of a link to
 * a file. This only intercepts the plain click.
 */
export async function downloadExport(path: string, filename: string): Promise<void> {
  const res = await fetch(`${apiBase()}${path}`, {
    credentials: isDesktop ? "omit" : "include",
    cache: "no-store",
    headers: authHeaders(),
  });

  if (!res.ok) {
    let detail = res.statusText || `Export failed (${res.status})`;
    try {
      const body = (await res.clone().json()) as { detail?: unknown };
      if (typeof body?.detail === "string") detail = body.detail;
    } catch {
      /* not JSON — keep the status text */
    }
    throw new ApiError(res.status, detail);
  }

  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}
