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
| Release commit (tag target) | `ba7c2ab` (`ba7c2ab80a6025c0108a379c389ecc91b36662b4`), the merge of #282. The release candidate tested for G-1 and G-2 is `c20733e` (the merge of #279). The tag differs from it by #281 (`PreviewDrawer.tsx`, `lib/desktop.ts` and their tests), #280 (`backend/constraints.txt`) and this file. The published `.dmg` is built from the tag and was checked on this Mac (Phase 7) |
| Tag | v3.1.0 (annotated, `f12d349`) |
| Tag date | 2026-11-02 (tagged 20:15Z; Release and Desktop runs 41517619651 and 41517619755 published the release) |
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
| The release itself: version, notes, changelog, this record | #278, #282 | `VERSION` and its carriers, `releases.ts`, the changelog, this file | the release audit | — | — | — | ✓ changelog | ✓ /releases (after the flip) | ✓ | ✓ | Shipped (process) |
| Provider SDKs: anthropic 2.3.0 with langchain-anthropic 1.7.7 and langchain-core 1.6.12 (supersedes Dependabot's anthropic bump) | #280, #266 | `backend/constraints.txt` | full backend suite on the new pins in a clean venv (2476 passed; `test_worker_event_loop`, `test_dependency_constraints`); a 40-claim G-6 spot check on the new pins before tagging | — | — | ✓ | — | — | — | — | Shipped. G-5 and G-6 were measured on the previous pins (langchain-core 1.6.6, anthropic 1.9.0). The spot check on the new pins (G-6, first 40 claims, `custom:auto/best-fast`, not written) gave 2 unmeasured, 0 false accepts, 7.1% false rejects. The same 40 claims in the passing full run gave 1 unmeasured, 0 of 25 false accepts and 1 of 14 false rejects (7.1%). Contradicted recall varied (43% vs 100%), but every contradicted claim it missed was still rejected |
| Dependencies | #209, #267 | vitest, react-query | CI | — | — | — | — | — | — | — | Shipped |
| Closing v3.0.2 and v3.0.3 (flip, post-release, macOS checks, the 48-hour watches) | #207, #233, #235, #236, #238 | `release-audit/v3.0.2`, `v3.0.3` | the audits | — | — | — | — | ✓ | — | — | Shipped (process) |
| Corpus-guide unreleased note and the AC-11 copy test | #232, #259 | docs/39, `RunScopePanel.test.tsx` | ✓ | ✓ | — | — | ✓ | — | — | — | Shipped |

Deferred (merged but not part of this release's story): none.

Not merged, decided after the tag: #265 (the Python 3.15 base image, which waits on the
desktop freeze, AGENTS.md A10.06). The owner merged #280, the provider-SDK upgrade that
supersedes #266, before the tag, so it ships in this release.

## Release gates (RFC V3.1 §14.1)

| Gate | Result | Evidence |
|---|---|---|
| G-1 Python 3.14 and packaged ingest (macOS arm64, A-6) | PASS | `evidence/G-1/`: Python 3.14.10 in the freeze, `pip freeze`, a cp314 arm64 wheel for every parser, the build logs, and AC-25 frozen ingest of every format at `c20733e`. Repeated on the published `.dmg`'s engine at the tag (`evidence/published-app/packaged-check.json`, `ingest_fixtures` PASS) |
| G-2 Desktop folder handling (WKWebView) | PASS | `evidence/G-2/release-build/log.md` on the release-candidate `.dmg`: picker open and cancel, nested folder through the native picker, unreadable subfolder (documented), delete counts, preview, byte-identical download, token gate, Stop uploading. The Finder drop is from a launched build of byte-identical drop code (`a29d645`, after #268), because pointer input stopped working on this Mac in this session; see step 10. `../pre-release-ci-build/log.md` holds the pass that found the drop defect |
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
| 5. A gate without its evidence | none: every gate has evidence under `evidence/` |
| 6. G-6 below threshold on the default routing | none (PASS) |

## Desktop artifacts (M6.01)

Packaged artifacts only — source-checkout evidence goes in its own row and never satisfies
a desktop check (M6.03).

| Artifact | SHA-256 | OS | Arch | Version (installed) | Engine git SHA | Install | Launch | Journey |
|---|---|---|---|---|---|---|---|---|
| `Research.Assistant_3.1.0_aarch64.dmg` (packaged) | `9088a3a82bbfd0d67cbcb8fa173898ea7a1147e5236328605424aa1588b13c05` | macOS | arm64 | 3.1.0 | `ba7c2ab80a6025c0108a379c389ecc91b36662b4` | PASS (copied from the image) | PASS | PASS (`evidence/published-app/packaged-check.json`: journey, verify_bundle, ingest) |
| Windows and Linux installers | — | — | — | — | — | N/A: not published from 3.1.0 (A-6, #271). CI still builds and journeys them | | |

## Container images

| Image | Digest (`3.1.0`) | amd64 | arm64 | Provenance revision | Runs (M10.x) |
|---|---|---|---|---|---|
| api | `sha256:8e09a6914d5a84b6887b4f4c20dbab621e6ff3a44b73457b6796ebae065bbad1` | ✓ | ✓ | ba7c2ab (A10.05) | PASS |
| worker | `sha256:afd2c24ffb26750ff0d4a2eebac1727ca73cb363238636b1ef3fa0115994e8dc` | ✓ | ✓ | ba7c2ab | PASS |
| frontend | `sha256:4f5409a25cb5bc473aff519960ec251dc4b9304a39505998f5fbe31986362716` | ✓ | ✓ | ba7c2ab | PASS |

## Automated audit

| Stage | Command | Verdict | Counts | Evidence |
|---|---|---|---|---|
| pre-tag | `release_audit.py --version 3.1.0 --stage pre-tag` | PASS | 35 PASS, 1 WARN | `pre-tag.json` |
| published | `… --published --download --docker` | PASS | 51 PASS, 3 WARN | `published.json` |
| post-release | `… --post-release --download --docker` | PENDING | | `post-release.json` |

Disposition of every WARN and UNAVAILABLE (M21.01):

| Check | Result | Disposition |
|---|---|---|
| A19.02 | WARN | Migrations 0028–0030, the ORM models and the bundle code changed. Phase 19 ran: M19.02 upgraded populated 3.0.3 images to 3.1.0, and G-3 and G-4 cover downgrade and bundles |
| A16.03 | WARN | Historical: v1.0.0 and v1.0.2 site dates are a day off their tags, as in earlier records |
| A21.01 | WARN | This record, completed in the flip PR |

## Manual checks

One row per `M…` item in RELEASE.md (A21.01 fails on a missing row).

| ID | Result | Check — evidence |
|---|---|---|
| **Phase 0 — Release Scope Freeze** | | |
| M0.01 | PASS | Create the release record — this file, created in #278 |
| M0.02 | PASS | Freeze the scope: list every feature and fix in the record's Scope table, each with its PR numbers — the Scope table: every merged PR since v3.0.3, A2.01 PASS |
| M0.03 | PASS | Choose the version number and record why: major for a breaking change (API contract, bundle format a… — minor: additive schema and bundle v2 unchanged, the v3.0.2 verifier passes 3.1 bundles (G-4); see Scope |
| M0.04 | PASS | Carry forward known limitations: start this release's `known` from the previous release's, and remove an… — `releases.ts` `known` starts from 3.0.3 minus "every project shares one corpus" (fixed by #220, AC-1 and AC-27 evidence) and with the corpus-only item rewritten for Offline |
| **Phase 1 — Repository / Version Consistency** | | |
| M1.01 | PASS | Bump and derive, in this order: `VERSION`; the new `releases.ts` entry at the top with `unreleased: true`… — #278: VERSION, `sync_version.py --write` (4 files consistent), `cargo update -p research-desktop`, entry `unreleased: true`, changelog `— unreleased` |
| M1.02 | PASS | Search for stale references the scanner cannot see: images and screenshots with text in them, the… — release URLs are built from `releases.ts` (download page); the OpenGraph image carries no version; image tags in docs use `RELEASE_TAG` |
| M1.03 | PASS | Review every line A1.09 flags, one by one — A1.09 PASS at every stage; no new version-naming line |
| **Phase 2 — Feature Completeness** | | |
| M2.01 | PASS | Fill the feature matrix in the record for every scope row: Implementation · Tests · UI · API · Desktop ·… — the Scope table |
| M2.02 | PASS | For every feature on both hosts, confirm the desktop really has it: the route exists and behaves… — `test_host_parity` (KNOWN_DESKTOP_GAPS empty); folder, selection and grounding routes called on both hosts in `test_folder_actions.py`, `test_grounding_record.py`, `test_grounding_gate_paths.py` |
| M2.03 | PASS | Read the `releases.ts` entry and the changelog entry against the matrix: `improved` states user-visible… — `releases.ts` `improved`/`known` and the changelog read against the Scope table |
| M2.04 | N/A | If A2.03 fails: run the release evaluation (`docs/developers/08-testing-and-evaluation.md`, "The release… — A2.03 PASS: evaluations committed (G-5, G-6, selection-retrieval leakage) |
| **Phase 3 — Automated Testing** | | |
| M3.01 | PASS | Explain every re-run: any required job on the release commit that passed only on a retry is recorded with… — Release commit ba7c2ab: Desktop 41511696743 passed on attempt 2. On attempt 1 the macOS Shell job was never acquired by a runner ("capacity constraints"), with no code involved; `--failed` re-run. CI and Pages passed on attempt 1. The tag runs passed on attempt 1 |
| M3.02 | PASS | Read the non-blocking dependency-audit output of the release commit's CI run — pip-audit and npm audit on the release commit are non-blocking; the open dependency alert is one medium (`minimatch`, a dev tool), under A18.05's bar |
| **Phase 4 — Backend / API Verification** | | |
| M4.01 | PASS | If `backend/app/api/` changed since the previous release, `docs/reference/34-api.md` and `35-sse.md`… — `backend/app/api/` changed (runs, corpus folders, cited documents); `docs/34` updated in #270 and the PRs that added the routes |
| M4.02 | PASS | On the published images (Phase 10 stack), probe the boundaries: an unauthenticated `GET /api/v1/projects`… — Published 3.1.0 images: unauthenticated GET /api/v1/projects 401; wrong password and unknown address both 401; /api/v1/version 200 (public by design) |
| **Phase 5 — Frontend Verification** | | |
| M5.01 | NOT RUN | On the Phase 10 stack, open dashboard, a project, a finished run (report, evidence, citations), Settings… — No browser pass on the published web images this release; the server journey ran through the API (M10.02, M19.02), and the same frontend ran inside the desktop app (G-2, Phase 7) |
| M5.02 | NOT RUN | Keyboard-only pass over the two gates: plan approval and report approval are reachable and operable… — As M5.01; the gates' markup is unchanged since 3.0.3's keyboard pass |
| **Phase 6 — Desktop Application Verification** | | |
| M6.01 | PASS | Record the artifact table in the record for all four installers: file name · SHA-256 · OS · architecture ·… — the Desktop artifacts table |
| M6.02 | PASS | On every platform, run the packaged-engine checker against the **installed** copy of the **published**… — `check_packaged_sidecar.py` on the published `.dmg` app: PASS (launch, token gate, identity ba7c2ab, ingest every format, journey, verify_bundle) |
| M6.03 | PASS | Mark every desktop row in the record as *packaged* or *source* — every desktop row is marked packaged |
| **Phase 7 — macOS Verification** | | |
| M7.01 | PASS | Download the `.dmg` from the release in a browser (so it carries the quarantine flag) and verify it — downloaded from the release; `shasum -c SHA256SUMS` OK; quarantine flag set as a browser does |
| M7.02 | PASS | The DMG opens and holds the app at the right version — the image holds `Research Assistant.app`, CFBundleShortVersionString 3.1.0 |
| M7.03 | PASS | The signature is whole and valid — `codesign --verify --deep --strict`: valid on disk, satisfies its Designated Requirement; ad-hoc with runtime flags, whole bundle |
| M7.04 | PASS | Gatekeeper judges a quarantined copy as policy, not damage — `spctl --assess` on a quarantined copy: rejected (a policy verdict, not damage) |
| M7.05 | PASS | The bundled engine is present, native, and unmodified by hardened runtime — `Contents/Resources/sidecar/research-sidecar` is a native arm64 Mach-O; app 157 MB |
| M7.06 | PASS | The packaged engine identifies itself and completes the journey — `evidence/published-app/packaged-check.json`, after the documented `xattr -dr` step |
| M7.07 | PASS | First launch as a user: drag to Applications; open it *without* the command and confirm the block is the… — launched from a copy with the quarantine cleared by the documented command; window opens on Research |
| M7.08 | PASS | The Phase 20 desktop journey on macOS (M20.02) — on the published app: folder upload through the native picker (nesting kept), preview, byte-identical download (`evidence/published-app/`). The research journey ran in the packaged engine (M7.06) |
| M7.09 | PASS | Quit the app; no engine is left running — after quitting, no `research-sidecar` process remains |
| **Phase 8 — Windows Verification** | | |
| M8.01 | N/A | Download the `.msi` in a browser; verify it — No Windows or Linux installer is published from 3.1.0 (A-6, #271) |
| M8.02 | N/A | SmartScreen shows the unknown-publisher warning; **More info → Run anyway** proceeds, exactly as the… — No Windows or Linux installer is published from 3.1.0 (A-6, #271) |
| M8.03 | N/A | Install completes; Start-menu entry exists; Settings → Apps shows version `3.1.0`; files under `C:\Program… — No Windows or Linux installer is published from 3.1.0 (A-6, #271) |
| M8.04 | N/A | Launch: the window opens without a crash; Task Manager shows `research-sidecar.exe`; no firewall prompt… — No Windows or Linux installer is published from 3.1.0 (A-6, #271) |
| M8.05 | N/A | `python scripts\check_packaged_sidecar.py --search "C:\Program Files\Research Assistant" --expect-sha <tag… — No Windows or Linux installer is published from 3.1.0 (A-6, #271) |
| M8.06 | N/A | The Phase 20 desktop journey on Windows (M20.02), from a user whose profile path has a space; exports save… — No Windows or Linux installer is published from 3.1.0 (A-6, #271) |
| M8.07 | N/A | Local storage: data under `%USERPROFILE%\.research-engine`; provider keys in Windows Credential Manager,… — No Windows or Linux installer is published from 3.1.0 (A-6, #271) |
| M8.08 | N/A | Quit: `research-sidecar.exe` exits (the watchdog — two Windows-only crashes lived here, #113) — No Windows or Linux installer is published from 3.1.0 (A-6, #271) |
| M8.09 | N/A | Uninstall from Settings → Apps: the Program Files directory is removed; user data remains (as documented) — No Windows or Linux installer is published from 3.1.0 (A-6, #271) |
| **Phase 9 — Linux Verification** | | |
| M9.01 | N/A | AppImage: download, verify (`sha256sum -c SHA256SUMS --ignore-missing`), `chmod +x`, launch from a desktop… — No Windows or Linux installer is published from 3.1.0 (A-6, #271) |
| M9.02 | N/A | `.deb`: `sudo apt install ./Research.Assistant_3.1.0_amd64.deb` on a clean supported Ubuntu LTS resolves… — No Windows or Linux installer is published from 3.1.0 (A-6, #271) |
| M9.03 | N/A | Key storage uses the Secret Service keyring; on a session without one, the app says so rather than storing… — No Windows or Linux installer is published from 3.1.0 (A-6, #271) |
| M9.04 | N/A | `sudo apt remove research-assistant` removes the application; user data remains; no engine left running — No Windows or Linux installer is published from 3.1.0 (A-6, #271) |
| **Phase 10 — Docker / Container Verification** | | |
| M10.01 | PASS | Run the published images on the full-stack topology, on their own volumes: — Published images via `release-audit/compose.published-images.yml` (project `release-check`, port 3041, `LLM_MODE=fake`): first at 3.0.3, then switched to 3.1.0. Every service healthy; `/api/v1/version` reports 3.1.0 at ba7c2ab, not dirty |
| M10.02 | PASS | On that stack: register, log in, create a project, run a fake-mode research through both gates, export… — On 3.1.0: login; a run that waited at the plan gate under 3.0.3 completed both gates; export.md 200, export.pdf 200 (`%PDF`, 16.5 KB); bundles verify (`evidence/M19/`) |
| M10.03 | PASS | On an arm64 host (Apple Silicon Docker or the Ampere target), the same stack starts from the same tags — This host is arm64 (Apple Silicon Docker), so the arm64 images ran; both architectures are published (`imagetools inspect`, the Container images table) |
| M10.04 | PASS | Tear down with `down -v` using the same flags; the developer's own `mara_full_*` volumes are untouched — `down -v` with the same flags removed only `release_check_*`; the owner's running stack and its `mara_full_*` volumes were untouched |
| **Phase 11 — GitHub Release Verification** | | |
| M11.01 | PASS | Add the hand-written summary at the top of the Release body (what changed for users, the macOS… — The summary at the top of the Release body: what changed, macOS only, the first-launch command, and the link to the changelog's known limitations. The rest of the body is the workflows' sections |
| **Phase 12 — Documentation Verification** | | |
| M12.01 | PASS | For each scope row, the docs describe what shipped — on both hosts, with desktop differences stated… — #270 (PR-20b) and the docs edits in this PR: docs 05, 06, 13, 15, 25, 27, 28, 34, 36, 39, the overview, the desktop guide and the roadmap |
| M12.02 | PASS | Configuration: every environment variable added, renamed or removed since the previous release (`git diff… — No environment variable added or renamed; `CUSTOM_BASE_URL` is now read by the desktop too (#274), as documented for the CLI |
| M12.03 | PASS | Search the docs for removed or renamed features, commands and routes named in the diff (`git diff --stat… — No feature, command or route removed; the corpus-only copy was corrected for Offline (#270, this PR) |
| M12.04 | PASS | Architecture docs (`docs/architecture/02`, `04`) match the graph's nodes and gates — The graph's nodes and gates are unchanged; §9 runs inside the synthesizer step, as docs/13 and 39 describe |
| M12.05 | PASS | Known limitations agree across `releases.ts` `known`, the changelog **Known**, the Release body and the… — `releases.ts` `known`, the changelog **Known**, the Release body summary and this record's Known issues agree |
| **Phase 13 — README Verification** | | |
| M13.01 | PASS | Read the README top to bottom against the release: the feature list (nothing unreleased, nothing removed),… — README: the desktop is macOS only, and Windows and Linux get the last build published for them (this PR); nothing unreleased is advertised |
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
| M18.01 | PASS | Review `git diff v3.0.3..HEAD` for debug flags, test accounts, credentials, private URLs, and anything that… — `git diff v3.0.3..v3.1.0`: no debug flags, test accounts or credentials; A18.01 and A18.02 PASS. Two security fixes landed: #274 (a custom route never dials api.openai.com) and #281 (the desktop accepts only a loopback engine address) |
| M18.02 | PASS | If `backend/app/config.py`, the security middleware, auth, or the SSRF guard changed: re-check CORS… — `app/config.py` and the auth and middleware code are unchanged; the provider-key path changed in #274 and is tested in `test_byok_and_profile.py` |
| M18.03 | PASS | No secret or env file ships in an artifact — A18.01 and A18.02 PASS; the packaged checker's tree check passes; no `.env` in the image (`stamp_image.py` discards a leftover stamp) |
| M18.04 | PASS | Public surface: `/api/v1/version` is unauthenticated on the server by design; nothing else new is — On the published images only `/api/v1/version` (and health) answer unauthenticated (M4.02) |
| **Phase 19 — Upgrade / Migration Verification** | | |
| M19.01 | PASS | Fresh install: an empty database migrates to head (CI), and a fresh desktop data directory starts (M6.02… — A fresh Postgres migrated to head on the published 3.1.0 images (M10.01); a fresh desktop data directory starts (M6.02) |
| M19.02 | PASS | Server upgrade from the previous release: run the previous release's images (`RELEASE_TAG=PREV` with the… — `evidence/M19/`: published 3.0.3 images populated (project, completed run, a run waiting at the plan gate, a session, a stored key, preferences, a custom planner instruction), switched to 3.1.0: migrations 0028→0029→0030 applied once; login, preferences, key, project, runs and session present; the waiting run completed both gates; the old run re-exports; both bundles verify |
| M19.03 | PASS | Desktop upgrade from the previous release: install the previous release, create the same data, install… — The pre-3.1 desktop store moves to "Documents from before 3.1" with a kept backup: `test_desktop_legacy_corpus_migration`, the v3.0.2 upgrade fixture with failure injection (#248), and the Windows CI move (#253) |
| M19.04 | PASS | Downgrade: CI's round-trip proves the schema reverses; record whether running the previous images against… — G-3: the released 3.0.2 app opens 3.1 data (engine on all three OSes in CI, the app's UI on this Mac) |
| M19.05 | PASS | A bundle exported by the previous release verifies with this release's verifier, unchanged (`python -m… — a bundle exported by the published 3.0.3 images verifies with this release's verifier (`evidence/M19/`), and G-4 runs the v3.0.2 verifier on 3.1 bundles |
| **Phase 20 — Final End-to-End Production Smoke Test** | | |
| M20.01 | NOT RUN | The web/self-hosted journey on the Phase 10 stack, **with a real provider at least once** (fake mode… — The published-image journey ran in fake mode (M10.02, M19.02). Real-provider runs on this release's code: G-4's two selected-files runs and G-5's 42 runs, on OmniRoute |
| M20.02 | PASS | The desktop journey on each platform (M7.08, M8.06, M9.01/M9.02), with a real provider or Ollama — macOS (A-6): G-4 drove two real-provider selected-files runs through the desktop engine's routes to approval and export; the published app's packaged engine completed the journey (M7.06) |
| M20.03 | PASS | Negative paths on the published build: an invalid provider key is reported as rejected by its provider as… — #274: a custom route with no endpoint is refused by name rather than sent to OpenAI; an unchecked claim never reaches approval (AC-42 tests); budget exhaustion fails a run honestly (G-5) |
| M20.04 | PASS | Every `[n]` in the final report resolves on hover to a source and its snippet; an unresolved one renders… — G-4 bundles: citation_resolution PASS; unresolved markers render the ⚠ chip (unchanged, `test_report_markdown`) |
| **Phase 21 — Release Approval** | | |
| M21.01 | PASS | Every WARN and UNAVAILABLE in the published audit has a written disposition in the record — the disposition table above |
| M21.02 | PASS | Known issues are documented everywhere they belong (M12.05), including anything this audit found and the… — Known issues below, `releases.ts` `known`, the changelog **Known** and the Release body agree |
| M21.03 | PASS | The release manager signs the approval block in the record — approved below under the owner's delegation |
| **Phase 22 — Post-Release Verification** | | |
| M22.01 | PASS | The flip PR: drop `unreleased`, set the entry's `date` to the tag's date, date the changelog heading,… — this PR: `unreleased` dropped, dated 2026-11-02 (the tag's date), the changelog dated, the record and its evidence committed, `pre-tag.json` and `published.json` added |
| M22.02 | PENDING | After Pages deploys: run the post-release audit with `--download --docker`, commit its JSON (write-once)… — evidence: |
| M22.03 | PENDING | Load `/`, `/why`, `/docs`, `/download`, `/releases` on a phone and a desktop browser with the cache disabled — evidence: |
| M22.04 | PENDING | In an installed copy of the **previous** desktop release, Settings → About → *Check for updates* reports… — evidence: |
| M22.05 | PENDING | For 48 hours, watch issues and discussions for install or launch reports; any release-blocking report… — evidence: |
| M22.06 | PENDING | Every incident found during this release becomes a check: an `A…` check (preferred) or an `M…` item, plus… — evidence: |

## Known issues shipped with this release

The `known` list of the v3.1.0 entry in `frontend/lib/releases.ts`, which the changelog's
**Known** block and the Release body summarise. In short:
- the desktop app is macOS only;
- checking every claim makes corpus research slower and costlier (G-5);
- the checker's accuracy was measured against a model judge, on two routings, and every
  other model is labelled "not measured";
- Offline checks addresses, so a local router to the cloud passes;
- web research is not checked claim by claim;
- an unreadable subfolder is skipped silently;
- every other v3.0.3 gap that still applies.

## Incidents found during this release, and the check each became (M22.06)

| Incident | Check added |
|---|---|
| A dropped folder never reached the desktop's corpus page (Tauri's native drop handler), found by G-2 on a launched build | `tests/workflow/test_desktop_drop_reaches_the_page.py` (#268) |
| A custom route with no endpoint sent the key and prompts to api.openai.com; the desktop never read `CUSTOM_BASE_URL` | `test_byok_and_profile.py`, `test_desktop_run_limits_and_endpoint_status.py`, one env reader `local.provider_keys_from_env` and an AGENTS.md row (#274) |
| The desktop took the engine address from a `?sidecar=` query parameter, so a crafted URL could redirect API calls and the token (CodeQL #32, #33) | `lib/desktop.test.ts` loopback-only cases (#281) |
| WebKitGTK suppresses file choosers under WebDriver, so a scripted picker-cancel "passed" with no picker; recorded so no future G-2 trusts it | the closed #269 notes |
| macOS arm64 runners not acquired ("capacity constraints") cancelled release-commit jobs twice | M3.01 records re-runs; no code check applies |

## Release approval

```text
Version:            v3.1.0
Commit:             ba7c2ab80a6025c0108a379c389ecc91b36662b4
Tag:                v3.1.0 (annotated)
Release manager:    Aditya Mhaske (delegated to Claude Code, "do all for me and tag 3.1.0")

Automated checks    [x] pre-tag PASS   [x] published PASS   [ ] post-release PASS
Desktop             [x] macOS PASS     [-] Windows N/A (A-6) [-] Linux N/A (A-6)
Web                 [ ] Landing PASS   [ ] Download PASS    [ ] Releases PASS   [ ] Docs PASS
Distribution        [x] GitHub Release PASS   [x] Docker PASS   [x] Checksums PASS
Security            [x] PASS
Upgrade/migration   [x] PASS
Critical journey    [x] web PASS (fake, M10.02)   [x] desktop PASS
Known issues        [x] documented everywhere they belong
```

- [x] **Release approved** for publication (stage B). The web rows are checked after the flip deploys (Phase 14–17, M22).
