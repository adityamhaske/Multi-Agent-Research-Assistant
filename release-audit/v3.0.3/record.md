# Release record — v3.0.3

Copied from `release-audit/TEMPLATE.md` at the start of the release (RELEASE.md, M0.01).
Everything a person decided, checked or accepted for this release is written here; everything
a machine checked is in the audit JSON beside it. Nothing is marked PASS without evidence a
reader can re-check.

Stage A (prepare) was run on 2026-10-25 from an Apple Silicon Mac, on the release branch
`release/v3.0.3` cut from `origin/main` at `41b7bf4`. Every row below that needs the merged
release commit, the tag or the published artifacts is `PENDING`.

| | |
|---|---|
| Version | v3.0.3 |
| Previous release | v3.0.2 (`0a9de70`) |
| Release manager | Aditya Mhaske (stage A prepared with Claude Code; the sign-off is the release manager's) |
| Release commit (tag target) | PENDING — the merge of the release PR into `main` |
| Tag | v3.0.3 (annotated) |
| Tag date | PENDING |
| Audit evidence | `pre-tag.json`, `published.json`, `post-release.json` in this directory |

Result values: `PASS` · `FAIL` · `N/A` (why it does not apply) · `NOT RUN` (why not) ·
`ACCEPTED` (a known failure the sign-off accepts, with the reason) · `PENDING`.

---

## Scope

Every PR merged since the previous release, in or out (A2.01 fails on a `#N` missing here).
Version rationale (M0.03): **patch**. The release ships the four fixes 3.0.2's notes promised
"for the next release" — three of them found by 3.0.2's own release checks — and the
bookkeeping that closed 3.0.2. Nothing adds a capability: #202 makes the desktop do what its
Settings, its docs, the server and the CLI already said it did, and moves two existing routes
above the one that shadowed them, with the same paths and bodies. No route is added or
reshaped, and there is no migration, ORM model or bundle-format change (A19.02). The 3.1
corpus work is not in this release.

Added to scope on 2026-10-25 with the release manager's approval, relayed by the planning
session: **the corpus privacy-copy correction**. Eight surfaces promised that a corpus-only
run sent nothing over the network, and the login page called local indexing "offline"; the
code enforces only that the evidence and its retrieval stay local. Per the owner's
follow-up, every surface keeps four things separate — evidence from the uploaded corpus;
web search off; indexing on a local model; and the question and excerpts going to whichever
provider each research model (planner, executor, critic, synthesizer) uses, a cloud
provider unless local models were chosen — and none implies that local indexing makes a run
offline. Correcting an overclaim is a fix, so it is eligible for a patch. It changes no
behaviour except one error message's wording and the corpus chat scope's text, which is
also the chat model's scope instruction.

| Feature / fix | PRs | Implementation | Tests | UI | API | Desktop | Docs | Website | Release notes | Known limitations | Status |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Desktop research on Ollama, or a Custom Endpoint, with no API key: the run is no longer refused, Settings offers local models, the endpoint URL saves, and the Local LLM default skips chat-only models (3.0.2 Finding 14) | #202 | `research_engine/local.py` `providers_missing_a_key`, `usable_providers` (one rule for the CLI and the desktop); `sidecar.py` `provider_keys`, route order; `ProviderPicker.tsx` | `test_desktop_local_models_without_a_key.py` (7 cases; five failed before the fix — v3.0.2 record, Finding 14); `ProviderPicker.test.tsx`; sidecar ratchet tests | ✓ Settings → Models, the run form | ✓ the desktop's catalog answer and custom-endpoint routes; no shape change | ✓ desktop-only — packaged check at stage B (X1) | ✓ docs/22, docs/23 already describe it; AGENTS.md row added | — | ✓ | — | Shipped (source); packaged PENDING |
| The per-account sign-in limit counts failures only (3.0.2 Finding 11) | #200 | `auth.login` reads the counter with `rate_limit.peek`, raises it on a failure | `test_login_rate_limit.py` (real Redis, real app; six correct logins failed before) | — | ✓ `/auth/login` behaviour; no shape change | n/a — the desktop has no sign-in | ✓ docs/06 §4, docs/34, docs/36 already said so | — | ✓ | — | Shipped |
| Settings → Appearance hydrates without React error 418 (3.0.2 Finding 12) | #201 | `useMounted` hook; `AppearanceSection`, `ThemeToggle`, `RelativeTime` | `AppearanceSection.test.tsx` (server render hydrated with the browser's theme; failed before) | ✓ | — | ✓ same frontend | — | — | ✓ | — | Shipped; published image checked at stage B (X2) |
| The public site stops fetching `/api/v1/projects` (3.0.2 Finding 15) | #205 | `ActiveProjectProvider` moved from the root `Providers` to the `(app)` layout | `Providers.test.tsx` (failed before, on that request); `(app)/layout.test.tsx` | ✓ | — | ✓ same frontend (the provider still wraps every app page) | ✓ frontend/AGENTS.md | ✓ every site page | ✓ | — | Shipped; live site checked at stage C (X4) |
| v3.0.2 offered for download (the previous release's flip): `unreleased` dropped, dated, download page's installed size corrected to ~150 MB, RELEASE.md's M7.02, M15.01 and M20.03 text corrected | #203 | `releases.ts`, the changelog, `download/page.tsx`, RELEASE.md, the v3.0.2 record | the published and post-release audits | ✓ | — | — | ✓ RELEASE.md | ✓ | ✓ changelog *Process* | — | Shipped (process) |
| v3.0.2's post-release audit committed | #204 | `release-audit/v3.0.2/post-release.json`, the v3.0.2 record | — | — | — | — | — | — | ✓ changelog *Process* | — | Shipped (process) |
| v3.0.2's notes and record say #202 and #205 are on `main` | #206 | `releases.ts` (3.0.2 known), the changelog, the v3.0.2 record | release-entry tests | — | — | — | — | ✓ releases page | ✓ changelog *Process* | — | Shipped (process) |
| Corpus-only mode described as what it enforces — evidence from the corpus, web search off, local indexing — and what it does not: the research models' provider, on every surface; chat's *My corpus* scope states the desktop's one shared corpus | #210 | README; docs/user-guide/25, 28; docs/getting-started/01, 20, 22; docs/architecture/04, 13; docs/project/10; `comparison.ts`, the landing page, the corpus, login, license and source pages, `LocalLLMCard`, `ScopeSelector`; `chat_scope.py` copy; `schemas/research.py`, `runconfig.py`, `ports.py`, `tools.py`, `embeddings.py`, `corpus.py` (the remote-embedder error message), comments in `adapters.py`, `pipeline_runner.py`, `sidecar.py` | `test_corpus_privacy_copy.py` — both claim kinds (no-network absolutes, and local indexing equated with offline), with negative controls from the old copy; fails on `main`'s copy of eight of those files, passes here; `test_corpus_egress.py` updated to the new message | ✓ | — (one error message's wording) | ✓ the scope copy is shared, and now true on both hosts | ✓ | ✓ landing page, `/why` | ✓ | ✓ two items added | Shipped |
| `vite` 8.1.5 → 8.3.5 in the frontend lockfile, past Dependabot alert #43 (high, GHSA-587h-7wmj-h5pm) and the moderate #42 and #44 | #208 | `frontend/package-lock.json` only | CI on the PR: every required check green; merged 2026-10-26 as `119fdbc` on the release manager's instruction, during stage A (Finding 1), then lint, typecheck, tests and all three builds re-run on the release branch | — | — | ✓ same frontend (a dev dependency: the test runner and the React plugin) | — | — | ✓ changelog *Process* | — | Shipped |
| This release's preparation: version, notes, changelog, this record, the template's M20.03 text | #210 | `VERSION` and its carriers, `releases.ts`, the changelog, this record, `TEMPLATE.md` | `--stage ci`; release-entry tests; the full CI suite run locally (below) | — | — | — | — | ✓ releases.ts (unreleased) | ✓ | — | Shipped (process) |

Deferred (merged but not part of this release's story): none.

### Evaluation (A2.03, M2.04)

The corpus scope's copy in `chat_scope.py` is also the text of the chat model's
`RETRIEVAL SCOPE` instruction, so this release changes one sentence a chat model reads. It is
not an A2.03 path and the release evaluation does not exercise chat; the change narrows what
the instruction claims and asks the model to do nothing new.

No quality path changed since v3.0.2 — `git diff --stat v3.0.2 HEAD` over A2.03's
`QUALITY_PATHS` (prompts, prompt composition, graph, routing rules, retrievers, tools, claims,
citation rate, catalog, model routing) is empty — so this release needs neither a new
evaluation nor a waiver. The notes say citation support was last measured for 3.0.2
(`eval-2026-10-19-custom.json`, 96.9%) and that nothing it measured has changed.

### Stage A results (on `release/v3.0.3`, before the PR)

Run on 2026-10-25/26 on this branch's tree (Apple Silicon) — last on its final state, after
the privacy-copy correction and the merge of `main` with #208 — with the commands CI runs (root
AGENTS.md, "What CI actually enforces"). CI on the PR and on the release commit is what A3.01
judges; this is the local run before it.

| Suite | Environment | Result |
|---|---|---|
| `ruff check` / `ruff format --check` over `app/ research_engine/ tests/ evals/` | Python 3.14.8, fresh venv from `requirements.txt` | clean; 301 files formatted |
| `alembic upgrade head` | throwaway `pgvector/pgvector:pg16` and `redis:7-alpine` containers, CI's env | to `0027_run_prompt_provenance` |
| Migration gate (round trip, downgrade policy, desktop column sync) | same | 59 passed, **0 skipped** |
| `python -m pytest tests/` | same | **2159 passed, 1 skipped** (2155 before the four guard tests were added). The skip is `test_export.py::test_render_pdf_emits_a_real_pdf_where_libs_exist` — WeasyPrint's native libraries are not on this Mac; CI installs them (`libpango`) |
| `npm ci`, `npm run lint`, `npm run typecheck` | Node 26.12.0, npm 11.20.0, on the merged lockfile (vite 8.3.5) | clean; no engine warnings |
| The four CI greps (raw HTML, hex colours, backend URLs, web storage) | `/usr/bin/grep`, the `ci.yml` commands | no match |
| `npm test` | Node 26 | 64 files, **504 passed** |
| `npm run build`, `npm run build:desktop`, `build:pages` (from a copy, as `pages.yml` does) | Node 26 | all three built; the export holds 34 docs pages and no governance or planning directory |
| `npm audit --audit-level=critical` | Node 26 | exit 0: no critical. Before #208: 5 advisories, 3 high (`undici` under jsdom, `vite` under vitest and the React plugin, `zod` under the React-hooks lint plugin) and 2 moderate (`@vitest/mocker`). After: 4 — `undici` and `zod` high, `@vitest/mocker` moderate — every one in the test or lint toolchain, none in the standalone server bundle (`.next/standalone/node_modules` holds 11 entries: `@img`, `@next`, `@swc`, `client-only`, `detect-libc`, `next`, `react`, `react-dom`, `semver`, `sharp`, `styled-jsx`). See Finding 1 for the one Dependabot also reports |
| `release_audit.py --stage ci --version 3.0.3` | Python 3.14 | **24/24 PASS** |

## Desktop artifacts (M6.01)

Packaged artifacts only — source-checkout evidence goes in its own row and never satisfies
a desktop check (M6.03). All PENDING until the tag's `Desktop` run publishes them.

| Artifact | SHA-256 | OS | Arch | Version (installed) | Engine git SHA | Install | Launch | Journey |
|---|---|---|---|---|---|---|---|---|
| `Research.Assistant_3.0.3_aarch64.dmg` | PENDING | macOS | arm64 | | | | | |
| `Research.Assistant_3.0.3_x64_en-US.msi` | PENDING | Windows | x64 | | | | | |
| `Research.Assistant_3.0.3_amd64.AppImage` | PENDING | Linux | x86-64 | | | | | |
| `Research.Assistant_3.0.3_amd64.deb` | PENDING | Linux | x86-64 | | | | | |

## Container images

| Image | Digest (`X.Y.Z`) | amd64 | arm64 | Provenance revision | Runs (M10.x) |
|---|---|---|---|---|---|
| api | PENDING | | | | |
| worker | PENDING | | | | |
| frontend | PENDING | | | | |

## Automated audit

| Stage | Command | Verdict | Counts | Evidence |
|---|---|---|---|---|
| ci | `release_audit.py --stage ci --version 3.0.3` on the release branch | PASS | 24 PASS | not committed — the `ci` stage is the per-commit check CI repeats on every push |
| pre-tag | `release_audit.py --version 3.0.3` | PENDING — after the release PR merges | | `pre-tag.json` |
| published | `… --published --download --docker` | PENDING | | `published.json` |
| post-release | `… --post-release --download --docker` | PENDING | | `post-release.json` |

Disposition of every WARN and UNAVAILABLE (M21.01):

| Check | Result | Disposition |
|---|---|---|
| — | — | None yet: the `ci` stage had no WARN or UNAVAILABLE |

## Manual checks

One row per `M…` item in RELEASE.md (A21.01 fails on a missing row).

| ID | Result | Check — evidence |
|---|---|---|
| **Phase 0 — Release Scope Freeze** | | |
| M0.01 | PASS | Create the release record — Created 2026-10-25 from TEMPLATE.md on `release/v3.0.3`, cut from `origin/main` at `41b7bf4`, before any version carrier changed |
| M0.02 | PASS | Freeze the scope: list every feature and fix in the record's Scope table, each with its PR numbers — Scope table above: every first-parent merge in `v3.0.2..41b7bf4` — #200, #201, #202, #203, #204, #205, #206 (`git log --first-parent --oneline v3.0.2..origin/main`; all merge commits), then #208, merged during stage A on the release manager's instruction — plus this release's own PR, #210. Nothing deferred |
| M0.03 | PASS | Choose the version number and record why: major for a breaking change (API contract, bundle format a… — Patch — reasoning under Scope: four fixes and release bookkeeping; no route added or reshaped, no migration, model or bundle-format change (A19.02) |
| M0.04 | PASS | Carry forward known limitations: start this release's `known` from the previous release's, and remove an… — `known` starts from 3.0.2's 22 items. Three removed with their fixes as evidence: the sign-in limit (#200, `test_login_rate_limit.py`), the Appearance hydration error (#201, `AppearanceSection.test.tsx`), desktop keyless research (#202, `test_desktop_local_models_without_a_key.py`). Two reworded to stay true: doubled evidence now says "before 3.0.2", and the citation-support item names 3.0.2's run, since nothing it measured changed. The other 17 carried unchanged. Two added with the privacy-copy correction: corpus-only mode does not keep model calls local, and desktop projects share one corpus. 21 in all. Details under Known issues |
| **Phase 1 — Repository / Version Consistency** | | |
| M1.01 | PASS | Bump and derive, in this order: `VERSION`; the new `releases.ts` entry at the top with `unreleased: true`… — `VERSION` 3.0.3; the 3.0.3 entry at the top of `releases.ts` with `unreleased: true`, written before `sync_version.py`; `sync_version.py` reported drift in `main.py`, `tauri.conf.json` and `Cargo.toml`; `--write` → "consistent across 4 files"; `cargo update -p research-desktop` → Cargo.lock 3.0.3; changelog `## v3.0.3 — unreleased` with **Known**. `--stage ci`: 24/24 PASS |
| M1.02 | PASS | Search for stale references the scanner cannot see: images and screenshots with text in them, the… — `git grep` for 3.0.2/v3.0.2, `releases/download/`, `ghcr.io/…:<tag>`: every hit is incident history (RELEASE.md's table, AGENTS.md, comments in `stamp_image.py`, `start.sh` and `release_checks`), a test fixture, an npm package that happens to be at 3.0.2, or a URL template built from `releases.ts`; no `ghcr.io` tag is pinned anywhere; the OpenGraph image names no version |
| M1.03 | PASS | Review every line A1.09 flags, one by one — A1.09 PASS — it flags no line: this release adds no version mention to user-facing text. The new mentions are in `releases.ts` and the changelog (version histories by design), and this record |
| **Phase 2 — Feature Completeness** | | |
| M2.01 | PASS | Fill the feature matrix in the record for every scope row: Implementation · Tests · UI · API · Desktop ·… — Matrix under Scope. Every fix row is Shipped on source evidence; #202's packaged-desktop column and #201's published-image check are confirmed at stage B (Extra checks) |
| M2.02 | PENDING | For every feature on both hosts, confirm the desktop really has it: the route exists and behaves… — #202 is desktop-only and makes the desktop match what the server and CLI already did; it is satisfied only by the packaged app (Extra checks X1). #200 is server-only by design (the desktop has no sign-in). #201 and #205 are the same frontend on every host |
| M2.03 | PASS | Read the `releases.ts` entry and the changelog entry against the matrix: `improved` states user-visible… — Read against the matrix: `improved` states user-visible effects only, one item per fix (four for #202's four defects, two for the privacy-copy correction); `known` is 3.0.2's minus the three fixed, two reworded to stay true, plus the two limitations the corrected copy now states; each summary compresses its list and adds nothing (A1.05 PASS; `releases.test.ts` bounds) |
| M2.04 | N/A | If A2.03 fails: run the release evaluation (`docs/developers/08-testing-and-evaluation.md`, "The release… — A2.03 does not require it: no quality path changed since v3.0.2 (`git diff --stat v3.0.2 HEAD` over `QUALITY_PATHS` is empty). #202 changes which runs the desktop refuses up front and the run form's default Local LLM, not what a run does with a model |
| **Phase 3 — Automated Testing** | | |
| M3.01 | PENDING | Explain every re-run: any required job on the release commit that passed only on a retry is recorded with… — Read on the release commit's CI, Desktop and Pages runs once the release PR merges |
| M3.02 | PENDING | Read the non-blocking dependency-audit output of the release commit's CI run — On the release commit's CI. Locally on this branch (Node 26): `npm audit --audit-level=critical` — see Stage A results |
| **Phase 4 — Backend / API Verification** | | |
| M4.01 | PASS | If `backend/app/api/` changed since the previous release, `docs/reference/34-api.md` and `35-sse.md`… — `backend/app/api` changed in `auth.py` only (#200): the account counter is read with `peek` and raised on a failure; no shape change, and docs/34 and docs/06 §4 already said "5 failures / 15 min" — they were right and the code was wrong. The sidecar's two custom-endpoint routes moved above `/desktop/keys/{provider}` with the same paths and bodies (#202). Contract hash: re-read on the stage B stack |
| M4.02 | PENDING | On the published images (Phase 10 stack), probe the boundaries: an unauthenticated `GET /api/v1/projects`… — Stage B, on the published images; adds #200's behaviour (Extra checks X3) |
| **Phase 5 — Frontend Verification** | | |
| M5.01 | PENDING | On the Phase 10 stack, open dashboard, a project, a finished run (report, evidence, citations), Settings… — Stage B; Settings → Appearance must load with no React error 418 this time (Extra checks X2) |
| M5.02 | PENDING | Keyboard-only pass over the two gates: plan approval and report approval are reachable and operable… — PENDING — stage B, on the published artifacts |
| **Phase 6 — Desktop Application Verification** | | |
| M6.01 | PENDING | Record the artifact table in the record for all four installers: file name · SHA-256 · OS · architecture ·… — PENDING — stage B, on the published artifacts |
| M6.02 | PENDING | On every platform, run the packaged-engine checker against the **installed** copy of the **published**… — PENDING — stage B, on the published artifacts; Windows and Linux need machines |
| M6.03 | PENDING | Mark every desktop row in the record as *packaged* or *source* — PENDING — stage B, on the published artifacts |
| **Phase 7 — macOS Verification** | | |
| M7.01 | PENDING | Download the `.dmg` from the release in a browser (so it carries the quarantine flag) and verify it — PENDING — stage B, on the published artifacts |
| M7.02 | PENDING | The DMG opens and holds the app at the right version — PENDING — stage B, on the published artifacts; ~150 MB, not ~5 MB |
| M7.03 | PENDING | The signature is whole and valid — PENDING — stage B, on the published artifacts |
| M7.04 | PENDING | Gatekeeper judges a quarantined copy as policy, not damage — PENDING — stage B, on the published artifacts |
| M7.05 | PENDING | The bundled engine is present, native, and unmodified by hardened runtime — PENDING — stage B, on the published artifacts |
| M7.06 | PENDING | The packaged engine identifies itself and completes the journey — PENDING — stage B, on the published artifacts |
| M7.07 | PENDING | First launch as a user: drag to Applications; open it *without* the command and confirm the block is the… — PENDING — stage B, on the published artifacts |
| M7.08 | PENDING | The Phase 20 desktop journey on macOS (M20.02) — Stage B: the published app, Ollama running, **no key stored** — 3.0.2's Finding 14, which this release fixes (Extra checks X1) |
| M7.09 | PENDING | Quit the app; no engine is left running — PENDING — stage B, on the published artifacts |
| **Phase 8 — Windows Verification** | | |
| M8.01 | PENDING | Download the `.msi` in a browser; verify it — PENDING — stage B; needs a Windows machine (3.0.2 had none: NOT RUN) |
| M8.02 | PENDING | SmartScreen shows the unknown-publisher warning; **More info → Run anyway** proceeds, exactly as the… — PENDING — stage B; needs a Windows machine (3.0.2 had none: NOT RUN) |
| M8.03 | PENDING | Install completes; Start-menu entry exists; Settings → Apps shows version `X.Y.Z`; files under `C:\Program… — PENDING — stage B; needs a Windows machine (3.0.2 had none: NOT RUN) |
| M8.04 | PENDING | Launch: the window opens without a crash; Task Manager shows `research-sidecar.exe`; no firewall prompt… — PENDING — stage B; needs a Windows machine (3.0.2 had none: NOT RUN) |
| M8.05 | PENDING | `python scripts\check_packaged_sidecar.py --search "C:\Program Files\Research Assistant" --expect-sha <tag… — PENDING — stage B; needs a Windows machine (3.0.2 had none: NOT RUN); CI drives the installed `.msi`'s engine (A6.02) |
| M8.06 | PENDING | The Phase 20 desktop journey on Windows (M20.02), from a user whose profile path has a space; exports save… — PENDING — stage B; needs a Windows machine (3.0.2 had none: NOT RUN) |
| M8.07 | PENDING | Local storage: data under `%USERPROFILE%\.research-engine`; provider keys in Windows Credential Manager,… — PENDING — stage B; needs a Windows machine (3.0.2 had none: NOT RUN) |
| M8.08 | PENDING | Quit: `research-sidecar.exe` exits (the watchdog — two Windows-only crashes lived here, #113) — PENDING — stage B; needs a Windows machine (3.0.2 had none: NOT RUN) |
| M8.09 | PENDING | Uninstall from Settings → Apps: the Program Files directory is removed; user data remains (as documented) — PENDING — stage B; needs a Windows machine (3.0.2 had none: NOT RUN) |
| **Phase 9 — Linux Verification** | | |
| M9.01 | PENDING | AppImage: download, verify (`sha256sum -c SHA256SUMS --ignore-missing`), `chmod +x`, launch from a desktop… — PENDING — stage B; needs a Linux machine (3.0.2 had none: NOT RUN); CI drives the AppImage's engine (A6.02) |
| M9.02 | PENDING | `.deb`: `sudo apt install ./Research.Assistant_X.Y.Z_amd64.deb` on a clean supported Ubuntu LTS resolves… — PENDING — stage B; needs a Linux machine (3.0.2 had none: NOT RUN); CI installs the `.deb` and drives its engine (A6.02) |
| M9.03 | PENDING | Key storage uses the Secret Service keyring; on a session without one, the app says so rather than storing… — PENDING — stage B; needs a Linux machine (3.0.2 had none: NOT RUN) |
| M9.04 | PENDING | `sudo apt remove research-assistant` removes the application; user data remains; no engine left running — PENDING — stage B; needs a Linux machine (3.0.2 had none: NOT RUN) |
| **Phase 10 — Docker / Container Verification** | | |
| M10.01 | PENDING | Run the published images on the full-stack topology, on their own volumes: — PENDING — stage B, on the published artifacts |
| M10.02 | PENDING | On that stack: register, log in, create a project, run a fake-mode research through both gates, export… — PENDING — stage B, on the published artifacts |
| M10.03 | PENDING | On an arm64 host (Apple Silicon Docker or the Ampere target), the same stack starts from the same tags — PENDING — stage B, on the published artifacts |
| M10.04 | PENDING | Tear down with `down -v` using the same flags; the developer's own `mara_full_*` volumes are untouched — PENDING — stage B, on the published artifacts |
| **Phase 11 — GitHub Release Verification** | | |
| M11.01 | PENDING | Add the hand-written summary at the top of the Release body (what changed for users, the macOS… — Stage B, after the tag creates the Release |
| **Phase 12 — Documentation Verification** | | |
| M12.01 | PASS | For each scope row, the docs describe what shipped — on both hosts, with desktop differences stated… — #200: docs/06 §4, docs/34 and docs/36 already state "5 failures per 15 min per account", which is now true. #202: docs/23 and docs/22 already describe Ollama as a keyless path on the desktop, which is now true; nothing documented the bug. #201, #205: no doc describes them. Privacy copy: every doc that described corpus-only mode now states what it enforces (Scope table), and docs/28 states the desktop's shared corpus. Desktop differences: #202 is the desktop catching up with the server; the desktop's one corpus is now stated wherever per-project scope was claimed in copy this release touched (not on the corpus page — Finding 8). Unrelated, pre-existing: Finding 3 |
| M12.02 | N/A | Configuration: every environment variable added, renamed or removed since the previous release (`git diff… — No environment variable added, renamed or removed: `git diff v3.0.2 HEAD -- backend/app/config.py .env.example` is empty, and `research_engine/local.py`'s diff adds two functions and reads no new variable |
| M12.03 | PASS | Search the docs for removed or renamed features, commands and routes named in the diff (`git diff --stat… — Nothing removed or renamed; the custom-endpoint routes keep their paths (#202). `git grep` for the 3.0.2 workaround ("Custom Endpoint key", "No provider key found") finds it only in the 3.0.2 notes, where it belongs. For the privacy copy: `git grep -i` over `docs/`, `frontend/`, `backend/app`, `backend/research_engine` and the README for "network call", "zero network", "airgap", "air-gap", "nothing leaves", "never leaves" and "offline": every absolute corpus claim rewritten; what remains is the bundle verifier being offline (true), the guard's name ("airgap guard"), history comments saying the old claim was false, and honest negations |
| M12.04 | N/A | Architecture docs (`docs/architecture/02`, `04`) match the graph's nodes and gates — Graph nodes and gates unchanged — no change to `graph.py` since v3.0.2 |
| M12.05 | PENDING | Known limitations agree across `releases.ts` `known`, the changelog **Known**, the Release body and the… — `releases.ts` known (21 items) and the changelog's **Known** (3.0.3's own six plus 3.0.1's, carried) agree on this branch; the Release body is written at stage B |
| **Phase 13 — README Verification** | | |
| M13.01 | PASS | Read the README top to bottom against the release: the feature list (nothing unreleased, nothing removed),… — README unchanged since v3.0.2 (`git diff --stat v3.0.2 HEAD -- README.md` is empty). Its features, platforms and commands are unaffected by four fixes; the measured claim is A1.14 (PASS) |
| **Phase 14 — Landing Page Verification** | | |
| M14.01 | PENDING | View `/` at desktop width and at 375 px, light and dark: hero, download call-to-action, "New in" link to… — PENDING — stage C, after the flip PR deploys |
| M14.02 | PENDING | `/why`: every comparison claim (`frontend/lib/comparison.ts`) still holds for this release — PENDING — stage C, after the flip PR deploys; v3.0.2's Finding 16 (the site's 96.4% is unattributed) is still open |
| **Phase 15 — Download Page Verification** | | |
| M15.01 | PENDING | On each OS (or with a UA override), the detected-OS card leads; the big button and every card button point… — PENDING — stage C, after the flip PR deploys |
| M15.02 | PENDING | Download one installer by clicking the page's button in a real browser; the file name and checksum are right — PENDING — stage C, after the flip PR deploys |
| **Phase 16 — Releases Page Verification** | | |
| M16.01 | PENDING | View `/releases`: the new entry is first with the tag's date; its summaries are shown and the lists fold… — PENDING — stage C, after the flip PR deploys |
| **Phase 17 — GitHub Pages / Deployment Verification** | | |
| M17.01 | PENDING | If A17.01 fails because `main` moved after the flip, wait for the newer deploy and re-run; if the deploy… — PENDING — stage C, after the flip PR deploys |
| **Phase 18 — Security / Configuration Verification** | | |
| M18.01 | PASS | Review `git diff vPREV..HEAD` for debug flags, test accounts, credentials, private URLs, and anything that… — Added lines since v3.0.2 searched for prints, debuggers, credentials, test accounts and private URLs: every hit is a comment or a test fixture (`http://test`, a loopback Ollama URL, a test token); no credential, no debug flag |
| M18.02 | PASS | If `backend/app/config.py`, the security middleware, auth, or the SSRF guard changed: re-check CORS… — Auth changed (#200), so re-checked on the diff: the login limits are unchanged (`LOGIN_IP` 20/60 s counts every attempt; `LOGIN_EMAIL` 5/900 s now counts failures only, as docs/06 §4 states); an unknown address raises the account counter exactly as a wrong password does, so the lock cannot enumerate accounts; five failures still lock the right password out. CORS, CSP, cookies, JWT lifetimes, refresh rotation, `ENCRYPTION_KEY`, `/docs` and the SSRF guard are untouched (no diff in `config.py`, `security`, the middleware or `ssrf`). Re-probed on the published images at M4.02 |
| M18.03 | PENDING | No secret or env file ships in an artifact — PENDING — stage B, on the published artifacts |
| M18.04 | PASS | Public surface: `/api/v1/version` is unauthenticated on the server by design; nothing else new is — No route added on either host since v3.0.2: `auth.py` changed only inside `login`, and the sidecar's custom-endpoint routes were moved, not added |
| **Phase 19 — Upgrade / Migration Verification** | | |
| M19.01 | PENDING | Fresh install: an empty database migrates to head (CI), and a fresh desktop data directory starts (M6.02… — CI migrates an empty database to head on the release commit; the fresh desktop data directory is M6.02's (stage B) |
| M19.02 | N/A | Server upgrade from the previous release: run the previous release's images (`RELEASE_TAG=PREV` with the… — A19.02 has nothing to declare: no migration, ORM model or bundle-format change since v3.0.2, and the same Python (3.14) as 3.0.2 |
| M19.03 | N/A | Desktop upgrade from the previous release: install the previous release, create the same data, install… — As M19.02 — the desktop data directory's schema is unchanged. The update path a 3.0.2 desktop user takes is still exercised at M22.04 |
| M19.04 | N/A | Downgrade: CI's round-trip proves the schema reverses; record whether running the previous images against… — No migration in this release, so a 3.0.2 image against a 3.0.3 database is the same schema |
| M19.05 | PENDING | A bundle exported by the previous release verifies with this release's verifier, unchanged (`python -m… — Stage B: a 3.0.2 bundle verified by the 3.0.3 verifier — cheap, and the claim the notes repeat |
| **Phase 20 — Final End-to-End Production Smoke Test** | | |
| M20.01 | PENDING | The web/self-hosted journey on the Phase 10 stack, **with a real provider at least once** (fake mode… — PENDING — stage B, on the published artifacts |
| M20.02 | PENDING | The desktop journey on each platform (M7.08, M8.06, M9.01/M9.02), with a real provider or Ollama — Stage B: macOS with Ollama and no key (X1); Windows and Linux need machines |
| M20.03 | PENDING | Negative paths on the published build: an invalid provider key is reported as rejected by its provider as… — PENDING — stage B, on the published artifacts |
| M20.04 | PENDING | Every `[n]` in the final report resolves on hover to a source and its snippet; an unresolved one renders… — PENDING — stage B, on the published artifacts |
| **Phase 21 — Release Approval** | | |
| M21.01 | PENDING | Every WARN and UNAVAILABLE in the published audit has a written disposition in the record — Stage B |
| M21.02 | PENDING | Known issues are documented everywhere they belong (M12.05), including anything this audit found and the… — Stage B |
| M21.03 | PENDING | The release manager signs the approval block in the record — The release manager's, after stage B |
| **Phase 22 — Post-Release Verification** | | |
| M22.01 | PENDING | The flip PR: drop `unreleased`, set the entry's `date` to the tag's date, date the changelog heading,… — PENDING — stage C, after the flip PR deploys |
| M22.02 | PENDING | After Pages deploys: run the post-release audit with `--download --docker`, commit its JSON (write-once)… — PENDING — stage C, after the flip PR deploys |
| M22.03 | PENDING | Load `/`, `/why`, `/docs`, `/download`, `/releases` on a phone and a desktop browser with the cache disabled — PENDING — stage C, after the flip PR deploys; the five pages must log no 404 for `/api/v1/projects` (#205, Extra checks X4) |
| M22.04 | PENDING | In an installed copy of the **previous** desktop release, Settings → About → *Check for updates* reports… — PENDING — stage C, after the flip PR deploys; an installed 3.0.2 must report 3.0.3 |
| M22.05 | PENDING | For 48 hours, watch issues and discussions for install or launch reports; any release-blocking report… — PENDING — stage C, after the flip PR deploys |
| M22.06 | PASS | Every incident found during this release becomes a check: an `A…` check (preferred) or an `M…` item, plus… — Incidents table below: the template's stale M20.03 text, and the corpus privacy overclaim — each fixed in this PR, the second with a test |

## Findings

Found while preparing stage A, separated by kind.

**Open at stage A — the pre-tag audit depends on them**

1. **An open high-severity Dependabot alert will fail A18.05 (STOP) at pre-tag.** Alert #43,
   opened 2026-10-23: `vite` ≤ 8.1.5 (GHSA-587h-7wmj-h5pm, a `launch-editor` existence check
   bypassable on Windows), transitive under `vitest` and `@vitejs/plugin-react` — development
   scope, used by the test runner and nothing the standalone server, the desktop export or the
   site ships. Four moderate alerts (#42, #44-#46) sit beside it. Dependabot's #208 (vite
   8.1.5 → 8.3.5) and #209 (`@vitest/mocker`, `vitest`) are open. A18.05 counts severity, not
   scope, so the pre-tag audit stops until #208 merges or the alert is dismissed with a reason.
   **The release manager's call**, as #183-#185 were for 3.0.2; if merged, each joins the scope
   table here before the pre-tag run (A2.01).

   **Resolved for #43:** the release manager chose to merge #208, which went in on 2026-10-26
   as `119fdbc` (all required checks green) and is in the scope table; GitHub marked #43
   fixed at 01:38:16Z. **Still open:** the rescan of the new lockfile opened alert #50 one
   second later — `undici` < 8.12.2 (high, GHSA-xjj6-f33q-929c, denial of service on
   excessive content-encodings), transitive under `jsdom`, the test environment, development
   scope, not in the standalone bundle. No Dependabot PR exists for it yet. A18.05 will stop
   the pre-tag audit on it as it did on #43, so it needs the same decision. The moderate
   #45 and #46 (`@vitest/mocker`, fixed by #209) do not stop it.
2. **#207 is open.** It records v3.0.2's 48-hour watch (M22.05). If it merges before the
   release commit, A2.01 needs it in the scope table, as a process row.

**Pre-existing, not in this release's scope**

3. **The desktop guide says a provider key is validated before it is stored, and it is not.**
   docs/getting-started/23-desktop-app.md, "Configure a model": "A key is never written to the
   keychain until it has answered a real request." `PUT /desktop/keys/{provider}`
   (`sidecar.py::set_key`) stores any non-empty key at once, and the frontend's
   `useSetDesktopKey` calls it directly. The server's design is the reverse of the doc too —
   saving is testing, and a failed check never blocks the save (RELEASE.md M20.03, reworded in
   #203). Unchanged by this release; a docs fix is a follow-up, not part of this patch.

**Release-process defects (fixed in this PR)**

4. **The record template still carried M20.03's old wording.** #203 reworded M20.03 in
   RELEASE.md to the shipped behaviour (an invalid key is reported as rejected once saved), but
   `TEMPLATE.md`'s row still said "refused before it is stored". The template row now matches.

**Decided in preparation**

5. **3.0.2's notes keep their three "Fixed for the next release" items.** They were true of
   3.0.2 as shipped, and `releases.ts`'s rule is that a release that shipped with a known gap
   says so. They are not carried into 3.0.3's `known`; they are 3.0.3's `improved`. The flip PR
   may reword "Fixed for the next release" to "Fixed in 3.0.3" once 3.0.3 is offered — before
   then the old wording is the accurate one.

**Carried over from the v3.0.2 record, still open**

6. The site's headline citation figure (96.4%, 3.0.0's run) is unattributed in `lib/features.ts`
   and `lib/comparison.ts` (v3.0.2 Finding 16) — the release manager's call.
7. Two historical release dates disagree with their tags (A16.03 WARN): v1.0.0 and v1.0.2.

**Found while correcting the privacy copy, not fixed**

8. **The corpus management page says the corpus is "Scoped to" the active project, which is
   false on the desktop app**, where every project shares one `corpus.sqlite`. Not one of the
   privacy surfaces this release was asked to correct, and not an egress claim; the shared
   corpus is now a stated known limitation. Follow-up: say so on the page itself, desktop only.
9. `internal/12_Launch_Plan.md` (the "docs/12 M10" the code cites) still records the absolute
   claim as an enforced milestone. It is not published; the code comments that cite it now
   say what M10 enforces.

## Extra checks this release needs

A patch of four fixes, each found by 3.0.2's release checks. Each must be seen fixed on the
**published** artifacts, the way it was seen broken — source evidence does not count (M6.03).

- **X1 (M7.08, M20.02, M2.02).** The published macOS app in a throwaway home, Ollama running,
  **no key stored**: research starts and completes through both gates, Settings → Models offers
  a local model, saving a Custom Endpoint base URL succeeds and reads back, and the run form's
  Local LLM default is not a model Settings marks chat only. 3.0.2's M7.08 failed at each of
  these steps (its Finding 14).
- **X2 (M5.01).** On the published images, full loads of Settings → Appearance in light and
  dark log no React error 418.
- **X3 (M4.02).** On the published images, six correct sign-ins to one account within 15
  minutes all succeed; five failures then lock it, the right password included; an unknown
  address answers exactly as a wrong password does.
- **X5 (M14.02, M5.01).** On the live site after the flip, `/why`'s comparison row and claim
  and the landing page's privacy card carry the corrected copy; in the published app, the
  run form's corpus help and chat's *My corpus* scope do.
- **X4 (M22.03).** On the live site after the flip, `/`, `/why`, `/docs`, `/download` and
  `/releases` request nothing from `/api/v1/` (3.0.2's M22.03 saw one 404 on each).

## Known issues shipped with this release

Everything in `frontend/lib/releases.ts` v3.0.3 `known` (21 items): 3.0.2's 22, less the three
this release fixes — the sign-in limit counting successes (#200), the Appearance page's
hydration error (#201) and the desktop refusing keyless research (#202). Two are reworded to
stay true of 3.0.3: the doubled-evidence item says "before 3.0.2" where it said "before this
release", and the citation-support item names 3.0.2's run, which still describes this code.
Two are new, stated by the privacy-copy correction: corpus-only mode keeps the evidence local
but does not stop model calls from leaving the machine, and on the desktop app every project
shares one corpus. Both were true of every earlier release; they were never written down.
The changelog's **Known** carries the same set (this release's own six lines, and 3.0.1's).

## Incidents found during this release, and the check each became (M22.06)

| Incident | Check added |
|---|---|
| Corpus-only mode was promised, on eight surfaces, to send nothing over the network, and local indexing was labelled "offline"; the code enforces local evidence only, and the egress test proves only the retrieval half because it runs with scripted models | `tests/workflow/test_corpus_privacy_copy.py`: both claim kinds on every published and user-facing surface, with negative controls; it fails on `main`'s copy |
| The record template's M20.03 row kept the wording RELEASE.md had dropped (Finding 4) | Fixed in this PR. No new check: `test_the_record_template_starts_with_a_row_for_every_manual_check` compares IDs, and the row text is a copy for the reader |

## Release approval

```text
Version:            v3.0.3
Commit:             PENDING
Tag:                v3.0.3 (annotated)
Release manager:    Aditya Mhaske

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
