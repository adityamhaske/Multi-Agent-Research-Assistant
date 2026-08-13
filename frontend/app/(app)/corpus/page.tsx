"use client";

import { useState } from "react";
import toast from "react-hot-toast";

import { useActiveProject } from "@/components/ActiveProject";
import {
  useCorpusDocuments,
  useCorpusStatus,
  useDeleteDocument,
  useUploadDocument,
} from "@/hooks/queries";
import { ApiError } from "@/lib/api";

export default function CorpusPage() {
  const { activeId, active } = useActiveProject();
  const { data: status, refetch: refetchStatus } = useCorpusStatus(activeId);
  const { data: docs, isLoading: docsLoading } = useCorpusDocuments(activeId);
  const upload = useUploadDocument();
  const del = useDeleteDocument();
  
  const [file, setFile] = useState<File | null>(null);

  if (!activeId) {
    return (
      <div className="card flex flex-col items-center py-10 text-center">
        <span aria-hidden className="mb-2 text-2xl opacity-60">◇</span>
        <p className="text-sm font-medium text-text-primary">No active project</p>
        <p className="mt-0.5 text-xs text-text-muted">Select or create a project to manage its corpus.</p>
      </div>
    );
  }

  const handleUpload = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!file) return;
    try {
      await upload.mutateAsync({ projectId: activeId, file });
      toast.success(`Uploaded ${file.name}`);
      setFile(null);
      refetchStatus();
      // Also reset file input
      (document.getElementById("file-upload") as HTMLInputElement).value = "";
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Upload failed.");
    }
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

  return (
    <div className="space-y-10">
      <section aria-labelledby="corpus-management">
        <h1
          id="corpus-management"
          className="mb-1 text-2xl font-semibold tracking-[-0.02em] text-text-primary"
        >
          Corpus Management
        </h1>
        <p className="mb-5 max-w-2xl text-sm leading-relaxed text-text-muted">
          Upload documents to restrict research to an airgapped local corpus.{" "}
          Saved to <strong className="text-text-secondary">{active?.name}</strong>.
        </p>

        <form onSubmit={handleUpload} className="card space-y-5 p-5 sm:p-6 mb-8">
          <div>
            <label htmlFor="file-upload" className="mb-1.5 block text-sm font-medium text-text-secondary">
              Upload Document
            </label>
            <div className="flex gap-4">
              <input
                id="file-upload"
                type="file"
                onChange={(e) => setFile(e.target.files?.[0] || null)}
                className="block w-full text-sm text-text-muted file:mr-4 file:rounded-full file:border-0 file:bg-[var(--accent-muted)] file:px-4 file:py-2 file:text-sm file:font-semibold file:text-[var(--accent)] hover:file:bg-[var(--accent-hover)]"
              />
              <button
                type="submit"
                disabled={!file || upload.isPending}
                className="btn btn-primary whitespace-nowrap"
              >
                {upload.isPending && <span className="spinner" />}
                Upload
              </button>
            </div>
          </div>
        </form>

        <div className="grid gap-6 md:grid-cols-3">
          <div className="md:col-span-2 space-y-4">
            <h2 className="text-lg font-medium text-text-primary">Documents</h2>
            {docsLoading ? (
              <div className="h-20 animate-pulse rounded-lg bg-bg-elevated" />
            ) : docs && docs.length > 0 ? (
              <ul className="divide-y divide-border rounded-lg border border-border bg-bg-base">
                {docs.map((doc) => (
                  <li key={doc.id} className="flex items-center justify-between p-4 hover:bg-bg-elevated">
                    <div>
                      <p className="text-sm font-medium text-text-primary">{doc.filename}</p>
                      <p className="text-xs text-text-muted">{doc.chunks} chunks · {new Date(doc.created_at || "").toLocaleString()}</p>
                    </div>
                    <button
                      onClick={() => handleDelete(doc.id, doc.filename)}
                      disabled={del.isPending}
                      className="text-xs font-medium text-[var(--danger)] hover:underline"
                    >
                      Delete
                    </button>
                  </li>
                ))}
              </ul>
            ) : (
              <div className="rounded-lg border border-border border-dashed p-8 text-center text-sm text-text-muted">
                No documents uploaded yet.
              </div>
            )}
          </div>

          <div className="space-y-4">
            <h2 className="text-lg font-medium text-text-primary">Status</h2>
            <div className="rounded-lg border border-border bg-bg-base p-5 space-y-4">
              <div>
                <div className="text-xs text-text-muted uppercase tracking-wider">Total Documents</div>
                <div className="text-2xl font-semibold">{status?.documents || 0}</div>
              </div>
              <div>
                <div className="text-xs text-text-muted uppercase tracking-wider">Total Chunks</div>
                <div className="text-2xl font-semibold">{status?.chunks || 0}</div>
              </div>
              <div>
                <div className="text-xs text-text-muted uppercase tracking-wider">Embedding Model</div>
                <div className="text-sm font-medium mt-1 truncate">{status?.current_model || "None"}</div>
              </div>
            </div>
          </div>
        </div>
      </section>
    </div>
  );
}
