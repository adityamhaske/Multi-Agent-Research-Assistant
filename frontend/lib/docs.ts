import fs from "node:fs";
import path from "node:path";

/**
 * The documentation set, read from the repo's `docs/` tree (docs/00_INDEX.md).
 *
 * Server-only, and read at **build time**: every docs route is statically generated, so
 * the rendered pages carry their own content and the runtime image never touches the
 * filesystem. That matters for both build targets — the standalone server bundle ships
 * only `.next/`, and the desktop variant is a static export with no server at all.
 */

/** Where `docs/` can be found, in priority order.
 *
 *  Two fallbacks because the frontend builds from two different working roots: `npm run
 *  dev` runs inside `frontend/` with the docs a level up, while the Docker build uses the
 *  repo root as its context and copies the tree in beside the app. Resolving here beats
 *  threading an env var through three compose files and a release workflow. */
const CANDIDATE_ROOTS = [
  process.env.DOCS_DIR,
  path.join(process.cwd(), "..", "docs"),
  path.join(process.cwd(), "project-docs"),
].filter(Boolean) as string[];

/**
 * Never published, regardless of what is on disk.
 *
 * `docs/deep-dive/04_Interview_Defense.md` is gitignored under "Personal / not for
 * publication". It is absent from a clone but present on the author's machine, so a
 * filesystem walk would happily publish it from a local build. An explicit denylist is
 * the only thing standing between "works on my machine" and shipping a private file.
 */
const NEVER_PUBLISH = new Set(["deep-dive/04_Interview_Defense"]);

export interface DocMeta {
  /** URL path under /docs, e.g. "architecture/04_Agent_Design". */
  slug: string;
  title: string;
  /** Directory name, or "" for top-level files. */
  category: string;
  /** Leading number in the filename, used for ordering. Infinity when absent. */
  order: number;
}

export interface Doc extends DocMeta {
  body: string;
}

export interface DocCategory {
  key: string;
  label: string;
  docs: DocMeta[];
}

/** Display names for the directories under `docs/`. */
const CATEGORY_LABELS: Record<string, string> = {
  "": "Overview",
  product: "Product",
  architecture: "Architecture",
  engineering: "Engineering",
  guides: "Guides",
  "deep-dive": "Deep Dive",
};

/** Reading order: what the project is, then what it is made of, then how it is run. */
const CATEGORY_ORDER = [
  "",
  "product",
  "architecture",
  "engineering",
  "guides",
  "deep-dive",
];

function docsRoot(): string | null {
  for (const root of CANDIDATE_ROOTS) {
    try {
      if (fs.existsSync(root) && fs.statSync(root).isDirectory()) return root;
    } catch {
      // An unreadable candidate is simply not the docs root.
    }
  }
  return null;
}

/** The document's own H1 if it has one, else a title derived from the filename.
 *
 *  Reading the H1 keeps the sidebar honest: renaming a heading should not also require
 *  renaming the file to keep navigation truthful. */
function titleOf(body: string, filename: string): string {
  const h1 = body.match(/^#\s+(.+?)\s*$/m);
  if (h1) return stripLeadingNumber(h1[1].replace(/[`*_]/g, "").trim());
  return stripLeadingNumber(
    filename
      .replace(/\.md$/, "")
      .replace(/^\d+[_-]/, "")
      .replace(/[_-]/g, " "),
  );
}

/**
 * Drop the leading document number from a display title.
 *
 * The headings are numbered — "01. Product Vision & Scope", "M12: Research Bundle Format"
 * — because the numbers order the *files*. In a rendered nav they are noise: the list is
 * already in order, so the number restates the position while pushing the words that
 * distinguish one entry from another to the right, where they are harder to scan.
 *
 * Ordering is unaffected. `orderOf` reads the number off the filename, never off the
 * title, so stripping it here changes what a reader sees and nothing about the sequence.
 *
 * Deliberately narrow: only a number that is clearly an index prefix. "v2 Launch Plan"
 * and "Research Bundle Format (v1)" keep their versions, because those numbers mean
 * something.
 */
function stripLeadingNumber(title: string): string {
  return title.replace(/^(?:\d+\.|M\d+:)\s+/, "");
}

function orderOf(filename: string): number {
  const m = filename.match(/^(\d+)/);
  return m ? Number(m[1]) : Number.POSITIVE_INFINITY;
}

function walk(root: string, dir = ""): Doc[] {
  const abs = path.join(root, dir);
  const out: Doc[] = [];
  for (const entry of fs.readdirSync(abs, { withFileTypes: true })) {
    const rel = dir ? `${dir}/${entry.name}` : entry.name;
    if (entry.isDirectory()) {
      // Only documentation directories; `screenshots/` holds PNGs.
      if (entry.name === "screenshots") continue;
      out.push(...walk(root, rel));
      continue;
    }
    if (!entry.name.endsWith(".md")) continue;
    const slug = rel.replace(/\.md$/, "");
    if (NEVER_PUBLISH.has(slug)) continue;
    const body = fs.readFileSync(path.join(root, rel), "utf8");
    out.push({
      slug,
      title: titleOf(body, entry.name),
      category: dir,
      order: orderOf(entry.name),
      body,
    });
  }
  return out;
}

let cached: Doc[] | null = null;

/** Every publishable document. Empty when the docs tree is unreachable, which the pages
 *  render as an explicit message rather than as an empty sidebar. */
export function allDocs(): Doc[] {
  if (cached) return cached;
  const root = docsRoot();
  cached = root ? walk(root) : [];
  return cached;
}

export function getDoc(slug: string): Doc | null {
  return allDocs().find((d) => d.slug === slug) ?? null;
}

/** Documents grouped for the sidebar, in reading order. */
export function docCategories(): DocCategory[] {
  const docs = allDocs();
  return CATEGORY_ORDER.filter((key) =>
    docs.some((d) => d.category === key),
  ).map((key) => ({
    key,
    label: CATEGORY_LABELS[key] ?? key,
    docs: docs
      .filter((d) => d.category === key)
      .sort((a, b) => a.order - b.order || a.title.localeCompare(b.title))
      .map(({ slug, title, category, order }) => ({
        slug,
        title,
        category,
        order,
      })),
  }));
}

/** Flat reading order, for previous/next links. */
export function docOrder(): DocMeta[] {
  return docCategories().flatMap((c) => c.docs);
}

/**
 * Rewrite in-repo Markdown links so they stay inside the docs site.
 *
 * The source files link each other with relative paths like
 * `../architecture/04_Agent_Design.md`, which are correct on GitHub and 404 here.
 * Anything resolving to a published document becomes a `/docs/...` route.
 *
 * A `.md` target that is *not* published is de-linked — the text survives, the link does
 * not. Three published documents link to `04_Interview_Defense.md`, which is gitignored
 * as private and deliberately never generated; leaving those as relative links would both
 * dead-end the reader and advertise a document that is not supposed to be here. Non-`.md`
 * targets (source files, screenshots) are left exactly as written rather than guessed at.
 */
export function rewriteDocLinks(body: string, fromSlug: string): string {
  const fromDir = path.posix.dirname(fromSlug);
  const known = new Set(allDocs().map((d) => d.slug));
  return body.replace(
    /\[([^\]]*)\]\((?!https?:|#|\/)([^)\s]+?)\)/g,
    (whole, text: string, href: string) => {
      const [pathPart, hash = ""] = href.split("#");
      if (!pathPart.endsWith(".md")) return whole;
      const resolved = path.posix
        .normalize(path.posix.join(fromDir === "." ? "" : fromDir, pathPart))
        .replace(/\.md$/, "");
      if (known.has(resolved))
        return `[${text}](/docs/${resolved}${hash ? `#${hash}` : ""})`;
      return text;
    },
  );
}
