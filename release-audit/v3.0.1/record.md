# Release record — v3.0.1

**A retroactive dry run, not the record of the release.** v3.0.1 was tagged on 2026-09-28,
before this process existed. This record runs today's `RELEASE.md` against what 3.0.1
actually published, on 2026-09-29, from a macOS (Apple Silicon) machine with no Windows or
Linux machine available. Every row says what was checked and how; `NOT RUN` means exactly
that, and is not a pass. It is **not signed off**: approving a release after the fact is not
an approval.

| | |
|---|---|
| Version | v3.0.1 |
| Previous release | v3.0.0 (`e291e1e`) |
| Release manager | — (retroactive dry run) |
| Release commit (tag target) | `d53d6457df1d5b7666fad529f5433616e78bce6a` — merge of #168 |
| Tag | v3.0.1 (annotated), 2026-09-28 13:47 −07:00 |
| Flip PR | #169 — `ef7bc66`, merged as `21e2147` |
| Audit evidence | `post-release.json` in this directory — the post-release stage re-runs every published-stage check; there is no `pre-tag.json` or `published.json` because the tag predates the audit |

Result values: `PASS` · `FAIL` · `N/A` (why it does not apply) · `NOT RUN` (why not) ·
`ACCEPTED` (a known failure the sign-off accepts, with the reason) · `PENDING`.

---

## Scope

Every PR merged between v3.0.0 and v3.0.1 (A2.01). Version rationale (M0.03): **patch** — a
desktop signing fix plus site and docs corrections; no API, schema or bundle-format change.

| Feature / fix | PRs | Implementation | Tests | UI | API | Desktop | Docs | Website | Release notes | Known limitations | Status |
|---|---|---|---|---|---|---|---|---|---|---|---|
| macOS app signed as a whole bundle (no more "damaged") | #168 | `tauri.conf.json` `signingIdentity: "-"` | `desktop.yml` DMG signature step, run against a damaged, a signed and a tampered image | — | — | ✓ macOS | ✓ 23-desktop-app, 24-troubleshooting | ✓ download card | ✓ releases.ts, changelog, Release body | ✓ still not notarized | Shipped |
| Install steps that work (one `xattr -dr` command on every surface) | #168 | download page, guides, release body | `download/page.test.tsx`; A12.02 | ✓ | — | ✓ | ✓ | ✓ | ✓ | — | Shipped |
| Releases page version index and folded summaries; homepage features | #167 | `releases/page.tsx`, `ReleaseNav.tsx`, `features.ts` | `releases/page.test.tsx`, `releases.test.ts`, `activeSection.test.ts`, `features.test.ts` | ✓ site | — | n/a | — | ✓ | — (site only) | — | Shipped |
| Guides brought up to 3.0.0 and the run pipeline | #167 | `docs/user-guide/*`, `docs/getting-started/*` | A12.01 (links) | — | — | — | ✓ | ✓ (rendered docs) | — | — | Shipped |
| v3.0.0 offered for download (the previous release's flip) | #166 | `releases.ts` | `download/unreleased.test.tsx` | ✓ | — | — | — | ✓ | — | — | Shipped (process) |

Deferred: none.

## Desktop artifacts (M6.01)

| Artifact | SHA-256 | OS | Arch | Version (installed) | Engine git SHA | Install | Launch | Journey |
|---|---|---|---|---|---|---|---|---|
| `Research.Assistant_3.0.1_aarch64.dmg` | `8b863081…271a243c` ✓ | macOS | arm64 | 3.0.1 (Info.plist) | `d53d6457` (packaged) | mounted, not installed — NOT RUN | engine: PASS (packaged); GUI: NOT RUN | engine: PASS, verifier PASS (packaged) |
| `Research.Assistant_3.0.1_x64_en-US.msi` | `254daa18…e98d1` ✓ (GitHub digest) | Windows | x64 | NOT RUN — no machine | raw engine only, in CI (source of the bundle, not the MSI) | NOT RUN | NOT RUN | NOT RUN |
| `Research.Assistant_3.0.1_amd64.AppImage` | `95cdeb1b…6e06` ✓ (GitHub digest) | Linux | x86-64 | NOT RUN — no machine | raw engine only, in CI | n/a | NOT RUN | NOT RUN |
| `Research.Assistant_3.0.1_amd64.deb` | `6cd4e70a…c2fa` ✓ (GitHub digest) | Linux | x86-64 | NOT RUN — no machine | raw engine only, in CI | NOT RUN | NOT RUN | NOT RUN |

Full hashes, and the downloaded-bytes verification of all four, are in `post-release.json` (A11.05, A11.06).

## Container images

| Image | Digest (`3.0.1` = `3.0` = `latest`) | amd64 | arm64 | Provenance revision | Runs (M10.x) |
|---|---|---|---|---|---|
| api | `sha256:d70c12a4…9584a` | ✓ manifest | ✓ manifest | `d53d6457` both | arm64: PASS; reports `git_sha: unknown` |
| worker | `sha256:8ebbc49b…cb826` | ✓ manifest | ✓ manifest | `d53d6457` both | arm64: PASS |
| frontend | `sha256:79fb4c3d…fe3a6` | ✓ manifest | ✓ manifest | `d53d6457` both | arm64: PASS |

## Automated audit

| Stage | Command | Verdict | Counts | Evidence |
|---|---|---|---|---|
| pre-tag | — | not run | — | the tag predates the audit |
| published | — | covered by post-release | — | every published-stage check re-ran below |
| post-release | `release_audit.py --version 3.0.1 --post-release --download --docker` | STOP | 56 PASS, 3 WARN, 3 FAIL, 0 UNAVAILABLE | `post-release.json` (2026-09-29T12:28:14+00:00) |

Disposition of every non-PASS result (M21.01):

| Check | Result | Disposition |
|---|---|---|
| A6.02 | WARN | The three installer guards did not exist at this tag: the 3.0.1 `.deb`, AppImage and `.msi` were never installed or launched by CI. Recorded as a gap of this release; the guards run from the next tag |
| A10.05 | FAIL | Product defect #1: the published images are unstamped (`git_sha: unknown`). Not fixable in 3.0.1's images without a re-release; fixed in `release.yml` for the next tag |
| A16.03 | WARN | Documentation defect #4: two historical dates differ from their tags by a day. Left for the owner |
| A17.02 | WARN | The live site predates `build.json`; A17.01 (deployment `21e2147` = `origin/main`, success) is the evidence of what is served |
| A21.01 | FAIL | Two manual FAILs (M4.02, M15.01) and no sign-off — correct for a retroactive dry run, which approves nothing |
| A22.01 | FAIL | This record is not on `main` until the release-process PR merges; re-run then |

## Manual checks

| ID | Result | Check — evidence |
|---|---|---|
| **Phase 0 — Release Scope Freeze** | | |
| M0.01 | PASS | Create the release record — Created retroactively on 2026-09-29 for this dry run; the process did not exist when 3.0.1 shipped |
| M0.02 | PASS | Freeze the scope: list every feature and fix in the record's Scope table, each with its PR numbers — Scope table below: #166, #167, #168 are every merge between v3.0.0 (e291e1e) and v3.0.1 (d53d645); A2.01 PASS |
| M0.03 | PASS | Choose the version number and record why: major for a breaking change (API contract, bundle format a… — Patch: a desktop signing fix, site and docs corrections; no API, schema or bundle-format change (`git diff --stat v3.0.0..v3.0.1 -- backend` = APP_VERSION only) |
| M0.04 | PASS | Carry forward known limitations: start this release's `known` from the previous release's, and remove an… — releases.ts v3.0.1 `known` carries 3.0.0's list; the one removed item (the macOS Gatekeeper description) is replaced by the corrected one, with the fix as evidence |
| **Phase 1 — Repository / Version Consistency** | | |
| M1.01 | PASS | Bump and derive, in this order: `VERSION`; the new `releases.ts` entry at the top with `unreleased: true`… — At the tag: sync_version consistent across 4 files, Cargo.lock 3.0.1, entry `unreleased: true`, changelog `— unreleased` (A1.13 PASS) |
| M1.02 | PASS | Search for stale references the scanner cannot see: images and screenshots with text in them, the… — A1.09 scan: 44 references, all historical (release-audit/historical-references.json); `git grep releases/download/` at the tag: only the page's template and pinned test fixtures; no hard-coded image tag outside internal/ |
| M1.03 | PASS | Review every line A1.09 flags, one by one — All 44 reviewed with a reason each; one stale literal found and reported (download/page.tsx fallback `v2.0.2`, unreachable) |
| **Phase 2 — Feature Completeness** | | |
| M2.01 | PASS | Fill the feature matrix in the record for every scope row: Implementation · Tests · UI · API · Desktop ·… — Matrix below |
| M2.02 | N/A | For every feature on both hosts, confirm the desktop really has it: the route exists and behaves… — No feature with a server/desktop contract changed: the signing fix is desktop-only by nature; site and docs are host-independent |
| M2.03 | PASS | Read the `releases.ts` entry and the changelog entry against the matrix: `improved` states user-visible… — Read against the matrix: `improved` is user-visible, `known` includes the still-unnotarized build; summaries add nothing (A1.05 PASS) |
| M2.04 | N/A | If A2.03 fails: run the release evaluation (`docs/developers/08-testing-and-evaluation.md`, "The release… — A2.03 PASS — no quality-affecting path changed since v3.0.0 |
| **Phase 3 — Automated Testing** | | |
| M3.01 | PASS | Explain every re-run: any required job on the release commit that passed only on a retry is recorded with… — Every run on d53d645 and the tag was attempt 1 (CI, Desktop ×2, Pages, Release) |
| M3.02 | PASS | Read the non-blocking dependency-audit output of the release commit's CI run — Release-commit CI run 36481603358: `npm audit` found 0 vulnerabilities (frontend, golden-e2e); `pip-audit` No known vulnerabilities found |
| **Phase 4 — Backend / API Verification** | | |
| M4.01 | N/A | If `backend/app/api/` changed since the previous release, `docs/reference/34-api.md` and `35-sse.md`… — backend/app/api and the sidecar unchanged between v3.0.0 and v3.0.1 |
| M4.02 | FAIL | On the published images (Phase 10 stack), probe the boundaries: an unauthenticated `GET /api/v1/projects`… — On the published images: unauthenticated /projects 401; wrong password and unknown user return the identical 401 (no enumeration); /health 3.0.1; /health/ready 200 — but /api/v1/version answers `unknown`: release.yml never stamped the images (fixed for the next release: stamp job + image step) |
| **Phase 5 — Frontend Verification** | | |
| M5.01 | NOT RUN | On the Phase 10 stack, open dashboard, a project, a finished run (report, evidence, citations), Settings… — Visual pass over the app screens not done in this dry run |
| M5.02 | NOT RUN | Keyboard-only pass over the two gates: plan approval and report approval are reachable and operable… — Keyboard pass over the gates not done in this dry run |
| **Phase 6 — Desktop Application Verification** | | |
| M6.01 | PASS | Record the artifact table in the record for all four installers: file name · SHA-256 · OS · architecture ·… — Artifact table below; every blank carries its NOT RUN reason |
| M6.02 | NOT RUN | On every platform, run the packaged-engine checker against the **installed** copy of the **published**… — macOS PASS (engine inside the published DMG, journey + verifier); Windows and Linux not run — no machine, and CI at this tag never installed or launched those installers (the steps are new) |
| M6.03 | PASS | Mark every desktop row in the record as *packaged* or *source* — Every desktop row below says packaged or source |
| **Phase 7 — macOS Verification** | | |
| M7.01 | PASS | Download the `.dmg` from the release in a browser (so it carries the quarantine flag) and verify it — SHA256SUMS: Research.Assistant_3.0.1_aarch64.dmg OK. Fetched with curl, which sets no quarantine flag, so M7.04 applied it by hand |
| M7.02 | PASS | The DMG opens and holds the app at the right version — Mounted: the app and an Applications link; CFBundleShortVersionString 3.0.1; 146 MB (not ~5 MB) |
| M7.03 | PASS | The signature is whole and valid — flags=0x10002(adhoc,runtime), not linker-signed; Sealed Resources version=2 files=276; valid on disk; satisfies its Designated Requirement |
| M7.04 | PASS | Gatekeeper judges a quarantined copy as policy, not damage — Quarantined copy: `spctl --assess --type execute` → rejected (a policy verdict, not damage) |
| M7.05 | PASS | The bundled engine is present, native, and unmodified by hardened runtime — research-sidecar: Mach-O 64-bit executable arm64; flags=0x2(adhoc), no hardened runtime |
| M7.06 | PASS | The packaged engine identifies itself and completes the journey — check_packaged_sidecar.py on the mounted DMG: 138 MB tree, 401 without token, version 3.0.1, git_sha d53d6457 (not dirty), plan → review → export → bundle v2, verify_bundle PASS |
| M7.07 | NOT RUN | First launch as a user: drag to Applications; open it *without* the command and confirm the block is the… — Installing would replace the owner's installed 3.0.0 and open their real data directory; left for the owner (the 3.0.1 release notes record a Mac launch at tag time, without a record of the steps) |
| M7.08 | NOT RUN | The Phase 20 desktop journey on macOS (M20.02) — See M20.02 |
| M7.09 | NOT RUN | Quit the app; no engine is left running — Needs the GUI launch in M7.07 |
| **Phase 8 — Windows Verification** | | |
| M8.01 | NOT RUN | Download the `.msi` in a browser; verify it — No Windows machine available to this dry run |
| M8.02 | NOT RUN | SmartScreen shows the unknown-publisher warning; **More info → Run anyway** proceeds, exactly as the… — No Windows machine |
| M8.03 | NOT RUN | Install completes; Start-menu entry exists; Settings → Apps shows version `X.Y.Z`; files under `C:\Program… — No Windows machine |
| M8.04 | NOT RUN | Launch: the window opens without a crash; Task Manager shows `research-sidecar.exe`; no firewall prompt… — No Windows machine |
| M8.05 | NOT RUN | `python scripts\check_packaged_sidecar.py --search "C:\Program Files\Research Assistant" --expect-sha <tag… — No Windows machine; CI at this tag smoke-tested the raw PyInstaller engine on Windows, never the installed MSI |
| M8.06 | NOT RUN | The Phase 20 desktop journey on Windows (M20.02), from a user whose profile path has a space; exports save… — No Windows machine |
| M8.07 | NOT RUN | Local storage: data under `%USERPROFILE%\.research-engine`; provider keys in Windows Credential Manager,… — No Windows machine |
| M8.08 | NOT RUN | Quit: `research-sidecar.exe` exits (the watchdog — two Windows-only crashes lived here, #113) — No Windows machine |
| M8.09 | NOT RUN | Uninstall from Settings → Apps: the Program Files directory is removed; user data remains (as documented) — No Windows machine |
| **Phase 9 — Linux Verification** | | |
| M9.01 | NOT RUN | AppImage: download, verify (`sha256sum -c SHA256SUMS --ignore-missing`), `chmod +x`, launch from a desktop… — No Linux desktop session; CI at this tag never extracted the AppImage |
| M9.02 | NOT RUN | `.deb`: `sudo apt install ./Research.Assistant_X.Y.Z_amd64.deb` on a clean supported Ubuntu LTS resolves… — No Linux machine; CI at this tag never installed the .deb |
| M9.03 | NOT RUN | Key storage uses the Secret Service keyring; on a session without one, the app says so rather than storing… — No Linux desktop session |
| M9.04 | NOT RUN | `sudo apt remove research-assistant` removes the application; user data remains; no engine left running — No Linux machine |
| **Phase 10 — Docker / Container Verification** | | |
| M10.01 | PASS | Run the published images on the full-stack topology, on their own volumes: — Published 3.0.1 images via release-audit/compose.published-images.yml: five services healthy; api log shows alembic upgrade 0001 → head |
| M10.02 | PASS | On that stack: register, log in, create a project, run a fake-mode research through both gates, export… — Register, login, project, fake-mode run through both gates; export.md 200, export.pdf 200 (real %PDF), bundle.json 200 — v2, demo-stamped, verify_bundle 7/7 PASS |
| M10.03 | PASS | On an arm64 host (Apple Silicon Docker or the Ampere target), the same stack starts from the same tags — This host is Apple Silicon, so M10.01-M10.02 ran the arm64 images (docker image inspect: arm64 ×3). amd64 runtime was not run; A10.01 proves only that the amd64 manifests exist |
| M10.04 | PASS | Tear down with `down -v` using the same flags; the developer's own `mara_full_*` volumes are untouched — `down -v` removed only release_check_*; mara_full_* intact |
| **Phase 11 — GitHub Release Verification** | | |
| M11.01 | PASS | Add the hand-written summary at the top of the Release body (what changed for users, the macOS… — Hand-written summary at the top, links the changelog's Known; both appended sections present (A11.07) |
| **Phase 12 — Documentation Verification** | | |
| M12.01 | PASS | For each scope row, the docs describe what shipped — on both hosts, with desktop differences stated… — 23-desktop-app and 24-troubleshooting describe the signed bundle and the one command; changelog updated |
| M12.02 | N/A | Configuration: every environment variable added, renamed or removed since the previous release (`git diff… — No change to app/config.py, research_engine/local.py or .env.example between the tags |
| M12.03 | PASS | Search the docs for removed or renamed features, commands and routes named in the diff (`git diff --stat… — No feature removed or renamed; docs diff is additive (agent instructions, 3.0.0 catch-up) |
| M12.04 | N/A | Architecture docs (`docs/architecture/02`, `04`) match the graph's nodes and gates — Graph unchanged |
| M12.05 | PASS | Known limitations agree across `releases.ts` `known`, the changelog **Known**, the Release body and the… — releases.ts known, changelog Known ("everything under 3.0.0 still applies"), and the Release body's changelog link agree |
| **Phase 13 — README Verification** | | |
| M13.01 | PASS | Read the README top to bottom against the release: the feature list (nothing unreleased, nothing removed),… — Features, platforms (Apple Silicon/x64/x86-64), commands and the measured claim (A1.14) current |
| **Phase 14 — Landing Page Verification** | | |
| M14.01 | PASS | View `/` at desktop width and at 375 px, light and dark: hero, download call-to-action, "New in" link to… — Live `/` at desktop width and 375 px: "New in v3.0.1", CTA to /download, feature cards. Light mode only — dark not checked |
| M14.02 | PASS | `/why`: every comparison claim (`frontend/lib/comparison.ts`) still holds for this release — No comparison claim touched by 3.0.1 |
| **Phase 15 — Download Page Verification** | | |
| M15.01 | FAIL | On each OS (or with a UA override), the detected-OS card leads; the big button and every card button point… — Buttons, selector (v3.0.1 latest), macOS card and steps correct — but the size note says ~80 MB download / ~180 MB installed; 3.0.1 is 70.3 MiB and 146 MB installed (−19%). Same numbers in docs/getting-started/23-desktop-app.md (81/182 MB). Documentation defect, reported, not fixed here |
| M15.02 | NOT RUN | Download one installer by clicking the page's button in a real browser; the file name and checksum are right — A11.06 downloaded and hashed every installer, but not by clicking the page's button in a browser |
| **Phase 16 — Releases Page Verification** | | |
| M16.01 | PASS | View `/releases`: the new entry is first with the tag's date; its summaries are shown and the lists fold… — v3.0.1 first, 2026-09-28, LATEST in the version index, summaries and folded lists, checksums link to the tag |
| **Phase 17 — GitHub Pages / Deployment Verification** | | |
| M17.01 | N/A | If A17.01 fails because `main` moved after the flip, wait for the newer deploy and re-run; if the deploy… — A17.01 PASS |
| **Phase 18 — Security / Configuration Verification** | | |
| M18.01 | PASS | Review `git diff vPREV..HEAD` for debug flags, test accounts, credentials, private URLs, and anything that… — v3.0.0..v3.0.1 diff: signing config, one workflow step, version bumps, site and docs; no credentials, debug flags or accounts |
| M18.02 | N/A | If `backend/app/config.py`, the security middleware, auth, or the SSRF guard changed: re-check CORS… — No config, auth, middleware or SSRF change |
| M18.03 | PASS | No secret or env file ships in an artifact — Engine inside the published DMG: one pattern hit, read with grep -ao — `sk-typemathbackground…` in primp.abi3.so, a keyword table, not a key; no .env files. Published api image: no /app/.env |
| M18.04 | PASS | Public surface: `/api/v1/version` is unauthenticated on the server by design; nothing else new is — No new public route |
| **Phase 19 — Upgrade / Migration Verification** | | |
| M19.01 | PASS | Fresh install: an empty database migrates to head (CI), and a fresh desktop data directory starts (M6.02… — CI migration gate on d53d645; a fresh desktop data directory started in M7.06; a fresh Postgres migrated to head in M10.01 |
| M19.02 | N/A | Server upgrade from the previous release: run the previous release's images (`RELEASE_TAG=PREV` with the… — A19.02 PASS: no migration, model or bundle-format change since v3.0.0 |
| M19.03 | N/A | Desktop upgrade from the previous release: install the previous release, create the same data, install… — As M19.02 |
| M19.04 | N/A | Downgrade: CI's round-trip proves the schema reverses; record whether running the previous images against… — As M19.02 |
| M19.05 | N/A | A bundle exported by the previous release verifies with this release's verifier, unchanged (`python -m… — Bundle format unchanged since v3.0.0; v1/v2 fixtures verify in CI (test_bundle_v2_verifier) |
| **Phase 20 — Final End-to-End Production Smoke Test** | | |
| M20.01 | NOT RUN | The web/self-hosted journey on the Phase 10 stack, **with a real provider at least once** (fake mode… — The web journey passed on the published images in fake mode (M10.02); no real-provider run was made in this dry run |
| M20.02 | NOT RUN | The desktop journey on each platform (M7.08, M8.06, M9.01/M9.02), with a real provider or Ollama — The packaged macOS engine completed the journey headlessly (M7.06); no GUI journey on any platform |
| M20.03 | NOT RUN | Negative paths on the published build: an invalid provider key is refused before it is stored; a run… — Auth negatives checked (M4.02); cancel, rework, refresh, worker restart and tampering not exercised on the published build here (covered in CI: gates.spec.ts, test_cancellation_is_authoritative, test_bundle_v2_verifier) |
| M20.04 | NOT RUN | Every `[n]` in the final report resolves on hover to a source and its snippet; an unresolved one renders… — Needs the GUI |
| **Phase 21 — Release Approval** | | |
| M21.01 | PASS | Every WARN and UNAVAILABLE in the published audit has a written disposition in the record — Dispositions below |
| M21.02 | PASS | Known issues are documented everywhere they belong (M12.05), including anything this audit found and the… — Known issues section below; the two defects this dry run found are not yet in releases.ts — they are for the owner to add |
| M21.03 | NOT RUN | The release manager signs the approval block in the record — Retroactive dry run: not an approval, and not signed |
| **Phase 22 — Post-Release Verification** | | |
| M22.01 | PASS | The flip PR: drop `unreleased`, set the entry's `date` to the tag's date, date the changelog heading,… — #169 (ef7bc66, merged 21e2147) dropped `unreleased`, kept the tag date, dated the changelog — without a record or evidence, which this process did not yet require |
| M22.02 | PASS | After Pages deploys: run the post-release audit with `--download --docker`, commit its JSON (write-once)… — Post-release audit run 2026-09-29, saved as post-release.json |
| M22.03 | NOT RUN | Load `/`, `/why`, `/docs`, `/download`, `/releases` on a phone and a desktop browser with the cache disabled — Checked in the browser pane (desktop + 375 px emulation), not on a phone with the cache disabled |
| M22.04 | PASS | In an installed copy of the **previous** desktop release, Settings → About → *Check for updates* reports… — The installed 3.0.0 engine's /updates/check → update_available, latest 3.0.1, release URL …/tag/v3.0.1 |
| M22.05 | N/A | For 48 hours, watch issues and discussions for install or launch reports; any release-blocking report… — Retroactive — the 48 hours are not observable after the fact |
| M22.06 | PASS | Every incident found during this release becomes a check: an `A…` check (preferred) or an `M…` item, plus… — Incidents table below — every defect this dry run found became a check |

## Findings

Separated by kind, as the task asked. None blocks 3.0.1 retroactively; each is dispositioned.

**Current product defects**
1. **The published api and worker images cannot say which commit they are.** `/api/v1/version`
   answers `version: unknown, git_sha: unknown` on every image through 3.0.1 — `release.yml`
   never ran `stamp_build.py` (A10.05 FAIL; M4.02). `/health` still reports 3.0.1. *Fixed for
   the next release* by a `stamp` job and a step that runs each pushed image and compares its
   commit (`release.yml`); first exercised on the next tag.

**Documentation defects**
2. **The deploy guide pulled a pre-1.0 build.** `deploy/oracle-bootstrap.sh` defaulted to
   `IMAGE_TAG=edge`, built on 2026-08-05 from `4904334`, and `deploy/README.md` said `latest`
   "does not exist yet". Fixed in this change (default `latest`; A10.04).
3. **Size claims are stale.** Download page "~80 MB download, ~180 MB installed"; desktop
   guide "around 81 MB … roughly 182 MB". 3.0.1: 70.3 MiB DMG, 146 MB installed (M15.01).
   Not fixed here — the owner's call.
4. **Two historical release dates on the site disagree with their tags** (A16.03, WARN):
   v1.0.0 site 2026-08-14 / tag 2026-08-13 (the GitHub Release says 2026-08-12); v1.0.2 site
   2026-08-15 / tag 2026-08-16. Not fixed — ambiguous which is right for v1.0.0.
5. **A stale literal:** `download/page.tsx` falls back to `"v2.0.2"` if `releases.ts` had no
   released desktop entry. Unreachable today; reviewed in the allowlist.

**Release-process defects (fixed in this change)**
6. No written release process, record, or evidence; `internal/rfcs/V3.0-scope-freeze.md` §20
   was per-release. → `RELEASE.md`, this directory, `scripts/release_audit.py`.
7. CI never installed or launched the `.deb`, AppImage or `.msi` (A6.02 WARN for this tag). →
   three new `desktop.yml` steps driving the installed engine through a journey.
8. Nothing on the live site said which commit it was built from (A17.02 WARN). → `pages.yml`
   writes `/build.json`.
9. The refresh-token reuse detection the README advertises had no test. →
   `tests/security/test_refresh_token_reuse.py` (planted regression caught).

**Infrastructure limitations**
10. No Windows or Linux machine, and no GUI automation of the desktop app: Phases 8-9 and
    every GUI row are `NOT RUN`. CI now covers the installed engines, not the GUI.
11. amd64 container *runtime* was not exercised (this host is arm64); A10.01 proves the
    manifests only.
12. The upgrade tooling is wired to a v2.1.0 fixture (`scripts/make_upgrade_fixture.py`), so
    an upgrade from any other previous release is a manual procedure (M19.03).
13. The Release is public the moment the tag's workflows finish, and GitHub marks it
    `latest` — so installed apps are told about it before Phase 21 approves it (A11.02).
    Publishing as a draft and un-drafting after sign-off would close this; not done, because
    it can only be exercised by a real tag.

## Known issues shipped with this release

Everything in `frontend/lib/releases.ts` v3.0.1 `known` (16 items), plus the defects above
that users can see: #1 (self-hosted `/api/v1/version` says `unknown`) and #3 (size claims).

## Incidents found during this release, and the check each became (M22.06)

| Incident | Check added |
|---|---|
| Images unstamped | `release.yml` stamp job + "The pushed image reports the commit that built it"; A10.05, A11.09, A6.03 |
| Deploy default `edge` stale | A10.04; bootstrap and guide default to `latest` |
| Installers never installed by CI | `desktop.yml` `.deb`/AppImage/`.msi` steps; A6.02, A6.03 |
| Live site had no build identity | `pages.yml` `build.json`; A17.02, A6.03 |
| Advertised reuse detection untested | `tests/security/test_refresh_token_reuse.py` |
| Binary false positive in a secret scan | M18.03 now requires reading each hit with `grep -ao` |

## Release approval

```text
Version:            v3.0.1
Commit:             d53d6457df1d5b7666fad529f5433616e78bce6a
Tag:                v3.0.1 (annotated)
Release manager:    — (retroactive dry run)

Automated checks    [ ] pre-tag (not run: predates the audit)   [ ] published   [ ] post-release
Desktop             [x] macOS (packaged engine + signature; GUI not run)   [ ] Windows   [ ] Linux
Web                 [x] Landing   [ ] Download (size claim)   [x] Releases   [x] Docs
Distribution        [x] GitHub Release   [ ] Docker (unstamped images)   [x] Checksums
Security            [x] PASS
Upgrade/migration   [x] N/A — no schema or format change
Critical journey    [ ] web (fake mode only)   [ ] desktop (engine only, no GUI)
Known issues        [ ] two new defects not yet in releases.ts
```

- [ ] **Release approved** — not applicable to a retroactive dry run.
