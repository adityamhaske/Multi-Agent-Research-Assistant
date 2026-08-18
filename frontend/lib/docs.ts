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
 * `00_INDEX` is the repository's own map of `docs/` — the thing a person reads when they
 * are browsing the tree on GitHub. On the site it would be a second table of contents
 * sitting next to the generated `/docs` index, which is the duplicate-navigation problem
 * rather than a solution to it.
 *
 * A filesystem walk publishes whatever it finds, including files a clone does not have,
 * so an explicit denylist is also what stands between "works on my machine" and shipping
 * something private. Internal engineering notes live outside `docs/` entirely (see
 * `internal/`), which is a stronger guarantee than a list — this list is the backstop.
 */
/**
 * Matched against the **source path** under `docs/` (minus `.md`), not the published slug.
 *
 * The slug has its numeric prefixes stripped, so `00_INDEX.md` publishes at `INDEX` — a
 * denylist keyed on the slug would have to spell that, and would silently stop matching the
 * moment a file were renumbered. The path is the stable thing to name.
 *
 * This list is for individual **files** at the root of `docs/`. Whole directories are
 * classified by `UNPUBLISHED_DIRS` below — naming files one at a time was the bug this
 * replaces: adding a second document to `docs/plans/` published it.
 */
const NEVER_PUBLISH = new Set([
  // The repository's own map of `docs/` — the thing a person reads when browsing the tree
  // on GitHub. On the site it would be a second table of contents beside the generated
  // `/docs` index, which is the duplicate-navigation problem rather than a fix for it.
  "00_INDEX",
]);

/**
 * Directories under `docs/` that exist on disk and are deliberately **not** published.
 *
 * `governance/` and `plans/` are repository governance rather than product documentation:
 * they describe how the project is *run*, not how the product works. `AGENTS.md` points
 * contributors and coding agents at them, so they stay in the tree. `screenshots/` holds
 * PNGs the README embeds.
 *
 * **This used to be a per-file denylist, and that was a latent leak.** A directory's
 * absence from `CATEGORY_ORDER` hides it from the sidebar and the index but does *not*
 * stop `generateStaticParams` generating its routes — so anything filed under
 * `docs/plans/` beyond the two named files was published at a URL nothing linked to, which
 * is the worst of both outcomes. The V1→V2 audit had to be filed in `internal/` for
 * exactly this reason. Classification is now by directory, and unclassified directories
 * fail the build (see `classifyDir`) rather than publishing by default.
 */
const UNPUBLISHED_DIRS = new Set(["governance", "plans", "screenshots"]);

/**
 * Whether a directory found under `docs/` is published, withheld, or unclassified.
 *
 * Fail-closed **and loud**: a directory nobody has classified throws at build time instead
 * of being published (the old failure) or silently dropped (a new one — a contributor
 * adding `docs/tutorials/` would find their pages missing with nothing to explain it).
 * The author makes the call once, in code, where it is reviewable.
 *
 * Exported for `docs.test.ts`, which is the regression guard for the leak above.
 */
export function classifyDir(dir: string): "publish" | "withhold" {
  if (UNPUBLISHED_DIRS.has(dir)) return "withhold";
  if (CATEGORY_ORDER.includes(dir)) return "publish";
  throw new Error(
    `docs/: directory "${dir}" is not classified.\n` +
      `Every directory under docs/ must be either published or explicitly withheld, ` +
      `because the site generates a route for every Markdown file it walks.\n` +
      `  • To publish it: add "${dir}" to CATEGORY_ORDER and CATEGORY_LABELS in ` +
      `frontend/lib/docs.ts (and NAV_ORDER for reading order).\n` +
      `  • To keep it private: add "${dir}" to UNPUBLISHED_DIRS in the same file — or, ` +
      `better, move it to internal/, which the site never walks at all.`,
  );
}

export interface DocMeta {
  /** URL path under /docs, e.g. "architecture/agent-architecture". */
  slug: string;
  title: string;
  /** Directory name, or "" for top-level files. */
  category: string;
  /** Position within the category. See `NAV_ORDER`. */
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
  "getting-started": "Getting started",
  "user-guide": "User guide",
  architecture: "Architecture",
  deployment: "Deployment",
  developers: "Developers",
  reference: "Reference",
  research: "Research",
  project: "Project",
};

/** Reading order: understand it, use it, understand how it works, run it, change it. */
const CATEGORY_ORDER = [
  "",
  "getting-started",
  "user-guide",
  "architecture",
  "deployment",
  "developers",
  "reference",
  "research",
  "project",
];

/**
 * Reading order **within** a category, by slug.
 *
 * Explicit rather than derived from the filename, because the two things a filename
 * number would have to encode pull in opposite directions. Files keep a numeric prefix as
 * a stable document identity — hundreds of code comments cite documents by that number
 * (`docs/04 §6`) and renumbering them would silently invalidate every one — while the
 * order a reader wants is a separate, editable decision. Security is document 06 and
 * belongs last in Architecture; a sort on the prefix cannot express that.
 *
 * A document missing from this list still renders; it sorts to the end of its category by
 * filename number, then title. Adding a page therefore never breaks the build — it just
 * lands last until it is listed here.
 */
const NAV_ORDER: Record<string, string[]> = {
  "getting-started": [
    "getting-started/overview",
    "getting-started/quick-start",
    "getting-started/configuration",
    "getting-started/local-llm",
    "getting-started/desktop-app",
    "getting-started/troubleshooting",
  ],
  "user-guide": [
    "user-guide/running-research",
    "user-guide/review-and-approval",
    "user-guide/citations",
    "user-guide/projects-and-memory",
    "user-guide/exports",
  ],
  architecture: [
    "architecture/system-architecture",
    "architecture/agent-architecture",
    "architecture/data-model",
    "architecture/local-and-self-hosted",
    "architecture/security",
  ],
  deployment: [
    "deployment/docker",
    "deployment/production",
    "deployment/operations",
  ],
  developers: [
    "developers/development",
    "developers/testing-and-evaluation",
    "developers/engineering-guidelines",
    "developers/frontend-guidelines",
    "developers/contributing",
  ],
  reference: [
    "reference/api",
    "reference/sse",
    "reference/bundle-format",
    "reference/configuration",
  ],
  research: ["research/citation-fidelity-benchmark"],
  project: ["project/roadmap", "project/changelog"],
};

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
 * Some headings still carry one — "01. Product Vision", "M12: Research Bundle Format" —
 * and in a rendered nav they are noise: the list is already ordered, so the number
 * restates the position while pushing the words that distinguish one entry from another
 * to the right, where they are harder to scan.
 *
 * Deliberately narrow: only a number that is clearly an index prefix. "Research Bundle
 * Format (v1)" keeps its version, because that number means something.
 */
function stripLeadingNumber(title: string): string {
  return title.replace(/^(?:\d+\.|M\d+:)\s+/, "");
}

/**
 * The published URL path for a file path under `docs/`.
 *
 * Strips the `.md` and the numeric prefix from each segment, so
 * `architecture/04-agent-architecture.md` is served at `architecture/agent-architecture`.
 * The prefix orders and identifies the file on disk; it is not something a reader should
 * have to type or read in a URL, and a number in a URL is the part that goes stale first
 * if a document is ever resequenced.
 *
 * Used for both directions — deriving a document's own slug, and resolving the relative
 * `.md` links the source files use — so the two can never disagree about what a path
 * means.
 */
function slugFor(relPath: string): string {
  return relPath
    .replace(/\.md$/, "")
    .split("/")
    .map((segment) => segment.replace(/^\d+[-_]/, ""))
    .join("/");
}

/** Fallback position for a document that `NAV_ORDER` does not list: its filename number,
 *  else last. Keeps an unlisted new page rendering rather than failing the build. */
function fallbackOrder(filename: string): number {
  const m = filename.match(/^(\d+)/);
  return m ? 1000 + Number(m[1]) : Number.POSITIVE_INFINITY;
}

/** Position within the category — the explicit nav list first, filename number after. */
function orderOf(slug: string, category: string, filename: string): number {
  const listed = NAV_ORDER[category]?.indexOf(slug) ?? -1;
  return listed >= 0 ? listed : fallbackOrder(filename);
}

function walk(root: string, dir = ""): Doc[] {
  const abs = path.join(root, dir);
  const out: Doc[] = [];
  for (const entry of fs.readdirSync(abs, { withFileTypes: true })) {
    const rel = dir ? `${dir}/${entry.name}` : entry.name;
    if (entry.isDirectory()) {
      // Classified by path, not by name, so a nested directory is judged on where it
      // actually sits — `architecture/deep/` is not `deep/`, and would otherwise produce
      // routed pages belonging to no category in the sidebar.
      if (classifyDir(rel) === "withhold") continue;
      out.push(...walk(root, rel));
      continue;
    }
    if (!entry.name.endsWith(".md")) continue;
    if (NEVER_PUBLISH.has(rel.replace(/\.md$/, ""))) continue;
    const slug = slugFor(rel);
    const body = fs.readFileSync(path.join(root, rel), "utf8");
    out.push({
      slug,
      title: titleOf(body, entry.name),
      category: dir,
      order: orderOf(slug, dir, entry.name),
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
 * `../architecture/04-agent-architecture.md`, which are correct on GitHub and 404 here.
 * Anything resolving to a published document becomes a `/docs/...` route, with the
 * filename's numeric prefix stripped by the same `slugFor` the document's own slug comes
 * from — so a link and its target cannot disagree about the URL.
 *
 * A `.md` target that is *not* published is de-linked: the text survives, the link does
 * not. That covers `00_INDEX.md` (the repo-facing map) and anything under `internal/`,
 * where leaving a relative link would both dead-end the reader and advertise a file that
 * is not part of the site. Non-`.md` targets (source files, screenshots) are left exactly
 * as written rather than guessed at.
 *
 * `fromSlug` is the *published* slug, whose directories have no numeric prefixes, so
 * resolution happens in slug space on both sides.
 */
export function rewriteDocLinks(body: string, fromSlug: string): string {
  const fromDir = path.posix.dirname(fromSlug);
  const known = new Set(allDocs().map((d) => d.slug));
  return body.replace(
    /\[([^\]]*)\]\((?!https?:|#|\/)([^)\s]+?)\)/g,
    (whole, text: string, href: string) => {
      const [pathPart, hash = ""] = href.split("#");
      if (!pathPart.endsWith(".md")) return whole;
      const resolved = path.posix.normalize(
        path.posix.join(fromDir === "." ? "" : fromDir, slugFor(pathPart)),
      );
      if (known.has(resolved))
        return `[${text}](/docs/${resolved}${hash ? `#${hash}` : ""})`;
      return text;
    },
  );
}
