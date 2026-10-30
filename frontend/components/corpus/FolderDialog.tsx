"use client";

import { useRef, useState } from "react";
import toast from "react-hot-toast";

import { useDeleteFolder, useUpdateFolder } from "@/hooks/queries";
import { useDialogFocus } from "@/hooks/useDialogFocus";
import { ApiError } from "@/lib/api";
import {
  folderDeletion,
  moveTargets,
  type CorpusTree,
  type TreeFolder,
} from "@/lib/corpusTree";

export type FolderAction = "rename" | "move" | "delete";

const TOP_LEVEL = "";

function plural(n: number, one: string, many = `${one}s`): string {
  return `${n} ${n === 1 ? one : many}`;
}

/**
 * Rename, move or delete one corpus folder (RFC V3.1 §7.1).
 *
 * An in-page dialog rather than the browser's `confirm`/`prompt`: those are drawn by the
 * webview, and the three desktop webviews do not draw them alike, so a confirmation the user
 * must read before files are deleted is rendered by the page itself.
 *
 * The delete confirmation states what will go before anything is sent — the subfolders, and
 * the files filed nowhere else — and the toast afterwards reports the server's own count.
 */
export function FolderDialog({
  projectId,
  tree,
  folder,
  action,
  onClose,
}: {
  projectId: string;
  tree: CorpusTree;
  folder: TreeFolder;
  action: FolderAction;
  onClose: () => void;
}) {
  const panelRef = useRef<HTMLDivElement>(null);
  const firstRef = useRef<HTMLInputElement & HTMLSelectElement & HTMLButtonElement>(null);
  useDialogFocus(true, onClose, panelRef, firstRef);

  const update = useUpdateFolder();
  const remove = useDeleteFolder();
  const [name, setName] = useState(folder.name);
  const [parent, setParent] = useState<string>(folder.parent_id ?? TOP_LEVEL);
  const pending = update.isPending || remove.isPending;

  const fail = (err: unknown) =>
    toast.error(err instanceof ApiError ? err.message : "That did not work. Nothing was changed.");

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    if (action === "rename") {
      const next = name.trim();
      if (!next || next === folder.name) return onClose();
      update.mutate(
        { projectId, folderId: folder.id, name: next },
        { onSuccess: () => onClose(), onError: fail },
      );
    } else if (action === "move") {
      const next = parent === TOP_LEVEL ? null : parent;
      if (next === (folder.parent_id ?? null)) return onClose();
      update.mutate(
        { projectId, folderId: folder.id, parentId: next },
        { onSuccess: () => onClose(), onError: fail },
      );
    } else {
      remove.mutate(
        { projectId, folderId: folder.id },
        {
          onSuccess: (done) => {
            toast.success(
              `Deleted ${plural(done.folders_deleted, "folder")} and ${plural(done.documents_deleted, "file")}`,
            );
            onClose();
          },
          onError: fail,
        },
      );
    }
  };

  const title =
    action === "rename"
      ? `Rename “${folder.name}”`
      : action === "move"
        ? `Move “${folder.name}”`
        : `Delete “${folder.name}”?`;
  const doomed = action === "delete" ? folderDeletion(tree, folder.id) : null;

  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center p-4">
      <button
        type="button"
        aria-label="Close without changing anything"
        tabIndex={-1}
        onClick={onClose}
        className="absolute inset-0 bg-black/40"
      />
      <div
        ref={panelRef}
        role={action === "delete" ? "alertdialog" : "dialog"}
        aria-modal="true"
        aria-labelledby="folder-dialog-title"
        aria-describedby={doomed ? "folder-dialog-consequence" : undefined}
        tabIndex={-1}
        className="relative w-full max-w-md border border-border bg-bg-surface p-5 shadow-xl"
      >
        <form onSubmit={submit}>
          <h2 id="folder-dialog-title" className="font-serif text-lg font-bold text-text-primary">
            {title}
          </h2>

          {action === "rename" && (
            <label className="mt-3 block text-sm text-text-secondary">
              New name
              <input
                ref={firstRef}
                value={name}
                onChange={(e) => setName(e.target.value)}
                maxLength={255}
                className="mt-1 block w-full border border-border bg-bg-elevated px-2 py-1 text-text-primary"
              />
            </label>
          )}

          {action === "move" && (
            <label className="mt-3 block text-sm text-text-secondary">
              Move into
              <select
                ref={firstRef}
                value={parent}
                onChange={(e) => setParent(e.target.value)}
                className="mt-1 block w-full border border-border bg-bg-elevated px-2 py-1 text-text-primary"
              >
                <option value={TOP_LEVEL}>Top level</option>
                {moveTargets(tree, folder.id).map((f) => (
                  <option key={f.id} value={f.id}>
                    {f.name}
                  </option>
                ))}
              </select>
            </label>
          )}

          {doomed && (
            <div id="folder-dialog-consequence" className="mt-3 space-y-2 text-sm text-text-secondary">
              <p>
                {doomed.subfolders > 0
                  ? `This folder and its ${plural(doomed.subfolders, "subfolder")} will be removed. `
                  : "This folder will be removed. "}
                <strong className="text-text-primary">
                  {doomed.files > 0
                    ? `${plural(doomed.files, "file")} filed only here will be deleted, with every version.`
                    : "No files will be deleted."}
                </strong>
              </p>
              <p>
                Files also in another folder stay there. Research that cited a deleted file
                keeps the quotes it gathered.
              </p>
            </div>
          )}

          <div className="mt-5 flex justify-end gap-2">
            <button
              ref={action === "delete" ? firstRef : undefined}
              type="button"
              className="btn btn-secondary"
              onClick={onClose}
              disabled={pending}
            >
              Cancel
            </button>
            <button
              type="submit"
              className={action === "delete" ? "btn btn-danger" : "btn btn-primary"}
              disabled={pending || (action === "rename" && !name.trim())}
            >
              {action === "rename" ? "Rename" : action === "move" ? "Move" : "Delete folder"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
