import { describe, expect, it } from "vitest";

import {
  buildTree,
  filterTree,
  folderDeletion,
  folderState,
  moveTargets,
  selectionRequest,
  toggleDocument,
  toggleFolder,
  type CorpusTree,
} from "./corpusTree";

const TREE: CorpusTree = {
  folders: [
    { id: "f-thesis", parent_id: null, name: "Thesis" },
    { id: "f-ch1", parent_id: "f-thesis", name: "Ch1" },
    { id: "f-ch2", parent_id: "f-thesis", name: "Ch2" },
    { id: "f-empty", parent_id: null, name: "Empty" },
  ],
  documents: [
    { id: "d1", filename: "a.pdf", doc_key: "k1", origin: "uploaded" },
    { id: "d2", filename: "b.xlsx", doc_key: "k2", origin: "uploaded" },
    { id: "d3", filename: "c.docx", doc_key: "k3", origin: "uploaded" },
    { id: "d4", filename: "loose.txt", doc_key: "k4", origin: "uploaded" },
    { id: "d5", filename: "report-1.md", doc_key: "k5", origin: "generated" },
    { id: "d6", filename: "old.pdf", doc_key: "k6", origin: "uploaded", is_current: false },
  ],
  memberships: [
    { doc_key: "k1", folder_id: "f-ch1", display_name: "a.pdf" },
    { doc_key: "k2", folder_id: "f-ch1", display_name: "b.xlsx" },
    { doc_key: "k3", folder_id: "f-ch2", display_name: "c.docx" },
    { doc_key: "k1", folder_id: "f-ch2", display_name: "a.pdf" },
  ],
};

describe("corpusTree", () => {
  const { roots, loose } = buildTree(TREE);
  const thesis = roots.find((r) => r.folder.name === "Thesis")!;
  const ch1 = thesis.folders.find((f) => f.folder.name === "Ch1")!;

  it("nests folders, files documents, and puts unfiled ones at the root", () => {
    expect(roots.map((r) => r.folder.name)).toEqual(["Empty", "Thesis"]);
    expect(thesis.folders.map((f) => f.folder.name)).toEqual(["Ch1", "Ch2"]);
    expect(ch1.documents.map((d) => d.filename)).toEqual(["a.pdf", "b.xlsx"]);
    expect(loose.map((d) => d.filename)).toEqual(["loose.txt"]);
  });

  it("never offers generated reports or superseded versions", () => {
    const names = [...loose, ...thesis.folders.flatMap((f) => f.documents)].map((d) => d.filename);
    expect(names).not.toContain("report-1.md");
    expect(names).not.toContain("old.pdf");
  });

  it("shows a half-selected folder as mixed and an empty one as unchecked", () => {
    expect(folderState(thesis, new Set(["k1"]))).toBe("mixed");
    expect(folderState(ch1, new Set(["k1", "k2"]))).toBe("checked");
    expect(folderState(roots[0], new Set(["k1"]))).toBe("unchecked");
  });

  it("toggles a whole folder, subfolders included, and clears a full one", () => {
    const all = toggleFolder(thesis, new Set());
    expect([...all].sort()).toEqual(["k1", "k2", "k3"]);
    expect(toggleFolder(thesis, all).size).toBe(0);
    expect([...toggleDocument("k4", all)].sort()).toEqual(["k1", "k2", "k3", "k4"]);
  });

  it("sends whole folders as ids and the rest as files", () => {
    const selected = new Set(["k1", "k2", "k4"]);
    expect(selectionRequest(roots, loose, selected)).toEqual({
      folder_ids: ["f-ch1"],
      doc_keys: ["k4"],
    });
    expect(selectionRequest(roots, loose, toggleFolder(thesis, new Set()))).toEqual({
      folder_ids: ["f-thesis"],
      doc_keys: [],
    });
  });

  it("filters by name and keeps the path to a match", () => {
    const filtered = filterTree(roots, "xlsx");
    expect(filtered.map((r) => r.folder.name)).toEqual(["Thesis"]);
    expect(filtered[0].folders.map((f) => f.folder.name)).toEqual(["Ch1"]);
    expect(filtered[0].folders[0].documents.map((d) => d.filename)).toEqual(["b.xlsx"]);
  });

  it("counts what a folder delete removes: files filed nowhere else, and subfolders", () => {
    // k2 is only in Ch1, k3 only in Ch2, k1 in both: deleting Thesis takes all three.
    expect(folderDeletion(TREE, "f-thesis")).toEqual({ subfolders: 2, files: 3 });
    // Deleting Ch1 alone leaves k1, which Ch2 still holds.
    expect(folderDeletion(TREE, "f-ch1")).toEqual({ subfolders: 0, files: 1 });
    expect(folderDeletion(TREE, "f-empty")).toEqual({ subfolders: 0, files: 0 });
  });

  it("never offers a folder itself or anything beneath it as a place to move it", () => {
    expect(moveTargets(TREE, "f-thesis").map((f) => f.id)).toEqual(["f-empty"]);
    expect(moveTargets(TREE, "f-ch1").map((f) => f.id)).toEqual(["f-ch2", "f-empty", "f-thesis"]);
  });
});
