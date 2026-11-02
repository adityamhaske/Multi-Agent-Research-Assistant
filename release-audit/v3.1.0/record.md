# Release record — v3.1.0

Copied from `release-audit/TEMPLATE.md` at the start of the release (RELEASE.md, M0.01).
Everything a person decided, checked or accepted for this release is written here; everything
a machine checked is in the audit JSON beside it. Nothing is marked PASS without evidence a
reader can re-check.

Stage A (prepare) was run on 2026-11-02 from an Apple Silicon Mac, on the release branch
`release/v3.1.0` cut from `origin/main`. The owner delegated the release end to end ("do all for
me", 2026-11-01), including the G-5 thresholds (scope-freeze A-7).

| | |
|---|---|
| Version | v3.1.0 |
| Previous release | v3.0.3 |
| Release manager | Aditya Mhaske (prepared and run with Claude Code under the owner's delegation) |
| Release commit (tag target) | PENDING: the merge of #281, which follows the release PR (#278) with the CodeQL fix and this record's scope. The release candidate tested for G-1 and G-2 is `c20733e`, the merge of #279. The tag differs from it by `PreviewDrawer.tsx`, `lib/desktop.ts`, their tests and this file; the published `.dmg` is built from the tag |
| Tag | v3.1.0 (annotated) |
| Tag date | PENDING |
| Audit evidence | `pre-tag.json`, `published.json`, `post-release.json` in this directory |

Result values: `PASS` · `FAIL` · `N/A` (why it does not apply) · `NOT RUN` (why not) ·
`ACCEPTED` (a known failure the sign-off accepts, with the reason) · `PENDING`.

---

## Scope

Every PR merged since the previous release, in or out (A2.01 fails on a `#N` missing here).
Version rationale (M0.03): **minor**. The release adds capability: file selection, claim
checking, folders, new file kinds, Offline, and a corpus per project on the desktop. The
changes are additive:
- **Schema:** migrations 0028–0030 add nullable columns, and the corpus store's `_migrate`
  only adds.
- **Bundles:** still format v2. A selected-files run records itself in fields the format
  already has, and the unchanged v3.0.2 verifier passes 3.1 bundles (G-4).
- **Downgrade:** a released 3.0.2 app opens 3.1 data (G-3).

The one platform change is publishing: the desktop ships for macOS only (A-6). Windows and
Linux users keep v3.0.3, and nothing they have is removed.

The frozen scope is `internal/rfcs/V3.1-scope-freeze.md` with RFC `V3.1-corpus-scope.md` rev 4.
Its amendments: A-1 (G-6 labels by an LLM judge), A-2 (claims located from quotes), A-3/A-4 (the
§9 checker hardening that made G-6 pass), A-5 (OmniRoute only), A-6 (macOS only), A-7 (the G-5
thresholds).

| Feature / fix | PRs | Implementation | Tests | UI | API | Desktop | Docs | Website | Release notes | Known limitations | Status |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Research limited to the files you choose: frozen selection, enforced in the store, recorded in the bundle and checked by the 3.1 verifier | #212, #213, #214, #215, #217, #229, #239, #241, #243, #246, #249 | `corpus_selection.py`, `ScopedCorpus`, `run_lifecycle`, `verify_bundle.py` (`corpus_selection`) | `test_corpus_project_isolation.py`, selection-isolation tests, `selection_retrieval` eval (leakage 0) | ✓ Ask about these files; run page lists the files | ✓ `corpus_selection` on `POST /runs`; cited-documents route | ✓ same routes (parity) | ✓ docs/34, 05, 13, 06, 15, 25, 39 | — | ✓ | ✓ | Shipped |
| Every claim checked before the report is offered (§9), with repair, a gate and a record; checker accuracy shown (D-24) | #221, #222, #240, #252, #254, #255, #257, #258, #260, #261, #262, #272, #273, #275, #277, #279 | `grounding.py`, `grounding_repair.py`, `quantities.py`, `checker_accuracy.py` | `test_grounding_*`, `test_quantities.py`, `test_checker_accuracy.py`; G-6 and G-5 | ✓ run page counts and accuracy label | ✓ `grounding_report` | ✓ | ✓ docs/15, 25, 27, 39 | — | ✓ | ✓ | Shipped |
| Folders: tree, uploads, drop, rename/move/delete, stop an upload | #227, #228, #263, #268 | `corpus.py` folders, `CorpusTree`, `FolderDialog`, corpus page, `lib.rs` drop handler | `test_folder_actions.py` (both hosts), `FolderDialog.test.tsx`, `test_desktop_drop_reaches_the_page.py`; G-2 macOS | ✓ | ✓ folder routes | ✓ | ✓ docs/34, 39 | — | ✓ | ✓ unreadable subfolder | Shipped |
| New file kinds and citation locations; PDF opens at its page; authenticated desktop preview | #223, #224, #225, #226, #230, #242, #245 | `documents.py` registry and extractors, `CitedPassage`, `PreviewDrawer` | format goldens, G-1 frozen ingest in CI | ✓ | ✓ `…/text` | ✓ | ✓ docs/27, 39 | — | ✓ | ✓ scanned PDFs | Shipped |
| Offline: refuses to start unless every model is at an address on this computer | #219, #270 | `research_engine/offline.py` | `test_offline.py` | ✓ the run form switch, corrected copy | ✓ `offline` | ✓ | ✓ docs/13, 25, 39 | — | ✓ | ✓ local routers | Shipped |
| A corpus per project on the desktop; legacy store moved and kept | #220, #247, #248, #253 | `desktop/corpus_layout.py` | `test_desktop_legacy_corpus_migration`, v3.0.2 upgrade fixture; G-3 | ✓ | — | ✓ desktop-only | ✓ docs/05, 28, 39 | — | ✓ | — | Shipped |
| A custom route with no endpoint is refused, not sent to api.openai.com; one env reader | #274 | `llm_factory._build`, `local.provider_keys_from_env` | `test_byok_and_profile.py`, desktop endpoint test | — | — | ✓ | ✓ AGENTS.md | — | ✓ | — | Shipped |
| Desktop run limits and the saved Custom Endpoint | #237 | `sidecar_run_config`, `endpoint_probe_config` | `test_desktop_run_limits_and_endpoint_status.py` | ✓ Settings | — | ✓ | — | — | ✓ | — | Shipped |
| macOS-only desktop publishing; download page offers Windows/Linux their newest build | #271 | `desktop.yml` release job, `releases.ts` `platforms`, download page, `installers_for` | `releases.test.ts`, `macos-only.test.tsx`, `test_release_audit.py` | ✓ download page | — | ✓ | ✓ release notes | ✓ /download | ✓ | ✓ | Shipped |
| Release gates G-1 to G-6 and their tooling | #234, #250, #251, #256, #276 | `scripts/gates/*`, `desktop.yml` G-1 steps | the gates themselves | — | — | ✓ | — | — | — | — | Shipped (process) |
| Docs: the corpus guide and PR-20b | #231, #232, #270 | docs | docs tests | — | — | — | ✓ | ✓ /docs | — | — | Shipped |
| Site discoverability: og.png content type, llms.txt, crawler rules, sitemap dates | #264 | `app/(site)` metadata routes | site tests | — | — | — | — | ✓ | — | — | Shipped |
| The preview drawer links Download only to this app's own API (CodeQL #32, #33) | #281 | `lib/desktop.ts::apiHref`, `PreviewDrawer` | `desktop.test.ts`, `PreviewDrawer.test.tsx` | ✓ | — | ✓ | — | — | — | — | Shipped |
| The release itself: version, notes, changelog, this record | #278 | `VERSION` and its carriers, `releases.ts`, the changelog, this file | the release audit | — | — | — | ✓ changelog | ✓ /releases (after the flip) | ✓ | ✓ | Shipped (process) |
| Dependencies | #209, #267 | vitest, react-query | CI | — | — | — | — | — | — | — | Shipped |
| Closing v3.0.2 and v3.0.3 (flip, post-release, macOS checks, the 48-hour watches) | #207, #233, #235, #236, #238 | `release-audit/v3.0.2`, `v3.0.3` | the audits | — | — | — | — | ✓ | — | — | Shipped (process) |
| Corpus-guide unreleased note and the AC-11 copy test | #232, #259 | docs/39, `RunScopePanel.test.tsx` | ✓ | ✓ | — | — | ✓ | — | — | — | Shipped |

Deferred (merged but not part of this release's story): none.

Not merged, decided after the tag (owner, 2026-11-02, "when complete"): #265 (Python 3.15 base
image, which waits on the desktop freeze, AGENTS.md A10.06) and #266 (anthropic SDK 2.x, a
reviewed provider-SDK upgrade).

## Release gates (RFC V3.1 §14.1)

| Gate | Result | Evidence |
|---|---|---|
| G-1 Python 3.14 and packaged ingest (macOS arm64, A-6) | PENDING | `evidence/G-1/` from the release commit's Desktop run |
| G-2 Desktop folder handling (WKWebView) | PENDING | `evidence/G-2/`. The pre-release pass on the CI build found the drop defect fixed in #268; the final pass is on the release build |
| G-3 v3.0.2 opening 3.1 data | PASS | `evidence/G-3/`: engine checks from CI and on this Mac, plus the 3.0.2 app's UI on this Mac (`macos-ui.md`) |
| G-4 Bundle compatibility | PASS | `evidence/G-4/`: two real selected-files runs, the v3.0.2 verifier sha256, every tamper case |
| G-5 Checking cost and latency | PASS against A-7 | Default routing: `eval-2026-11-02-custom-auto-best-fast-checking-cost-run1.json` (+152% tokens, 3.13× p95, no budget failures at L=240k). Second routing: `…-custom-agy-gemini-3-flash-checking-cost-run1.json` (+165%, 3.05×, none at L; 3 of 12 unbudgeted runs ended unmeasured, and the thresholds bind the default only) |
| G-6 Grounding benchmark | PASS on the default routing | `…-custom-auto-best-fast-grounding-run1.json` (2026-11-02): FA 1.9% (Wilson 4.3%), FR 5.1%, unmeasured 4.5%. The second routing (`custom:agy/gemini-3-flash`) is below the threshold and labelled so (D-24) |

## Release blockers (§14.2)

| Blocker | Result |
|---|---|
| 1. Cross-project access (AC-1, AC-27, AC-37) | none found. Both hosts are tested in `test_corpus_project_isolation.py` |
| 2. An unchecked claim reaching approval (AC-35, AC-42) | none. `test_grounding_gate_paths.py` |
| 3. A bundle either verifier cannot verify, or a tamper that passes | none (G-4) |
| 4. Failed migration recovery or lost legacy document | none. v3.0.2 upgrade fixture, failure injection; G-3 |
| 5. A gate without its evidence | PENDING (G-1, G-2) |
| 6. G-6 below threshold on the default routing | none (PASS) |

## Desktop artifacts (M6.01)

Packaged artifacts only — source-checkout evidence goes in its own row and never satisfies
a desktop check (M6.03).

| Artifact | SHA-256 | OS | Arch | Version (installed) | Engine git SHA | Install | Launch | Journey |
|---|---|---|---|---|---|---|---|---|
| `Research.Assistant_3.1.0_aarch64.dmg` | | macOS | arm64 | | | | | |
| `Research.Assistant_3.1.0_x64_en-US.msi` | | Windows | x64 | | | | | |
| `Research.Assistant_3.1.0_amd64.AppImage` | | Linux | x86-64 | | | | | |
| `Research.Assistant_3.1.0_amd64.deb` | | Linux | x86-64 | | | | | |

## Container images

| Image | Digest (`3.1.0`) | amd64 | arm64 | Provenance revision | Runs (M10.x) |
|---|---|---|---|---|---|
| api | | | | | |
| worker | | | | | |
| frontend | | | | | |

## Automated audit

| Stage | Command | Verdict | Counts | Evidence |
|---|---|---|---|---|
| pre-tag | `release_audit.py --version 3.1.0` | | | `pre-tag.json` |
| published | `… --published --download --docker` | | | `published.json` |
| post-release | `… --post-release --download --docker` | | | `post-release.json` |

Disposition of every WARN and UNAVAILABLE (M21.01):

| Check | Result | Disposition |
|---|---|---|

## Manual checks

One row per `M…` item in RELEASE.md (A21.01 fails on a missing row).

| ID | Result | Check — evidence |
|---|---|---|
| **Phase 0 — Release Scope Freeze** | | |
| M0.01 | PENDING | Create the release record — evidence: |
| M0.02 | PENDING | Freeze the scope: list every feature and fix in the record's Scope table, each with its PR numbers — evidence: |
| M0.03 | PENDING | Choose the version number and record why: major for a breaking change (API contract, bundle format a… — evidence: |
| M0.04 | PENDING | Carry forward known limitations: start this release's `known` from the previous release's, and remove an… — evidence: |
| **Phase 1 — Repository / Version Consistency** | | |
| M1.01 | PENDING | Bump and derive, in this order: `VERSION`; the new `releases.ts` entry at the top with `unreleased: true`… — evidence: |
| M1.02 | PENDING | Search for stale references the scanner cannot see: images and screenshots with text in them, the… — evidence: |
| M1.03 | PENDING | Review every line A1.09 flags, one by one — evidence: |
| **Phase 2 — Feature Completeness** | | |
| M2.01 | PENDING | Fill the feature matrix in the record for every scope row: Implementation · Tests · UI · API · Desktop ·… — evidence: |
| M2.02 | PENDING | For every feature on both hosts, confirm the desktop really has it: the route exists and behaves… — evidence: |
| M2.03 | PENDING | Read the `releases.ts` entry and the changelog entry against the matrix: `improved` states user-visible… — evidence: |
| M2.04 | PENDING | If A2.03 fails: run the release evaluation (`docs/developers/08-testing-and-evaluation.md`, "The release… — evidence: |
| **Phase 3 — Automated Testing** | | |
| M3.01 | PENDING | Explain every re-run: any required job on the release commit that passed only on a retry is recorded with… — evidence: |
| M3.02 | PENDING | Read the non-blocking dependency-audit output of the release commit's CI run — evidence: |
| **Phase 4 — Backend / API Verification** | | |
| M4.01 | PENDING | If `backend/app/api/` changed since the previous release, `docs/reference/34-api.md` and `35-sse.md`… — evidence: |
| M4.02 | PENDING | On the published images (Phase 10 stack), probe the boundaries: an unauthenticated `GET /api/v1/projects`… — evidence: |
| **Phase 5 — Frontend Verification** | | |
| M5.01 | PENDING | On the Phase 10 stack, open dashboard, a project, a finished run (report, evidence, citations), Settings… — evidence: |
| M5.02 | PENDING | Keyboard-only pass over the two gates: plan approval and report approval are reachable and operable… — evidence: |
| **Phase 6 — Desktop Application Verification** | | |
| M6.01 | PENDING | Record the artifact table in the record for all four installers: file name · SHA-256 · OS · architecture ·… — evidence: |
| M6.02 | PENDING | On every platform, run the packaged-engine checker against the **installed** copy of the **published**… — evidence: |
| M6.03 | PENDING | Mark every desktop row in the record as *packaged* or *source* — evidence: |
| **Phase 7 — macOS Verification** | | |
| M7.01 | PENDING | Download the `.dmg` from the release in a browser (so it carries the quarantine flag) and verify it — evidence: |
| M7.02 | PENDING | The DMG opens and holds the app at the right version — evidence: |
| M7.03 | PENDING | The signature is whole and valid — evidence: |
| M7.04 | PENDING | Gatekeeper judges a quarantined copy as policy, not damage — evidence: |
| M7.05 | PENDING | The bundled engine is present, native, and unmodified by hardened runtime — evidence: |
| M7.06 | PENDING | The packaged engine identifies itself and completes the journey — evidence: |
| M7.07 | PENDING | First launch as a user: drag to Applications; open it *without* the command and confirm the block is the… — evidence: |
| M7.08 | PENDING | The Phase 20 desktop journey on macOS (M20.02) — evidence: |
| M7.09 | PENDING | Quit the app; no engine is left running — evidence: |
| **Phase 8 — Windows Verification** | | |
| M8.01 | PENDING | Download the `.msi` in a browser; verify it — evidence: |
| M8.02 | PENDING | SmartScreen shows the unknown-publisher warning; **More info → Run anyway** proceeds, exactly as the… — evidence: |
| M8.03 | PENDING | Install completes; Start-menu entry exists; Settings → Apps shows version `3.1.0`; files under `C:\Program… — evidence: |
| M8.04 | PENDING | Launch: the window opens without a crash; Task Manager shows `research-sidecar.exe`; no firewall prompt… — evidence: |
| M8.05 | PENDING | `python scripts\check_packaged_sidecar.py --search "C:\Program Files\Research Assistant" --expect-sha <tag… — evidence: |
| M8.06 | PENDING | The Phase 20 desktop journey on Windows (M20.02), from a user whose profile path has a space; exports save… — evidence: |
| M8.07 | PENDING | Local storage: data under `%USERPROFILE%\.research-engine`; provider keys in Windows Credential Manager,… — evidence: |
| M8.08 | PENDING | Quit: `research-sidecar.exe` exits (the watchdog — two Windows-only crashes lived here, #113) — evidence: |
| M8.09 | PENDING | Uninstall from Settings → Apps: the Program Files directory is removed; user data remains (as documented) — evidence: |
| **Phase 9 — Linux Verification** | | |
| M9.01 | PENDING | AppImage: download, verify (`sha256sum -c SHA256SUMS --ignore-missing`), `chmod +x`, launch from a desktop… — evidence: |
| M9.02 | PENDING | `.deb`: `sudo apt install ./Research.Assistant_3.1.0_amd64.deb` on a clean supported Ubuntu LTS resolves… — evidence: |
| M9.03 | PENDING | Key storage uses the Secret Service keyring; on a session without one, the app says so rather than storing… — evidence: |
| M9.04 | PENDING | `sudo apt remove research-assistant` removes the application; user data remains; no engine left running — evidence: |
| **Phase 10 — Docker / Container Verification** | | |
| M10.01 | PENDING | Run the published images on the full-stack topology, on their own volumes: — evidence: |
| M10.02 | PENDING | On that stack: register, log in, create a project, run a fake-mode research through both gates, export… — evidence: |
| M10.03 | PENDING | On an arm64 host (Apple Silicon Docker or the Ampere target), the same stack starts from the same tags — evidence: |
| M10.04 | PENDING | Tear down with `down -v` using the same flags; the developer's own `mara_full_*` volumes are untouched — evidence: |
| **Phase 11 — GitHub Release Verification** | | |
| M11.01 | PENDING | Add the hand-written summary at the top of the Release body (what changed for users, the macOS… — evidence: |
| **Phase 12 — Documentation Verification** | | |
| M12.01 | PENDING | For each scope row, the docs describe what shipped — on both hosts, with desktop differences stated… — evidence: |
| M12.02 | PENDING | Configuration: every environment variable added, renamed or removed since the previous release (`git diff… — evidence: |
| M12.03 | PENDING | Search the docs for removed or renamed features, commands and routes named in the diff (`git diff --stat… — evidence: |
| M12.04 | PENDING | Architecture docs (`docs/architecture/02`, `04`) match the graph's nodes and gates — evidence: |
| M12.05 | PENDING | Known limitations agree across `releases.ts` `known`, the changelog **Known**, the Release body and the… — evidence: |
| **Phase 13 — README Verification** | | |
| M13.01 | PENDING | Read the README top to bottom against the release: the feature list (nothing unreleased, nothing removed),… — evidence: |
| **Phase 14 — Landing Page Verification** | | |
| M14.01 | PENDING | View `/` at desktop width and at 375 px, light and dark: hero, download call-to-action, "New in" link to… — evidence: |
| M14.02 | PENDING | `/why`: every comparison claim (`frontend/lib/comparison.ts`) still holds for this release — evidence: |
| **Phase 15 — Download Page Verification** | | |
| M15.01 | PENDING | On each OS (or with a UA override), the detected-OS card leads; the big button and every card button point… — evidence: |
| M15.02 | PENDING | Download one installer by clicking the page's button in a real browser; the file name and checksum are right — evidence: |
| **Phase 16 — Releases Page Verification** | | |
| M16.01 | PENDING | View `/releases`: the new entry is first with the tag's date; its summaries are shown and the lists fold… — evidence: |
| **Phase 17 — GitHub Pages / Deployment Verification** | | |
| M17.01 | PENDING | If A17.01 fails because `main` moved after the flip, wait for the newer deploy and re-run; if the deploy… — evidence: |
| **Phase 18 — Security / Configuration Verification** | | |
| M18.01 | PENDING | Review `git diff v3.0.3..HEAD` for debug flags, test accounts, credentials, private URLs, and anything that… — evidence: |
| M18.02 | PENDING | If `backend/app/config.py`, the security middleware, auth, or the SSRF guard changed: re-check CORS… — evidence: |
| M18.03 | PENDING | No secret or env file ships in an artifact — evidence: |
| M18.04 | PENDING | Public surface: `/api/v1/version` is unauthenticated on the server by design; nothing else new is — evidence: |
| **Phase 19 — Upgrade / Migration Verification** | | |
| M19.01 | PENDING | Fresh install: an empty database migrates to head (CI), and a fresh desktop data directory starts (M6.02… — evidence: |
| M19.02 | PENDING | Server upgrade from the previous release: run the previous release's images (`RELEASE_TAG=PREV` with the… — evidence: |
| M19.03 | PENDING | Desktop upgrade from the previous release: install the previous release, create the same data, install… — evidence: |
| M19.04 | PENDING | Downgrade: CI's round-trip proves the schema reverses; record whether running the previous images against… — evidence: |
| M19.05 | PENDING | A bundle exported by the previous release verifies with this release's verifier, unchanged (`python -m… — evidence: |
| **Phase 20 — Final End-to-End Production Smoke Test** | | |
| M20.01 | PENDING | The web/self-hosted journey on the Phase 10 stack, **with a real provider at least once** (fake mode… — evidence: |
| M20.02 | PENDING | The desktop journey on each platform (M7.08, M8.06, M9.01/M9.02), with a real provider or Ollama — evidence: |
| M20.03 | PENDING | Negative paths on the published build: an invalid provider key is reported as rejected by its provider as… — evidence: |
| M20.04 | PENDING | Every `[n]` in the final report resolves on hover to a source and its snippet; an unresolved one renders… — evidence: |
| **Phase 21 — Release Approval** | | |
| M21.01 | PENDING | Every WARN and UNAVAILABLE in the published audit has a written disposition in the record — evidence: |
| M21.02 | PENDING | Known issues are documented everywhere they belong (M12.05), including anything this audit found and the… — evidence: |
| M21.03 | PENDING | The release manager signs the approval block in the record — evidence: |
| **Phase 22 — Post-Release Verification** | | |
| M22.01 | PENDING | The flip PR: drop `unreleased`, set the entry's `date` to the tag's date, date the changelog heading,… — evidence: |
| M22.02 | PENDING | After Pages deploys: run the post-release audit with `--download --docker`, commit its JSON (write-once)… — evidence: |
| M22.03 | PENDING | Load `/`, `/why`, `/docs`, `/download`, `/releases` on a phone and a desktop browser with the cache disabled — evidence: |
| M22.04 | PENDING | In an installed copy of the **previous** desktop release, Settings → About → *Check for updates* reports… — evidence: |
| M22.05 | PENDING | For 48 hours, watch issues and discussions for install or launch reports; any release-blocking report… — evidence: |
| M22.06 | PENDING | Every incident found during this release becomes a check: an `A…` check (preferred) or an `M…` item, plus… — evidence: |

## Known issues shipped with this release

## Incidents found during this release, and the check each became (M22.06)

| Incident | Check added |
|---|---|

## Release approval

```text
Version:            v3.1.0
Commit:
Tag:                v3.1.0 (annotated)
Release manager:

Automated checks    [ ] pre-tag PASS   [ ] published PASS   [ ] post-release PASS
Desktop             [ ] macOS PASS     [ ] Windows PASS     [ ] Linux PASS
Web                 [ ] Landing PASS   [ ] Download PASS    [ ] Releases PASS   [ ] Docs PASS
Distribution        [ ] GitHub Release PASS   [ ] Docker PASS   [ ] Checksums PASS
Security            [ ] PASS
Upgrade/migration   [ ] PASS
Critical journey    [ ] web PASS   [ ] desktop PASS
Known issues        [ ] documented everywhere they belong
```

- [ ] **Release approved**
