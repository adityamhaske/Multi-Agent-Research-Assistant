/**
 * The corpus as a folder tree, and the selection a user makes in it (RFC V3.1 §12).
 *
 * Pure functions, so the rules that decide what a research run may read are tested without
 * a browser: which documents a folder checkbox covers, what a half-selected folder shows,
 * and the request a selection becomes. The server re-resolves that request and freezes it
 * (`corpus_selection.freeze_selection`); nothing here is trusted beyond being a request.
 */

export type TreeFolder = { id: string; parent_id: string | null; name: string };
export type TreeDocument = {
  id: string;
  filename: string;
  doc_key?: string | null;
  origin?: string;
  is_current?: boolean;
};
export type TreeMembership = { doc_key: string; folder_id: string; display_name: string };
export type CorpusTree = {
  folders: TreeFolder[];
  documents: TreeDocument[];
  memberships: TreeMembership[];
};

export type FolderNode = {
  folder: TreeFolder;
  folders: FolderNode[];
  documents: TreeDocument[];
};

export type CheckState = "checked" | "unchecked" | "mixed";

/** Documents that can be selected: current, uploaded versions — never auto-saved reports. */
export function selectable(doc: TreeDocument): boolean {
  return doc.origin !== "generated" && doc.is_current !== false && !!doc.doc_key;
}

/** The folder tree, plus the documents filed in no folder (shown at the root). */
export function buildTree(tree: CorpusTree): { roots: FolderNode[]; loose: TreeDocument[] } {
  const nodes = new Map<string, FolderNode>();
  for (const folder of tree.folders) nodes.set(folder.id, { folder, folders: [], documents: [] });
  const roots: FolderNode[] = [];
  for (const node of nodes.values()) {
    const parent = node.folder.parent_id ? nodes.get(node.folder.parent_id) : undefined;
    (parent ? parent.folders : roots).push(node);
  }
  const byKey = new Map<string, TreeDocument>();
  for (const doc of tree.documents.filter(selectable)) byKey.set(doc.doc_key as string, doc);
  const filed = new Set<string>();
  for (const m of tree.memberships) {
    const doc = byKey.get(m.doc_key);
    const node = nodes.get(m.folder_id);
    if (doc && node) {
      node.documents.push(doc);
      filed.add(m.doc_key);
    }
  }
  const sortNode = (node: FolderNode) => {
    node.folders.sort((a, b) => a.folder.name.localeCompare(b.folder.name));
    node.documents.sort((a, b) => a.filename.localeCompare(b.filename));
    node.folders.forEach(sortNode);
  };
  roots.sort((a, b) => a.folder.name.localeCompare(b.folder.name));
  roots.forEach(sortNode);
  const loose = [...byKey.values()]
    .filter((d) => !filed.has(d.doc_key as string))
    .sort((a, b) => a.filename.localeCompare(b.filename));
  return { roots, loose };
}

/** Every selectable document key in a folder and all its subfolders. */
export function keysUnder(node: FolderNode): Set<string> {
  const out = new Set<string>();
  const walk = (n: FolderNode) => {
    n.documents.forEach((d) => out.add(d.doc_key as string));
    n.folders.forEach(walk);
  };
  walk(node);
  return out;
}

/** What a folder's checkbox shows for the current selection. An empty folder is unchecked. */
export function folderState(node: FolderNode, selected: ReadonlySet<string>): CheckState {
  const keys = keysUnder(node);
  if (keys.size === 0) return "unchecked";
  let hit = 0;
  for (const key of keys) if (selected.has(key)) hit += 1;
  return hit === 0 ? "unchecked" : hit === keys.size ? "checked" : "mixed";
}

/** Toggle a folder: a fully checked folder clears; anything else selects all beneath it. */
export function toggleFolder(node: FolderNode, selected: ReadonlySet<string>): Set<string> {
  const keys = keysUnder(node);
  const next = new Set(selected);
  if (folderState(node, selected) === "checked") keys.forEach((k) => next.delete(k));
  else keys.forEach((k) => next.add(k));
  return next;
}

export function toggleDocument(docKey: string, selected: ReadonlySet<string>): Set<string> {
  const next = new Set(selected);
  if (next.has(docKey)) next.delete(docKey);
  else next.add(docKey);
  return next;
}

/** The request a selection becomes: whole folders by id, the rest as individual files.
 *
 * The smallest cover, so selecting a folder of a thousand files sends one id rather than a
 * thousand. The server expands folders at the moment the run is created, so the run reads
 * exactly the files in the folder then.
 */
export function selectionRequest(
  roots: FolderNode[],
  loose: TreeDocument[],
  selected: ReadonlySet<string>,
): { folder_ids: string[]; doc_keys: string[] } {
  const folderIds: string[] = [];
  const covered = new Set<string>();
  const walk = (node: FolderNode) => {
    if (folderState(node, selected) === "checked") {
      folderIds.push(node.folder.id);
      keysUnder(node).forEach((k) => covered.add(k));
      return;
    }
    node.folders.forEach(walk);
  };
  roots.forEach(walk);
  const all = new Set<string>();
  roots.forEach((r) => keysUnder(r).forEach((k) => all.add(k)));
  loose.forEach((d) => all.add(d.doc_key as string));
  const docKeys = [...selected].filter((k) => all.has(k) && !covered.has(k)).sort();
  return { folder_ids: folderIds.sort(), doc_keys: docKeys };
}

/** Folders and documents whose name or path contains `query`, keeping their ancestors. */
export function filterTree(roots: FolderNode[], query: string): FolderNode[] {
  const q = query.trim().toLowerCase();
  if (!q) return roots;
  const walk = (node: FolderNode): FolderNode | null => {
    const nameHit = node.folder.name.toLowerCase().includes(q);
    const folders = node.folders.map(walk).filter((n): n is FolderNode => n !== null);
    const documents = nameHit
      ? node.documents
      : node.documents.filter((d) => d.filename.toLowerCase().includes(q));
    if (nameHit || folders.length || documents.length) return { ...node, folders, documents };
    return null;
  };
  return roots.map(walk).filter((n): n is FolderNode => n !== null);
}
