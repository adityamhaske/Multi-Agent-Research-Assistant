import { describe, expect, it } from "vitest";

// The web test run builds without NEXT_PUBLIC_DESKTOP, so isDesktop is false here;
// the pure resolver is the part that carries the real logic (docs/13 §7).
import { apiHref, resolveSidecar, sessionHref, streamUrl } from "./desktop";

describe("resolveSidecar", () => {
  it("parses the handshake from the launch query string", () => {
    const cfg = resolveSidecar("?sidecar=http://127.0.0.1:54321&token=t-123");
    expect(cfg).toEqual({ baseUrl: "http://127.0.0.1:54321", token: "t-123" });
  });

  it("strips trailing slashes from the base URL", () => {
    const cfg = resolveSidecar("?sidecar=http://127.0.0.1:54321///&token=t");
    expect(cfg?.baseUrl).toBe("http://127.0.0.1:54321");
  });

  it("prefers the injected window.__DESKTOP__ global over the query string", () => {
    const cfg = resolveSidecar("?sidecar=http://stale:1&token=old", {
      baseUrl: "http://127.0.0.1:9",
      token: "fresh",
    });
    expect(cfg).toEqual({ baseUrl: "http://127.0.0.1:9", token: "fresh" });
  });

  it("falls back per-field when the injected global is partial", () => {
    const cfg = resolveSidecar("?token=from-query", { baseUrl: "http://127.0.0.1:9" });
    expect(cfg).toEqual({ baseUrl: "http://127.0.0.1:9", token: "from-query" });
  });

  it("returns null when either half of the handshake is missing", () => {
    expect(resolveSidecar("?sidecar=http://127.0.0.1:9")).toBeNull();
    expect(resolveSidecar("?token=t")).toBeNull();
    expect(resolveSidecar("")).toBeNull();
  });
});

describe("web-build defaults", () => {
  it("sessionHref keeps the dynamic route in the web build", () => {
    expect(sessionHref("abc-123")).toBe("/session/abc-123");
  });

  it("streamUrl passes through untouched without a sidecar handshake", () => {
    expect(streamUrl("/api/v1/sessions/1/stream")).toBe("/api/v1/sessions/1/stream");
  });
});

describe("apiHref", () => {
  it("passes this app's own API addresses", () => {
    expect(apiHref("/api/v1/runs/abc/cited-documents/d%201/download")).toBe(
      "/api/v1/runs/abc/cited-documents/d%201/download",
    );
    expect(apiHref("http://127.0.0.1:58583/api/v1/projects/p/corpus/documents/d/download")).toBe(
      "http://127.0.0.1:58583/api/v1/projects/p/corpus/documents/d/download",
    );
  });

  it("refuses anything a route parameter could turn it into", () => {
    for (const url of [
      "javascript:alert(1)",
      "https://evil.example/api/v1/x",
      "//evil.example/api/v1/x",
      "/api/v1/x\"><script>",
      "http://127.0.0.1.evil.example/api/v1/x",
      "/runs/abc/download",
    ]) {
      expect(apiHref(url)).toBeUndefined();
    }
  });
});
