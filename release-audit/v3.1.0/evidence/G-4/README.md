# G-4 — bundle compatibility on real selected-files runs (2026-11-02)

- **Bundles:** two real selected-files runs, made by `scripts/gates/g4_real_bundles.py` through the
  desktop engine's own routes (`python -m desktop.sidecar`, run from source at `main`
  e747170, which reports its version as `unknown` because a source run is unstamped). Real
  models on `custom:auto/best-fast` (OmniRoute), local `nomic-embed-text` embeddings, a scratch
  data directory and no keychain. Each was approved at the review gate, then exported.
  - `bundle-1.json`: one file, `Reports/report.docx`.
  - `bundle-2.json`: three files in `Mixed/Figures` (xlsx, csv, md).
  - Both runs' grounding reports are `complete`; their `bundle_hash` is in `runs.json`.
- **Check:** `python scripts/gates/g4_bundle_compat.py bundle-1.json bundle-2.json --out …`.
  `g4.json` has every verdict, and the sha256 of the v3.0.2 `verify_bundle.py` (unpacked from
  the tag with `git archive`).
- **Result: PASS.**
  - Both bundles pass under the v3.0.2 verifier and under the 3.1 verifier.
  - A tampered source, selection entry, `grounding_validation` entry or report fails on
    hash under both.
  - A selection rewritten to exclude the cited sources, with `bundle_hash` recomputed,
    fails only `corpus_selection` under 3.1, and passes under v3.0.2, which has no such
    check.
