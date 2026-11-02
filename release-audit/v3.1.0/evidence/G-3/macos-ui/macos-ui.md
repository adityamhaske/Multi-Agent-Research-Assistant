# G-3 macOS — the released 3.0.2 app's UI on 3.1 data (2026-11-01)

- **Installer:** `Research.Assistant_3.0.2_aarch64.dmg` from the v3.0.2 GitHub release,
  sha256 `827c6a0443117b9092fe2e5c885a0f990c065a0e80ed2375f2a55fd1d688cc01`, identical to its
  line in the release's `SHA256SUMS`. The app was copied out of the mounted image unchanged.
- **Binaries:** 6450e020118842d52bbfa5f7828f0e1502e74e796700ef73d30b8c0deea7a71b  Research Assistant.app/Contents/MacOS/research-desktop
- **Data:** `python scripts/gates/g3_downgrade_open.py prepare` at this checkout. Each
  directory was copied into a scratch `HOME/.research-engine` and the app launched with
  `open -n --env HOME=… --env PYTHON_KEYRING_BACKEND=null`. Embeddings came from local Ollama
  `nomic-embed-text`.
- **Driven:** by hand-equivalent clicks (Claude computer-use) on this Mac. The engine-level
  checks, search included, are in `macOS-local.json` and the CI JSONs.

| Directory | Expected (`expect.json`) | Observed in the 3.0.2 UI | Result |
|---|---|---|---|
| `restored` | 8 legacy documents | Corpus page lists 8 documents, 11 chunks, two GENERATED reports marked | PASS (`restored-01-…`) |
| `corpus31` (3.1-written store: new kinds, folders, a revision) | 7 documents, no crash | Lists all 7, report.docx, budget.xlsx, deck.pptx and stats.py included. Previewing the .docx says "No preview for this file type. Download it to open in its own application." Nothing crashes | PASS (`corpus31-01-…`, `corpus31-02-…`) |
