# G-2 macOS (WKWebView): the release build

- **Build:** `Research Assistant_3.1.0_aarch64.dmg`, sha256 `ea0b471536bdc264cbc940409032198266e0e5b63e8392376091c5aec30c8007`, from Desktop run
  41399061578 of `main` at `c20733e`, the v3.1.0 tag target. The app was copied out of the
  mounted image unchanged and launched with a scratch `HOME` (empty corpus) and no keychain.
  Embeddings come from local Ollama `nomic-embed-text`.
- **Fixtures:** `Thesis/{ch1/intro.txt, ch1/notes/solar.md, ch2/wind.txt, locked/hidden.txt}`,
  with `locked` set `chmod 000`, and 40 × ~628 KB text files.
- **Driven:** Claude computer-use, with the native Open panel and real keys.

| # | Step | Observed | Result |
|---|---|---|---|
| 1 | Choose folder | The native macOS Open panel appears | PASS (frame not committed: it shows the owner's Finder sidebar) |
| 2 | Cancel in the panel | The panel closes; the page is unchanged; nothing uploads | PASS (`02`) |
| 3 | Choose folder → Go to fixtures → select `Thesis` → Open | Queue 3/3: Thesis/ch1/intro.txt, Thesis/ch1/notes/solar.md, Thesis/ch2/wind.txt ADDED. The store has folders Thesis, ch1, notes, ch2 | PASS (`03`) |
| 4 | Unreadable `Thesis/locked` | Left out of the upload, with no message (documented in user guide 39) | OBSERVED |
| 5 | Delete on `Thesis` | "This folder and its 3 subfolders will be removed. 3 files filed only here will be deleted, with every version." Cancel | PASS (`04`) |
| 6 | Preview `solar.md` | The drawer shows its text | PASS (`05`) |
| 7 | Download from the preview | `HOME/Downloads/solar.md`, 55 bytes, `cmp`-identical to the source | PASS |
| 8 | The engine without the app's token: `GET /api/v1/corpus/documents`, with no token and with a wrong bearer | 401 / 401 | PASS |
| 9 | Choose folder → `fixtures` (Thesis plus 40 large files) → Stop uploading during the first large file | "Stopping after this file…"; the queue ends 1/43 completed, the rest SKIPPED | PASS (`06`, `07`) |
| 10 | Drag a folder from Finder onto the drop zone | **Not repeated on this build.** In this session, synthetic pointer input stopped taking effect in full-screen mode: clicks and drags did nothing on any display, while keys still worked. Every step above was driven by accessibility presses and keys. The drop was verified with a real Finder drag on a launched build of `a29d645`, which is #268's fix; see `../pre-release-ci-build/log.md`, steps 12–13. `git diff a29d645 c20733e` over `desktop/src`, `frontend/lib/dropFiles.ts`, the corpus page and `frontend/components/corpus` is **empty**: only the version strings in `Cargo.toml` and `tauri.conf.json` differ. `tests/workflow/test_desktop_drop_reaches_the_page.py` pins the handler line in the release tree | PASS on identical drop code (a launched build of a29d645); not re-driven on c20733e |
