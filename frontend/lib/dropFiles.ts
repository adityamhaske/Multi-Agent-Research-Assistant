/**
 * Every file in a drag-and-drop, folders walked recursively, each with its path inside the
 * dropped folder — the same shape the folder picker gives through `webkitRelativePath`.
 *
 * `DataTransfer.files` lists only the top-level items and, for a dropped folder, nothing a
 * page can read; the entry API (`webkitGetAsEntry`) is the only way to walk into one. Where a
 * webview lacks it, the drop falls back to the plain file list, so files still upload and a
 * folder simply arrives without its structure — the page says so rather than claiming more.
 */

export type DroppedFile = { file: File; path?: string };

function fileOf(entry: FileSystemFileEntry): Promise<File> {
  return new Promise((resolve, reject) => entry.file(resolve, reject));
}

async function childrenOf(entry: FileSystemDirectoryEntry): Promise<FileSystemEntry[]> {
  const reader = entry.createReader();
  const all: FileSystemEntry[] = [];
  // `readEntries` returns entries in batches and an empty batch when done.
  for (;;) {
    const batch = await new Promise<FileSystemEntry[]>((resolve, reject) =>
      reader.readEntries(resolve, reject),
    );
    if (!batch.length) return all;
    all.push(...batch);
  }
}

async function walk(entry: FileSystemEntry, out: DroppedFile[]): Promise<void> {
  if (entry.isFile) {
    const file = await fileOf(entry as FileSystemFileEntry);
    const path = entry.fullPath.replace(/^\//, "");
    out.push({ file, path: path.includes("/") ? path : undefined });
    return;
  }
  if (entry.isDirectory) {
    for (const child of await childrenOf(entry as FileSystemDirectoryEntry)) await walk(child, out);
  }
}

/** Whether this browser can walk a dropped folder at all. */
export function canWalkFolders(dt: DataTransfer): boolean {
  const item = dt.items?.[0];
  return !!item && typeof item.webkitGetAsEntry === "function";
}

export async function filesFromDrop(dt: DataTransfer): Promise<DroppedFile[]> {
  if (!canWalkFolders(dt)) return Array.from(dt.files).map((file) => ({ file }));
  // Entries must be taken synchronously, before the drop event's data store is cleared.
  const entries = Array.from(dt.items)
    .map((item) => item.webkitGetAsEntry())
    .filter((e): e is FileSystemEntry => e !== null);
  const out: DroppedFile[] = [];
  for (const entry of entries) await walk(entry, out);
  return out;
}
