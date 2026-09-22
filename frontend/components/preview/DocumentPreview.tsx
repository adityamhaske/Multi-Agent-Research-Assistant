"use client";

import { useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { apiBase, authHeaders, isDesktop } from "@/lib/desktop";

/**
 * A corpus document, rendered in place (internal/07 Phase 6; req 9).
 *
 * Four types, three of which never touch the download route's rendering path at all —
 * the bytes are fetched and rendered by this component, and `fetch` ignores
 * `Content-Disposition`. Only PDF is handed to the browser, because it is the only
 * format where "render" does not mean "execute a document in our origin".
 *
 * **HTML is the dangerous one, and the boundary is the sandbox, not a sanitizer.**
 * An uploaded page was authored by whoever made the file. It goes into
 * `<iframe sandbox="" srcdoc={…}>`: no `allow-scripts`, no `allow-same-origin`, so the
 * frame gets an opaque origin, cannot run script, cannot reach our cookies, and cannot
 * navigate the top window. The two React escape hatches for injecting raw HTML stay
 * banned and CI greps the source for both by name — a sanitizer is a list of things
 * someone remembered, the sandbox is a capability the browser withholds.
 *
 * (Those two names are deliberately not written out anywhere in this file. The guard is
 * a plain grep and cannot tell a use from a mention, so explaining the ban in prose is
 * enough to fail the build — which is exactly what it did.)
 *
 * Markdown goes through the same `react-markdown` + `remark-gfm` pipeline reports use,
 * which does not render raw HTML — so an uploaded `.md` containing a `<script>` tag is
 * inert text, and it is displayed rather than silently dropped.
 */

export type PreviewKind = "pdf" | "html" | "md" | "txt";

/** The stored kind, inferred from the filename the same way `documents.kind_for` does. */
export function kindForFilename(filename: string): PreviewKind | null {
  const ext = filename.includes(".") ? filename.split(".").pop()!.toLowerCase() : "";
  if (ext === "pdf") return "pdf";
  if (ext === "html" || ext === "htm") return "html";
  if (ext === "md" || ext === "markdown") return "md";
  if (["txt", "text", "rst", "csv", "json"].includes(ext)) return "txt";
  return null;
}

/** Bytes that are clearly not text — a guard against rendering a binary as a wall of
 *  replacement characters when a file's extension lied about its contents. */
function looksBinary(text: string): boolean {
  return text.slice(0, 2000).includes("\u0000");
}

function Frame({ children }: { children: React.ReactNode }) {
  return <div className="h-full overflow-auto bg-bg-surface p-4">{children}</div>;
}

/**
 * Fetches and renders a text-shaped document.
 *
 * Split out and mounted with `key={url}` by `DocumentPreview` rather than resetting its
 * own state when `url` changes: remount-over-effect-derived-state is this codebase's
 * rule (frontend/AGENTS.md), and the lint rule enforces it. A `setText(null)` at the top
 * of an effect is exactly the cascading-render shape that rule exists to prevent.
 */
function TextDocument({ url, filename, kind }: { url: string; filename: string; kind: PreviewKind }) {
  const [text, setText] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetch(url, { credentials: isDesktop ? "omit" : "include", headers: { ...authHeaders() } })
      .then(async (res) => {
        if (!res.ok) throw new Error(`Could not load this document (${res.status}).`);
        return res.text();
      })
      .then((body) => {
        if (cancelled) return;
        if (looksBinary(body)) {
          setError("This file's contents don't look like text, so it can't be previewed here.");
          return;
        }
        setText(body);
      })
      .catch((e: Error) => {
        if (!cancelled) setError(e.message);
      });
    return () => {
      cancelled = true;
    };
  }, [url]);

  if (error) {
    return (
      <Frame>
        <p role="alert" className="text-sm" style={{ color: "var(--danger)" }}>
          {error}
        </p>
      </Frame>
    );
  }

  if (text === null) {
    return (
      <Frame>
        <div className="space-y-3" aria-hidden>
          {[95, 80, 90, 70].map((w, i) => (
            <div key={i} className="h-3.5 animate-pulse bg-bg-elevated" style={{ width: `${w}%` }} />
          ))}
        </div>
        <span className="sr-only">Loading {filename}…</span>
      </Frame>
    );
  }

  if (kind === "html") {
    return (
      <iframe
        // sandbox="" — every capability withheld. Not `allow-scripts`, not
        // `allow-same-origin`, and never both (together they let a frame remove its own
        // sandbox). This is the boundary; see the module docstring.
        sandbox=""
        srcDoc={text}
        title={`${filename} (preview)`}
        className="h-full w-full border-0 bg-bg-surface"
        // The frame is untrusted content: stop it leaking where it was opened from.
        referrerPolicy="no-referrer"
      />
    );
  }

  if (kind === "md") {
    return (
      <Frame>
        <div className="prose-report">
          {/* No raw-HTML plugin here: HTML inside an uploaded .md stays inert text. */}
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{text}</ReactMarkdown>
        </div>
      </Frame>
    );
  }

  return (
    <Frame>
      <pre className="whitespace-pre-wrap break-words font-mono text-xs text-text-secondary">
        {text}
      </pre>
    </Frame>
  );
}

export function DocumentPreview({
  url,
  filename,
  downloadable,
}: {
  /** The document's download URL. Same-origin `/api` proxy — never a hardcoded host. */
  url: string;
  filename: string;
  /** False for documents stored before originals were kept: text is searchable, but
   *  there is nothing to show. Saying so beats an empty pane. */
  downloadable: boolean;
}) {
  const kind = kindForFilename(filename);

  if (!downloadable) {
    return (
      <Frame>
        <p className="text-sm text-text-secondary">
          This document was added before original files were kept. Its text is still
          searchable and citable — there is just no file to show.
        </p>
      </Frame>
    );
  }

  if (kind === null) {
    return (
      <Frame>
        <p className="text-sm text-text-secondary">
          No preview for this file type. Download it to open in its own application.
        </p>
      </Frame>
    );
  }

  if (kind === "pdf") {
    return (
      <object
        data={url}
        type="application/pdf"
        className="h-full w-full"
        aria-label={`${filename} (PDF preview)`}
      >
        {/* Shown when the browser has no PDF viewer, rather than a blank rectangle. */}
        <Frame>
          <p className="text-sm text-text-secondary">
            Your browser can&apos;t display PDFs inline. Download it to read it.
          </p>
        </Frame>
      </object>
    );
  }

  return <TextDocument key={url} url={url} filename={filename} kind={kind} />;
}

/** The download URL for one corpus document, via the same-origin API proxy. */
/**
 * The download route for one corpus document.
 *
 * The `/corpus` segment is not decorative — the backend router is mounted at
 * `/projects/{project_id}/corpus` (`app/api/v1/corpus.py`), so omitting it 404s. This
 * function shipped without it, which made every preview render "Could not load this
 * document (404)" while the surrounding drawer, the row, and the ingest all worked. Unit
 * tests passed the whole time: they pass a stub URL in, so nothing that constructs one
 * was ever exercised. Only the golden E2E, driving a real upload against a real API,
 * caught it.
 *
 * `hooks/queries.ts` builds the same path for the delete and download mutations. Two
 * copies of one route is exactly the drift AGENTS.md catalogues — change both, or better,
 * reach for the one in `queries.ts` when adding a third caller.
 */
export function documentUrl(projectId: string, docId: string): string {
  return `${apiBase()}/projects/${projectId}/corpus/documents/${docId}/download`;
}
