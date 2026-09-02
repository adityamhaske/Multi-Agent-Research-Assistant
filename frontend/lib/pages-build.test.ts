import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

/**
 * `siteUrl`/`absoluteUrl`/`pageUrls` are read at module load from `NEXT_PUBLIC_PAGES`,
 * `NEXT_PUBLIC_BASE_PATH` and `NEXT_PUBLIC_SITE_URL` — the same env vars
 * `.github/workflows/pages.yml` sets for the real build — so every test reloads the module
 * fresh after stubbing them, the same pattern `lib/docs.test.ts` uses for `DOCS_DIR`. Empty
 * string is this suite's "unset", matching that file too: `siteUrl`'s own `||` fallback (as
 * opposed to `basePath`'s `??`) treats an empty `NEXT_PUBLIC_SITE_URL` the same way.
 */
async function loadModule() {
  vi.resetModules();
  return import("@/lib/pages-build");
}

beforeEach(() => {
  vi.stubEnv("NEXT_PUBLIC_PAGES", "");
  vi.stubEnv("NEXT_PUBLIC_BASE_PATH", "");
  vi.stubEnv("NEXT_PUBLIC_SITE_URL", "");
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.resetModules();
});

describe("siteUrl", () => {
  it("falls back to the production origin plus basePath with no workflow env set", async () => {
    vi.stubEnv("NEXT_PUBLIC_BASE_PATH", "/Multi-Agent-Research-Assistant");
    const { siteUrl } = await loadModule();
    expect(siteUrl).toBe("https://adityamhaske.github.io/Multi-Agent-Research-Assistant");
  });

  it("prefers NEXT_PUBLIC_SITE_URL when the workflow sets one", async () => {
    vi.stubEnv("NEXT_PUBLIC_SITE_URL", "https://example.com");
    const { siteUrl } = await loadModule();
    expect(siteUrl).toBe("https://example.com");
  });
});

describe("absoluteUrl", () => {
  it("is undefined outside the Pages build — no known public origin to build from", async () => {
    const { absoluteUrl } = await loadModule();
    expect(absoluteUrl("/why")).toBeUndefined();
  });

  it("builds a trailing-slashed absolute URL under the resolved site origin", async () => {
    vi.stubEnv("NEXT_PUBLIC_PAGES", "1");
    vi.stubEnv("NEXT_PUBLIC_SITE_URL", "https://example.com/repo");
    const { absoluteUrl } = await loadModule();
    expect(absoluteUrl("/why")).toBe("https://example.com/repo/why/");
    expect(absoluteUrl("docs/getting-started/overview")).toBe(
      "https://example.com/repo/docs/getting-started/overview/",
    );
  });

  it("does not add a trailing slash to the root", async () => {
    vi.stubEnv("NEXT_PUBLIC_PAGES", "1");
    vi.stubEnv("NEXT_PUBLIC_SITE_URL", "https://example.com/repo");
    const { absoluteUrl } = await loadModule();
    expect(absoluteUrl("/")).toBe("https://example.com/repo/");
  });
});

describe("pageUrls", () => {
  it("sets alternates.canonical and openGraph.url to the same URL", async () => {
    vi.stubEnv("NEXT_PUBLIC_PAGES", "1");
    vi.stubEnv("NEXT_PUBLIC_SITE_URL", "https://example.com/repo");
    const { pageUrls } = await loadModule();
    const result = pageUrls("/download");
    expect(result.alternates?.canonical).toBe("https://example.com/repo/download/");
    expect(result.openGraph).toMatchObject({ url: "https://example.com/repo/download/" });
  });

  it("never sets openGraph.title or openGraph.description", async () => {
    // Setting either here would freeze one page's title into every other page's Open
    // Graph tags once Next merges metadata objects shallowly — see the comment on
    // `pageUrls` in pages-build.ts for why that fallback depends on the key staying unset.
    vi.stubEnv("NEXT_PUBLIC_PAGES", "1");
    vi.stubEnv("NEXT_PUBLIC_SITE_URL", "https://example.com/repo");
    const { pageUrls } = await loadModule();
    const result = pageUrls("/download");
    expect(result.openGraph).not.toHaveProperty("title");
    expect(result.openGraph).not.toHaveProperty("description");
  });

  it("is an empty object outside the Pages build, not a wrong URL", async () => {
    const { pageUrls } = await loadModule();
    expect(pageUrls("/download")).toEqual({});
  });
});
