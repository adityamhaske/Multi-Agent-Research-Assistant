# G-1 — Python 3.14 and packaged ingest, macOS arm64 (A-6: macOS only)

The release candidate: `main` at `c20733e` (`c20733ecdf11533483adc4f97e38a18ac80fa70b`), the
v3.1.0 tag target. Its Desktop workflow run is 41399061578, and every job passed.

| Evidence | File |
|---|---|
| The interpreter inside the freeze | `python-VV.txt`: Python 3.14.10 |
| The resolved dependency set | `pip-freeze.txt` |
| A cp314 wheel for every parser on every target, `macosx_11_0_arm64` included | `parser-wheels-all-targets.txt` (from the Linux runner, which downloads for all four targets) |
| The build log | `job-Sidecar--macos-latest.log` (PyInstaller freeze) and `job-Shell--macos-latest.log` (the Tauri bundle and the disk image) |
| AC-25: the frozen engine ingests and queries one fixture of every shipped format exactly as the source tree does | `ingest-frozen.json`. `ingest_fixtures` PASS, and the engine identifies as 3.1.0 at c20733e, `dirty: false`. The Shell job repeats it on the engine inside the published-to-be `.dmg` (`--ingest-fixtures`, PASS, in its log) |

Logs were scanned for the engine's per-launch token before commit: none present.

**Result: PASS.**
