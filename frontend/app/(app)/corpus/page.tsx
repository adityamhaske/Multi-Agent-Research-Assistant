"use client";

import { useRef, useState } from "react";
import toast from "react-hot-toast";

import { useActiveProject } from "@/components/ActiveProject";
import { GeneratedBadge } from "@/components/GeneratedBadge";
import { documentUrl } from "@/components/preview/DocumentPreview";
import { PreviewDrawer } from "@/components/preview/PreviewDrawer";
import { EmptyState } from "@/components/ui/EmptyState";
import {
  useCorpusDocuments,
  useCorpusStatus,
  useDeleteDocument,
  useUploadDocument,
} from "@/hooks/queries";
import { ApiError } from "@/lib/api";

/**
 * Corpus management (docs/12 M10).
 *
 * Uploads run one file at a time on purpose. Each ingest embeds every chunk, so firing a
 * folder of PDFs concurrently would stampede the embedding endpoint — and on a local
 * model, thrash a single set of weights. A queue with visible per-file state is both
 * kinder to the backend and more honest: you can see which file is being worked and which
 * one failed, instead of one spinner that hides a partial failure.
 */

/** What the backend will accept (`research_engine/documents.py`). */
// The file picker's convenience list, narrower than what `documents.kind_for` accepts
// (.rst/.csv/.json also ingest as text). Adding a kind here without adding it there
// produces a file the picker offers and the upload rejects — the two are one contract.
const ACCEPTED = [".pdf", ".html", ".htm", ".md", ".markdown", ".txt"];
const MAX_BYTES = 25 * 1024 * 1024;

type Outcome = "queued" | "uploading" | "done" | "failed" | "skipped";

interface QueueItem {
  key: string;
  file: File;
  /** Set when the file arrived via a folder pick, so its origin stays visible. */
  path?: string;
  state: Outcome;
  detail?: string;
}

function formatBytes(bytes?: number | null): string | null {
  if (bytes === null || bytes === undefined) return null;
  if (bytes < 1024) return `${bytes} B`;
  const kb = bytes / 1024;
  if (kb < 1024) return `${Math.round(kb)} KB`;
  return `${(kb / 1024).toFixed(1)} MB`;
}

function extensionOf(name: string): string {
  const dot = name.lastIndexOf(".");
  return dot === -1 ? "" : name.slice(dot).toLowerCase();
}

/** Reject locally what the server would reject anyway. A folder pick can hand us hundreds
 *  of unrelated files; uploading 25 MB to be told "wrong format" wastes the user's time
 *  and the embedding endpoint's. */
function rejectionReason(file: File): string | null {
  if (!ACCEPTED.includes(extensionOf(file.name))) {
    return `unsupported type — ${ACCEPTED.join(", ")} only`;
  }
  if (file.size > MAX_BYTES) return `too large — ${formatBytes(MAX_BYTES)} max`;
  if (file.size === 0) return "empty file";
  return null;
}

const STATE_STYLE: Record<Outcome, { label: string; token: string }> = {
  queued: { label: "queued", token: "text-muted" },
  uploading: { label: "uploading", token: "info" },
  done: { label: "added", token: "success" },
  skipped: { label: "skipped", token: "warning" },
  failed: { label: "failed", token: "danger" },
};

function QueueRow({ item }: { item: QueueItem }) {
  const style = STATE_STYLE[item.state];
  const color = `var(--${style.token})`;
  return (
    <li className="flex items-center gap-3 px-3 py-2 font-mono text-xs">
      <span
        className="min-w-0 flex-1 truncate text-text-primary"
        title={item.path ?? item.file.name}
      >
        {item.path ?? item.file.name}
      </span>
      <span className="shrink-0 tabular-nums text-text-muted">{formatBytes(item.file.size)}</span>
      <span
        className="shrink-0 border px-1.5 py-0.5 text-[0.625rem] font-semibold uppercase tracking-wider"
        style={{
          color,
          backgroundColor: `color-mix(in srgb, ${color} 10%, var(--bg-surface))`,
          borderColor: `color-mix(in srgb, ${color} 30%, var(--border))`,
        }}
        title={item.detail}
      >
        {style.label}
      </span>
    </li>
  );
}

export default function CorpusPage() {
  // Which document the drawer is showing, or null. Identified by id + filename because
  // the preview needs both: the id builds the URL, the filename picks the renderer.
  const [preview, setPreview] = useState<{ id: string; filename: string } | null>(null);
  const { activeId, active } = useActiveProject();
  const { data: status, refetch: refetchStatus } = useCorpusStatus(activeId);
  const { data: docs, isLoading: docsLoading } = useCorpusDocuments(activeId);
  const upload = useUploadDocument();
  const del = useDeleteDocument();

  const [queue, setQueue] = useState<QueueItem[]>([]);
  const [dragging, setDragging] = useState(false);
  const [busy, setBusy] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);
  const folderInput = useRef<HTMLInputElement>(null);

  if (!activeId) {
    return (
      <EmptyState
        title="No active project"
        description="Select or create a project to manage its corpus."
      />
    );
  }

  const runQueue = async (files: { file: File; path?: string }[]) => {
    if (!files.length) return;
    const items: QueueItem[] = files.map(({ file, path }, i) => {
      const reason = rejectionReason(file);
      return {
        key: `${file.name}-${file.size}-${i}`,
        file,
        path,
        state: reason ? "skipped" : "queued",
        detail: reason ?? undefined,
      };
    });
    setQueue(items);
    setBusy(true);

    let added = 0;
    let failed = 0;
    for (const item of items) {
      if (item.state === "skipped") continue;
      setQueue((q) => q.map((x) => (x.key === item.key ? { ...x, state: "uploading" } : x)));
      try {
        await upload.mutateAsync({ projectId: activeId, file: item.file });
        added += 1;
        setQueue((q) => q.map((x) => (x.key === item.key ? { ...x, state: "done" } : x)));
      } catch (err) {
        failed += 1;
        const detail = err instanceof ApiError ? err.message : "upload failed";
        // One bad file must not abandon the rest of a folder — record it and continue.
        setQueue((q) => q.map((x) => (x.key === item.key ? { ...x, state: "failed", detail } : x)));
      }
    }

    setBusy(false);
    refetchStatus();
    const skipped = items.filter((i) => i.state === "skipped").length;
    if (added) toast.success(`Added ${added} document${added === 1 ? "" : "s"}`);
    if (failed || skipped) {
      toast.error(
        [failed ? `${failed} failed` : "", skipped ? `${skipped} skipped` : ""]
          .filter(Boolean)
          .join(", "),
      );
    }
  };

  const fromInput = (e: React.ChangeEvent<HTMLInputElement>) => {
    const picked = Array.from(e.target.files ?? []).map((file) => ({
      file,
      // webkitRelativePath is set only by the folder picker. It keeps the folder
      // structure visible in the queue even though the corpus itself is flat.
      path: (file as File & { webkitRelativePath?: string }).webkitRelativePath || undefined,
    }));
    e.target.value = "";
    void runQueue(picked);
  };

  const onDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragging(false);
    if (busy) return;
    void runQueue(Array.from(e.dataTransfer.files).map((file) => ({ file })));
  };

  const handleDelete = async (docId: string, filename: string) => {
    if (!confirm(`Delete ${filename}?`)) return;
    try {
      await del.mutateAsync({ projectId: activeId, docId });
      toast.success(`Deleted ${filename}`);
      refetchStatus();
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Delete failed.");
    }
  };

  const doneCount = queue.filter((q) => q.state === "done").length;

  return (
    <div className="space-y-8">
      <section aria-labelledby="corpus-management">
        <h1
          id="corpus-management"
          className="mb-1 font-serif text-2xl font-bold tracking-tight text-text-primary"
        >
          Corpus Management
        </h1>
        <p className="mb-6 max-w-2xl text-sm leading-relaxed text-text-muted">
          Upload documents to restrict research to an airgapped local corpus. Scoped to{" "}
          <strong className="font-semibold text-text-primary">{active?.name}</strong>. Approved
          reports in this project are automatically saved here too and marked{" "}
          <span className="border border-border bg-bg-elevated px-1.5 py-0.2 font-mono text-[0.6875rem] font-semibold uppercase tracking-wider text-text-secondary">Generated</span>{" "}
          so they are never recycled as evidence for subsequent questions.
        </p>

        {/* 1. Drag & Drop Upload Zone */}
        <div
          onDragOver={(e) => {
            e.preventDefault();
            if (!busy) setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={onDrop}
          className="mb-8 border-2 border-dashed p-8 text-center transition-all shadow-xs"
          style={{
            borderColor: dragging ? "var(--accent)" : "var(--border)",
            backgroundColor: dragging
              ? "color-mix(in srgb, var(--accent) 8%, var(--bg-surface))"
              : "var(--bg-surface)",
          }}
        >
          <div className="mx-auto flex h-11 w-11 items-center justify-center border border-border bg-bg-elevated text-lg text-accent">
            📄
          </div>
          <p className="mt-3 text-sm font-semibold text-text-primary">
            Drag & drop files or folders here to ingest
          </p>
          <div className="mt-2 flex flex-wrap items-center justify-center gap-1.5 font-mono text-[length:var(--text-micro)] text-text-muted">
            {ACCEPTED.map((ext) => (
              <span key={ext} className="border border-border bg-bg-elevated px-1.5 py-0.5">
                {ext}
              </span>
            ))}
            <span className="ml-1 text-text-muted">· up to {formatBytes(MAX_BYTES)} each</span>
          </div>

          <div className="mt-5 flex flex-wrap items-center justify-center gap-2.5">
            <button
              type="button"
              className="btn btn-primary px-4 py-2 text-xs font-medium"
              disabled={busy}
              onClick={() => fileInput.current?.click()}
            >
              {busy && <span className="spinner" />}
              Choose files
            </button>
            <button
              type="button"
              className="btn btn-secondary px-4 py-2 text-xs font-medium"
              disabled={busy}
              onClick={() => folderInput.current?.click()}
            >
              Choose folder
            </button>
          </div>

          <input
            ref={fileInput}
            type="file"
            multiple
            accept={ACCEPTED.join(",")}
            onChange={fromInput}
            className="hidden"
          />
          {/* `webkitdirectory` is non-standard but is what every current browser
              implements for directory selection, and React has no typing for it. */}
          <input
            ref={folderInput}
            type="file"
            multiple
            onChange={fromInput}
            className="hidden"
            {...({ webkitdirectory: "", directory: "" } as Record<string, string>)}
          />
        </div>

        {/* 2. Upload Queue */}
        {queue.length > 0 && (
          <div className="mb-8 border border-border bg-bg-surface shadow-xs">
            <div className="flex items-center justify-between border-b border-border bg-bg-elevated/40 px-3.5 py-2.5">
              <span className="font-mono text-xs font-semibold uppercase tracking-wider text-text-secondary">
                Upload queue ({doneCount}/{queue.length} completed)
              </span>
              {!busy && (
                <button
                  type="button"
                  onClick={() => setQueue([])}
                  className="font-mono text-xs text-text-muted transition-colors hover:text-text-primary"
                >
                  Clear queue
                </button>
              )}
            </div>
            <ul className="max-h-60 divide-y divide-border overflow-y-auto">
              {queue.map((item) => (
                <QueueRow key={item.key} item={item} />
              ))}
            </ul>
          </div>
        )}

        {preview && activeId && (
          <PreviewDrawer
            open
            onClose={() => setPreview(null)}
            url={documentUrl(activeId, preview.id)}
            filename={preview.filename}
            downloadable
          />
        )}

        {/* 3. Main Split Grid (Documents & Stats) */}
        <div className="grid gap-6 lg:grid-cols-3">
          <div className="space-y-4 lg:col-span-2">
            <div className="flex items-baseline justify-between gap-2">
              <h2 className="font-serif text-lg font-bold tracking-tight text-text-primary">
                Documents
              </h2>
              {docs && docs.length > 0 && (
                <span className="border border-border bg-bg-elevated px-2 py-0.5 font-mono text-xs text-text-muted">
                  {docs.length} {docs.length === 1 ? "document" : "documents"}
                </span>
              )}
            </div>

            {docsLoading ? (
              <div className="h-28 animate-pulse border border-border bg-bg-elevated" />
            ) : docs && docs.length > 0 ? (
              <ul className="divide-y divide-border border border-border bg-bg-surface shadow-xs">
                {docs.map((doc) => {
                  const size = formatBytes(doc.size_bytes);
                  return (
                    <li
                      key={doc.id}
                      className="group flex items-center justify-between gap-3 p-4 transition-colors hover:bg-bg-elevated/60"
                    >
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2">
                          <span className="font-mono text-xs text-text-muted" aria-hidden>
                            📄
                          </span>
                          <p className="truncate font-serif text-sm font-semibold text-text-primary group-hover:text-accent">
                            {doc.filename}
                          </p>
                          {doc.origin === "generated" && <GeneratedBadge className="shrink-0" />}
                        </div>
                        <div className="mt-1 flex flex-wrap items-center gap-2 font-mono text-xs text-text-muted">
                          <span>{doc.chunks} chunks</span>
                          {size && <span>· {size}</span>}
                          {doc.created_at && <span>· {new Date(doc.created_at).toLocaleDateString()}</span>}
                        </div>
                      </div>
                      <div className="flex shrink-0 items-center gap-1.5">
                        {doc.downloadable ? (
                          <button
                            type="button"
                            onClick={() => setPreview({ id: doc.id, filename: doc.filename })}
                            className="btn btn-secondary px-2.5 py-1 font-mono text-xs font-medium text-accent hover:border-accent"
                          >
                            Preview
                          </button>
                        ) : (
                          <span
                            className="px-2 py-0.5 font-mono text-xs text-text-muted"
                            title="Added before original files were kept — its text is still searchable."
                          >
                            text only
                          </span>
                        )}
                        <button
                          onClick={() => handleDelete(doc.id, doc.filename)}
                          disabled={del.isPending}
                          className="px-2 py-1 font-mono text-xs font-medium text-text-muted transition-colors hover:text-danger"
                        >
                          Delete
                        </button>
                      </div>
                    </li>
                  );
                })}
              </ul>
            ) : (
              <div className="border border-dashed border-border bg-bg-surface p-10 text-center shadow-xs">
                <p className="text-sm font-medium text-text-secondary">No documents uploaded yet</p>
                <p className="mt-1 text-xs text-text-muted">
                  Drag files into the dropzone above or click &ldquo;Choose files&rdquo; to build your corpus.
                </p>
              </div>
            )}
          </div>

          {/* Right Sidebar: Corpus Stats & Privacy */}
          <div className="space-y-4">
            <h2 className="font-serif text-lg font-bold tracking-tight text-text-primary">
              Corpus Stats
            </h2>
            <div className="card space-y-4 border border-border bg-bg-surface p-5 shadow-xs">
              <div className="border-b border-border/60 pb-3">
                <div className="font-mono text-xs uppercase tracking-wider text-text-muted">
                  Total Documents
                </div>
                <div className="mt-1 font-mono text-2xl font-bold tabular-nums text-text-primary">
                  {status?.documents || 0}
                </div>
              </div>
              <div className="border-b border-border/60 pb-3">
                <div className="font-mono text-xs uppercase tracking-wider text-text-muted">
                  Total Chunks
                </div>
                <div className="mt-1 font-mono text-2xl font-bold tabular-nums text-text-primary">
                  {status?.chunks || 0}
                </div>
              </div>
              <div>
                <div className="font-mono text-xs uppercase tracking-wider text-text-muted">
                  Embedding Model
                </div>
                <div className="mt-1.5 truncate border border-border bg-bg-elevated px-2 py-1 font-mono text-xs font-semibold text-accent">
                  {status?.current_model || "None"}
                </div>
              </div>

              <div className="border-t border-border/60 pt-3">
                <div className="flex items-center gap-1.5 text-xs text-text-muted font-mono">
                  <span className="h-2 w-2 rounded-full bg-success" aria-hidden />
                  Airgapped Local Storage
                </div>
                <p className="mt-1 text-[length:var(--text-micro)] text-text-muted leading-relaxed">
                  Documents are embedded and stored locally in this project&apos;s corpus database.
                </p>
              </div>
            </div>
          </div>
        </div>
      </section>
    </div>
  );
}
