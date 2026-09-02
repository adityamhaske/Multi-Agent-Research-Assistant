import fs from "node:fs";
import os from "node:os";
import path from "node:path";

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

/**
 * The docs publication boundary (M0B).
 *
 * The site walks `docs/` at build time and generates a route for **every** Markdown file
 * it finds. A directory's absence from `CATEGORY_ORDER` hides it from the sidebar and the
 * index but does not stop `generateStaticParams` — so anything filed under a governance
 * directory was published at a URL nothing linked to.
 *
 * The old guard was a denylist of two exact file paths. It held only for as long as those
 * the named files were the only ones there: adding a third document to a withheld directory published
 * it, silently, with no failing check anywhere. A planning audit had to be filed outside
 * `docs/` because of this.
 *
 * These tests are the regression guard. They exercise the real `walk()` against fixture
 * trees rather than testing the classifier alone, because the classifier was never the
 * broken part — the wiring was.
 */

let tmpRoot: string | null = null;

/** Build a throwaway docs tree and point the module at it via `DOCS_DIR`. */
function makeDocsTree(files: Record<string, string>): string {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "docs-boundary-"));
  for (const [rel, body] of Object.entries(files)) {
    const abs = path.join(root, rel);
    fs.mkdirSync(path.dirname(abs), { recursive: true });
    fs.writeFileSync(abs, body, "utf8");
  }
  tmpRoot = root;
  return root;
}

/** A fresh copy of the module, reading whatever `DOCS_DIR` currently points at.
 *
 *  `allDocs()` memoises into a module-level `cached`, and `CANDIDATE_ROOTS` reads the env
 *  var at module load — so a fixture swap needs the module graph reset, not just the env. */
async function loadDocsModule() {
  vi.resetModules();
  return import("@/lib/docs");
}

beforeEach(() => {
  vi.stubEnv("DOCS_DIR", "");
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.resetModules();
  if (tmpRoot) {
    fs.rmSync(tmpRoot, { recursive: true, force: true });
    tmpRoot = null;
  }
});

// ── The classifier ────────────────────────────────────────────────────────────────

describe("classifyDir", () => {
  it("publishes the documentation categories", async () => {
    const { classifyDir } = await loadDocsModule();
    for (const dir of [
      "getting-started",
      "user-guide",
      "architecture",
      "deployment",
      "developers",
      "reference",
      "research",
      "project",
    ]) {
      expect(classifyDir(dir)).toBe("publish");
    }
  });

  it("withholds governance", async () => {
    const { classifyDir } = await loadDocsModule();
    expect(classifyDir("governance")).toBe("withhold");
  });

  it("refuses a planning directory rather than remembering one that was deleted", async () => {
    // `plans/` was withheld while it existed and is not withheld now that it does not.
    // A leftover entry would publish nothing today and quietly wave through whatever a
    // future contributor filed under that name; an unclassified directory stops the build
    // and makes someone decide, which is the whole point of failing closed.
    const { classifyDir } = await loadDocsModule();
    expect(() => classifyDir("plans")).toThrow(/not classified/);
  });

  it("refuses a screenshots directory rather than remembering one that was deleted", async () => {
    // Same reasoning as `plans/` above: the capture tool and its images are gone
    // (frontend/e2e/capture-screenshots.spec.ts, docs/screenshots/), so a leftover
    // `UNPUBLISHED_DIRS` entry would silently withhold whatever a future contributor
    // filed under that name instead of making them classify it.
    const { classifyDir } = await loadDocsModule();
    expect(() => classifyDir("screenshots")).toThrow(/not classified/);
  });

  it("refuses to guess about a directory nobody classified", async () => {
    const { classifyDir } = await loadDocsModule();
    expect(() => classifyDir("rfcs")).toThrow(/not classified/);
  });

  it("names the directory and both remedies in the failure", async () => {
    const { classifyDir } = await loadDocsModule();
    // The message is the whole value of failing loudly — it has to say what to do.
    expect(() => classifyDir("launch-notes")).toThrow(/"launch-notes"/);
    expect(() => classifyDir("launch-notes")).toThrow(/CATEGORY_ORDER/);
    expect(() => classifyDir("launch-notes")).toThrow(/UNPUBLISHED_DIRS/);
    expect(() => classifyDir("launch-notes")).toThrow(/internal\//);
  });
});

// ── The walk, against fixture trees ───────────────────────────────────────────────

describe("allDocs (fixture tree)", () => {
  it("publishes an ordinary documentation page", async () => {
    vi.stubEnv(
      "DOCS_DIR",
      makeDocsTree({
        "getting-started/20-quick-start.md": "# Quick start\n\nBody.\n",
      }),
    );
    const { allDocs } = await loadDocsModule();
    expect(allDocs().map((d) => d.slug)).toEqual(["getting-started/quick-start"]);
  });

  it("withholds every file under a governance directory, not just the named ones", async () => {
    // The exact regression: the second file in a withheld directory was published, because
    // the old denylist named the first one and nothing generalised.
    vi.stubEnv(
      "DOCS_DIR",
      makeDocsTree({
        "getting-started/20-quick-start.md": "# Quick start\n",
        "governance/Multi-Agent-Research-Assistant-Open-Source-Constitution.md": "# C\n",
        "governance/some-new-policy.md": "# Policy\n",
        "governance/nested/deeper-note.md": "# Deeper\n",
      }),
    );
    const { allDocs } = await loadDocsModule();
    const slugs = allDocs().map((d) => d.slug);

    expect(slugs).toEqual(["getting-started/quick-start"]);
    expect(slugs.some((s) => s.startsWith("governance/"))).toBe(false);
  });

  it("withholds the repo-facing index", async () => {
    vi.stubEnv(
      "DOCS_DIR",
      makeDocsTree({
        "00_INDEX.md": "# Documentation map\n",
        "getting-started/01-overview.md": "# Overview\n",
      }),
    );
    const { allDocs } = await loadDocsModule();
    expect(allDocs().map((d) => d.slug)).toEqual(["getting-started/overview"]);
  });

  // ── Planted failure ─────────────────────────────────────────────────────────────

  it("FAILS THE BUILD on an unclassified directory rather than publishing it", async () => {
    // This is the planted leak. Before M0B it published `internal-notes/leak` at a live
    // URL and nothing anywhere said so.
    vi.stubEnv(
      "DOCS_DIR",
      makeDocsTree({
        "getting-started/01-overview.md": "# Overview\n",
        "internal-notes/leak.md": "# Go/no-go, budget assumptions, private\n",
      }),
    );
    const { allDocs } = await loadDocsModule();
    expect(() => allDocs()).toThrow(/"internal-notes" is not classified/);
  });

  it("fails on an unclassified directory nested inside a published one", async () => {
    vi.stubEnv(
      "DOCS_DIR",
      makeDocsTree({
        "architecture/02-system-architecture.md": "# Architecture\n",
        "architecture/scratch/notes.md": "# Scratch\n",
      }),
    );
    const { allDocs } = await loadDocsModule();
    // Judged on its path, so the message names where it actually sits.
    expect(() => allDocs()).toThrow(/"architecture\/scratch" is not classified/);
  });

  it("still reports an unreachable docs tree as empty, not as a failure", async () => {
    // The site renders an explicit "unavailable" notice for this; it must not become a
    // build failure, or a Docker build without the tree copied in would die instead of
    // saying so. M0B adds a `throw` to the walk, so this is the case that proves the
    // throw did not turn a graceful degradation into a crash.
    //
    // Every candidate root has to miss, not just `DOCS_DIR`: `CANDIDATE_ROOTS` is a
    // priority chain, so an unset or wrong `DOCS_DIR` legitimately falls through to
    // `../docs`. `cwd` is stubbed before the import because the chain is built at module
    // load.
    const nowhere = fs.mkdtempSync(path.join(os.tmpdir(), "docs-boundary-nowhere-"));
    const cwd = vi.spyOn(process, "cwd").mockReturnValue(nowhere);
    try {
      vi.stubEnv("DOCS_DIR", path.join(nowhere, "also-missing"));
      const { allDocs } = await loadDocsModule();
      expect(allDocs()).toEqual([]);
    } finally {
      cwd.mockRestore();
      fs.rmSync(nowhere, { recursive: true, force: true });
    }
  });
});

// ── The real repository tree ──────────────────────────────────────────────────────

describe("allDocs (this repository)", () => {
  it("publishes nothing from governance or plans", async () => {
    const { allDocs } = await loadDocsModule();
    const docs = allDocs();
    // Guard the guard: an empty walk would pass every assertion below vacuously.
    expect(docs.length).toBeGreaterThan(5);
    for (const doc of docs) {
      expect(doc.slug.startsWith("governance/")).toBe(false);
      expect(doc.slug.startsWith("plans/")).toBe(false);
      expect(doc.category).not.toBe("governance");
      expect(doc.category).not.toBe("plans");
    }
  });

  it("classifies every directory that actually exists under docs/", async () => {
    // If someone adds a directory to docs/ without classifying it, this fails here — in a
    // 200ms unit test — instead of in the Pages deploy.
    const { allDocs } = await loadDocsModule();
    expect(() => allDocs()).not.toThrow();
  });

  it("publishes the categories the sidebar promises", async () => {
    const { docCategories } = await loadDocsModule();
    const keys = docCategories().map((c) => c.key);
    expect(keys).toContain("getting-started");
    expect(keys).toContain("architecture");
    expect(keys).toContain("reference");
    expect(keys).not.toContain("governance");
    expect(keys).not.toContain("plans");
  });
});

// ── excerpt (meta descriptions and JSON-LD) ───────────────────────────────────────

describe("excerpt", () => {
  it("takes the first prose paragraph after the H1, with Markdown syntax stripped", async () => {
    const { excerpt } = await loadDocsModule();
    const body = [
      "# Overview",
      "",
      "**A self-hostable, bring-your-own-key research assistant** with `citations` you",
      "can verify, and a [link](https://example.com) to read more.",
      "",
      "## Next section",
      "This is not the first paragraph and must not be picked.",
    ].join("\n");
    expect(excerpt(body)).toBe(
      "A self-hostable, bring-your-own-key research assistant with citations you " +
        "can verify, and a link to read more.",
    );
  });

  it("skips a heading, table, list or blockquote to find the first real paragraph", async () => {
    const { excerpt } = await loadDocsModule();
    const body = [
      "# Title",
      "",
      "## Not this",
      "",
      "| a | b |",
      "|---|---|",
      "",
      "- not this either",
      "",
      "> nor this",
      "",
      "The actual summary paragraph.",
    ].join("\n");
    expect(excerpt(body)).toBe("The actual summary paragraph.");
  });

  it("truncates near the cap on a word boundary-ish point with an ellipsis", async () => {
    const { excerpt } = await loadDocsModule();
    const long = "word ".repeat(60).trim();
    const body = `# Title\n\n${long}`;
    const result = excerpt(body, 50);
    expect(result.length).toBeLessThanOrEqual(50);
    expect(result.endsWith("…")).toBe(true);
  });

  it("returns an empty string when there is no prose paragraph to summarize", async () => {
    const { excerpt } = await loadDocsModule();
    expect(excerpt("# Title only\n")).toBe("");
  });
});
