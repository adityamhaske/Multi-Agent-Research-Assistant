# Release record — vX.Y.Z

Copied from `release-audit/TEMPLATE.md` at the start of the release (RELEASE.md, M0.01).
Everything a person decided, checked or accepted for this release is written here; everything
a machine checked is in the audit JSON beside it. Nothing is marked PASS without evidence a
reader can re-check.

| | |
|---|---|
| Version | vX.Y.Z |
| Previous release | vPREV |
| Release manager | |
| Release commit (tag target) | |
| Tag | vX.Y.Z (annotated) |
| Tag date | |
| Audit evidence | `pre-tag.json`, `published.json`, `post-release.json` in this directory |

Result values: `PASS` · `FAIL` · `N/A` (why it does not apply) · `NOT RUN` (why not) ·
`ACCEPTED` (a known failure the sign-off accepts, with the reason) · `PENDING`.

---

## Scope

Every PR merged since the previous release, in or out (A2.01 fails on a `#N` missing here).
Version rationale (M0.03):

| Feature / fix | PRs | Implementation | Tests | UI | API | Desktop | Docs | Website | Release notes | Known limitations | Status |
|---|---|---|---|---|---|---|---|---|---|---|---|
| | | | | | | | | | | | Shipped / Partial / Deferred |

Deferred (merged but not part of this release's story):

Eval waiver: <!-- only if A2.03 requires one; delete otherwise -->

## Desktop artifacts (M6.01)

Packaged artifacts only — source-checkout evidence goes in its own row and never satisfies
a desktop check (M6.03).

| Artifact | SHA-256 | OS | Arch | Version (installed) | Engine git SHA | Install | Launch | Journey |
|---|---|---|---|---|---|---|---|---|
| `Research.Assistant_X.Y.Z_aarch64.dmg` | | macOS | arm64 | | | | | |
| `Research.Assistant_X.Y.Z_x64_en-US.msi` | | Windows | x64 | | | | | |
| `Research.Assistant_X.Y.Z_amd64.AppImage` | | Linux | x86-64 | | | | | |
| `Research.Assistant_X.Y.Z_amd64.deb` | | Linux | x86-64 | | | | | |

## Container images

| Image | Digest (`X.Y.Z`) | amd64 | arm64 | Provenance revision | Runs (M10.x) |
|---|---|---|---|---|---|
| api | | | | | |
| worker | | | | | |
| frontend | | | | | |

## Automated audit

| Stage | Command | Verdict | Counts | Evidence |
|---|---|---|---|---|
| pre-tag | `release_audit.py --version X.Y.Z` | | | `pre-tag.json` |
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
| M8.03 | PENDING | Install completes; Start-menu entry exists; Settings → Apps shows version `X.Y.Z`; files under `C:\Program… — evidence: |
| M8.04 | PENDING | Launch: the window opens without a crash; Task Manager shows `research-sidecar.exe`; no firewall prompt… — evidence: |
| M8.05 | PENDING | `python scripts\check_packaged_sidecar.py --search "C:\Program Files\Research Assistant" --expect-sha <tag… — evidence: |
| M8.06 | PENDING | The Phase 20 desktop journey on Windows (M20.02), from a user whose profile path has a space; exports save… — evidence: |
| M8.07 | PENDING | Local storage: data under `%USERPROFILE%\.research-engine`; provider keys in Windows Credential Manager,… — evidence: |
| M8.08 | PENDING | Quit: `research-sidecar.exe` exits (the watchdog — two Windows-only crashes lived here, #113) — evidence: |
| M8.09 | PENDING | Uninstall from Settings → Apps: the Program Files directory is removed; user data remains (as documented) — evidence: |
| **Phase 9 — Linux Verification** | | |
| M9.01 | PENDING | AppImage: download, verify (`sha256sum -c SHA256SUMS --ignore-missing`), `chmod +x`, launch from a desktop… — evidence: |
| M9.02 | PENDING | `.deb`: `sudo apt install ./Research.Assistant_X.Y.Z_amd64.deb` on a clean supported Ubuntu LTS resolves… — evidence: |
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
| M18.01 | PENDING | Review `git diff vPREV..HEAD` for debug flags, test accounts, credentials, private URLs, and anything that… — evidence: |
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
| M20.03 | PENDING | Negative paths on the published build: an invalid provider key is refused before it is stored; a run… — evidence: |
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
Version:            vX.Y.Z
Commit:
Tag:                vX.Y.Z (annotated)
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
