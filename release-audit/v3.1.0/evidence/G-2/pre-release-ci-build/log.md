# G-2 macOS (WKWebView) — computer-use pass

Build: CI run 41089930104 (main 2ba347d), artifact research-desktop-shell-macos-latest,
launched with a throwaway HOME and PYTHON_KEYRING_BACKEND=null; embeddings ollama:nomic-embed-text.

| # | Step | Observed | Result |
|---|---|---|---|
| 1 | Corpus page, empty project General | Drop zone, "Choose files", "Choose folder" | — |
| 2 | Click "Choose folder" | Native macOS Open panel (window "Open") | PASS |
| 3 | Click Cancel in the panel | Panel closes; page unchanged, no error, no upload | PASS |
| 4 | "Choose folder" → Go to fixtures/ → select `Thesis` → Open | Queue: Thesis/ch1/intro.txt, Thesis/ch1/notes/solar.md, Thesis/ch2/wind.txt ADDED (3/3); tree Thesis → ch1, ch2 | PASS |
| 5 | `Thesis/locked` is `chmod 000` (unreadable) | Its file is absent from the queue and the tree; **no message tells the user a subfolder was skipped** | FINDING |
| 6 | Drag folder `Dropped` from Finder onto the drop zone (real drag session; drag image over the zone) | Zone never highlights; drop uploads nothing. Tauri's native drag-drop handler takes the drop before the page | **FAIL** — fix: `disable_drag_drop_handler()` |
| 7 | Delete on folder `Thesis` | Alert dialog: "This folder and its 3 subfolders will be removed. 3 files filed only here will be deleted, with every version." Cancel / Delete folder | PASS (Cancel pressed; nothing removed) |
| 8 | Preview `Thesis/ch1/notes/solar.md` | Drawer renders the Markdown | PASS |
| 9 | Download from the preview | `$HOME/Downloads/solar.md`, 55 bytes, `cmp` identical to the source file | PASS |
| 10 | Engine without the app's token: `GET /api/v1/corpus/documents` with no token / a wrong bearer | 401 / 401 | PASS |
| 11 | Choose folder `big` (40 × 628 KB), click "Stop uploading" while file 3 uploads | Button reads "Stopping after this file…"; queue ends 3/40 completed, the other 37 SKIPPED | PASS |
| 12 | **Fixed build** (main 2ba347d + `disable_drag_drop_handler()`, built locally with the same CI sidecar): drag `Dropped` from Finder (window moved clear of the app) | Zone tints while dragging; on drop the folder uploads nested — corpus store: folder `Dropped` (root) ⊃ `inner`, memberships Dropped/top.txt, inner/deep.txt | PASS |
| 13 | **Unfixed CI build**, identical geometry (Finder clear of the window), drag `Dropped2` | No tint while dragging; nothing uploads; corpus store has no `Dropped2` folder | FAIL — confirms step 6 is the shell, not the test |

Step 6's first attempt overlapped Finder and the app window, and an attempt on the fixed build in that geometry also failed, so 12 and 13 repeat the drag with nothing overlapping on both builds: only the fixed build receives it.

Screenshots of this pre-release pass are not committed. The scratch corpus also held files the
owner picked during the session, unrelated to the test, and their names are visible in most
frames. The release-build pass in `../release-build/` starts from an empty home, and its
screenshots are committed.
