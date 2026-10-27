# Release record — v3.0.3

Copied from `release-audit/TEMPLATE.md` at the start of the release (RELEASE.md, M0.01).
Everything a person decided, checked or accepted for this release is written here; everything
a machine checked is in the audit JSON beside it. Nothing is marked PASS without evidence a
reader can re-check.

Stage A (prepare) was run on 2026-10-25 from an Apple Silicon Mac, on the release branch
`release/v3.0.3` cut from `origin/main` at `41b7bf4`. Stage B (publish) was checked on 2026-10-26
on the same Mac against the published artifacts, and Stage C (offer) on the live site after the flip
(#233) deployed.

| | |
|---|---|
| Version | v3.0.3 |
| Previous release | v3.0.2 (`0a9de70`) |
| Release manager | Aditya Mhaske (stage A prepared with Claude Code; the sign-off is the release manager's) |
| Release commit (tag target) | `0c72d37` (`0c72d371a64500ef5672c83dff543df3c4f386b4`), the merge of #218 |
| Tag | v3.0.3 (annotated) |
| Tag date | 2026-10-26 (tagged 06:44Z; the Release published 06:49Z) |
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
| Desktop research on Ollama, or a Custom Endpoint, with no API key: the run is no longer refused, Settings offers local models, the endpoint URL saves, and the Local LLM default skips chat-only models (3.0.2 Finding 14) | #202 | `research_engine/local.py` `providers_missing_a_key`, `usable_providers` (one rule for the CLI and the desktop); `sidecar.py` `provider_keys`, route order; `ProviderPicker.tsx` | `test_desktop_local_models_without_a_key.py` (7 cases; five failed before the fix — v3.0.2 record, Finding 14); `ProviderPicker.test.tsx`; sidecar ratchet tests | ✓ Settings → Models, the run form | ✓ the desktop's catalog answer and custom-endpoint routes; no shape change | ✓ desktop-only — packaged check X1 partly (M7.08) | ✓ docs/22, docs/23 already describe it; AGENTS.md row added | — | ✓ | — | Shipped; on the packaged app the no-key run starts and Settings works, but the Ollama journey on the default model did not complete (M7.08, Finding 13) |
| The per-account sign-in limit counts failures only (3.0.2 Finding 11) | #200 | `auth.login` reads the counter with `rate_limit.peek`, raises it on a failure | `test_login_rate_limit.py` (real Redis, real app; six correct logins failed before) | — | ✓ `/auth/login` behaviour; no shape change | n/a — the desktop has no sign-in | ✓ docs/06 §4, docs/34, docs/36 already said so | — | ✓ | — | Shipped |
| Settings → Appearance hydrates without React error 418 (3.0.2 Finding 12) | #201 | `useMounted` hook; `AppearanceSection`, `ThemeToggle`, `RelativeTime` | `AppearanceSection.test.tsx` (server render hydrated with the browser's theme; failed before) | ✓ | — | ✓ same frontend | — | — | ✓ | — | Shipped; published image checked at stage B (X2) |
| The public site stops fetching `/api/v1/projects` (3.0.2 Finding 15) | #205 | `ActiveProjectProvider` moved from the root `Providers` to the `(app)` layout | `Providers.test.tsx` (failed before, on that request); `(app)/layout.test.tsx` | ✓ | — | ✓ same frontend (the provider still wraps every app page) | ✓ frontend/AGENTS.md | ✓ every site page | ✓ | — | Shipped; live site checked at stage C (X4) |
| v3.0.2 offered for download (the previous release's flip): `unreleased` dropped, dated, download page's installed size corrected to ~150 MB, RELEASE.md's M7.02, M15.01 and M20.03 text corrected | #203 | `releases.ts`, the changelog, `download/page.tsx`, RELEASE.md, the v3.0.2 record | the published and post-release audits | ✓ | — | — | ✓ RELEASE.md | ✓ | ✓ changelog *Process* | — | Shipped (process) |
| v3.0.2's post-release audit committed | #204 | `release-audit/v3.0.2/post-release.json`, the v3.0.2 record | — | — | — | — | — | — | ✓ changelog *Process* | — | Shipped (process) |
| v3.0.2's notes and record say #202 and #205 are on `main` | #206 | `releases.ts` (3.0.2 known), the changelog, the v3.0.2 record | release-entry tests | — | — | — | — | ✓ releases page | ✓ changelog *Process* | — | Shipped (process) |
| Corpus-only mode described as what it enforces — evidence from the corpus, web search off, local indexing — and what it does not: the research models' provider, on every surface; chat's *My corpus* scope states the desktop's one shared corpus | #210 | README; docs/user-guide/25, 28; docs/getting-started/01, 20, 22; docs/architecture/04, 13; docs/project/10; `comparison.ts`, the landing page, the corpus, login, license and source pages, `LocalLLMCard`, `ScopeSelector`; `chat_scope.py` copy; `schemas/research.py`, `runconfig.py`, `ports.py`, `tools.py`, `embeddings.py`, `corpus.py` (the remote-embedder error message), comments in `adapters.py`, `pipeline_runner.py`, `sidecar.py` | `test_corpus_privacy_copy.py` — both claim kinds (no-network absolutes, and local indexing equated with offline), with negative controls from the old copy; fails on `main`'s copy of eight of those files, passes here; `test_corpus_egress.py` updated to the new message | ✓ | — (one error message's wording) | ✓ the scope copy is shared, and now true on both hosts | ✓ | ✓ landing page, `/why` | ✓ | ✓ two items added | Shipped |
| `vite` 8.1.5 → 8.3.5 in the frontend lockfile, past Dependabot alert #43 (high, GHSA-587h-7wmj-h5pm) and the moderate #42 and #44 | #208 | `frontend/package-lock.json` only | CI on the PR: every required check green; merged 2026-10-26 as `119fdbc` on the release manager's instruction, during stage A (Finding 1), then lint, typecheck, tests and all three builds re-run on the release branch | — | — | ✓ same frontend (a dev dependency: the test runner and the React plugin) | — | — | ✓ changelog *Process* | — | Shipped |
| `undici` 8.12.2 under `jsdom`, via `overrides`, past Dependabot alert #50 (high, GHSA-xjj6-f33q-929c) | #210 | `frontend/package.json` `overrides` (`jsdom` → `undici` 8.12.2, inside jsdom's own `^8.10.2`); one lock entry, still `dev: true` | `npm ci` (no engine warnings), lint, typecheck, the four greps, 504 tests and all three builds on Node 26; the standalone bundle's 11 packages unchanged; `npm audit` no longer lists `undici` | — | — | ✓ same frontend (the test environment only) | — | — | ✓ changelog *Process* | — | Shipped |
| This release's preparation: version, notes, changelog, this record, the template's M20.03 text | #210, #216, #218 | `VERSION` and its carriers, `releases.ts`, the changelog, this record, `TEMPLATE.md` | `--stage ci`; release-entry tests; the full CI suite run locally (below) | — | — | — | — | ✓ releases.ts (unreleased) | ✓ | — | Shipped (process) |

Deferred (merged but not part of this release's story): none.

### Evaluation (A2.03, M2.04)

The corpus scope's copy in `chat_scope.py` is also the text of the chat model's
`RETRIEVAL SCOPE` instruction, so this release changes one sentence a chat model reads. It is
not an A2.03 path and the release evaluation does not exercise chat; the change narrows what
the instruction claims and asks the model to do nothing new.

Two quality paths changed since v3.0.2, both in the privacy-copy correction (#210), and both
only in text no model reads. `git diff v3.0.2 HEAD -- backend/research_engine/retrievers.py
backend/research_engine/tools.py` is two hunks:

- `retrievers.py`: one `#` comment ("no network calls at all" → "no retrieval egress").
- `tools.py`: the **module** docstring. The `@tool` docstrings of `web_search` and
  `read_webpage`, which are the tool descriptions the executor model receives, are unchanged.

Neither can alter what a run produces, so this release carries a waiver rather than a new
evaluation. The notes say citation support was last measured for 3.0.2
(`eval-2026-10-19-custom.json`, 96.9%) and that nothing it measured has changed.

Eval waiver: the only quality-path changes since v3.0.2 are a code comment in retrievers.py and the module docstring of tools.py (privacy-copy correction, #210); no prompt, tool description, graph, routing or retrieval logic changed, so run output cannot differ.

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
| `npm ci`, `npm run lint`, `npm run typecheck` | Node 26.12.0, npm 11.20.0, on the final lockfile (vite 8.3.5, undici 8.12.2) | clean; no engine warnings |
| The four CI greps (raw HTML, hex colours, backend URLs, web storage) | `/usr/bin/grep`, the `ci.yml` commands | no match |
| `npm test` | Node 26 | 64 files, **504 passed** |
| `npm run build`, `npm run build:desktop`, `build:pages` (from a copy, as `pages.yml` does) | Node 26 | all three built; the export holds 34 docs pages and no governance or planning directory |
| `npm audit --audit-level=critical` | Node 26 | exit 0: no critical. Before #208: 5 advisories, 3 high (`undici` under jsdom, `vite` under vitest and the React plugin, `zod` under the React-hooks lint plugin) and 2 moderate (`@vitest/mocker`). After #208: 4 — `undici` and `zod` high, `@vitest/mocker` moderate. After the `undici` override: 3 — `zod` high, `@vitest/mocker` moderate. Every one is in the test or lint toolchain, none in the standalone server bundle (`.next/standalone/node_modules` holds 11 entries: `@img`, `@next`, `@swc`, `client-only`, `detect-libc`, `next`, `react`, `react-dom`, `semver`, `sharp`, `styled-jsx`). See Finding 1 for the one Dependabot also reports |
| `release_audit.py --stage ci --version 3.0.3` | Python 3.14 | **24/24 PASS** |

## Desktop artifacts (M6.01)

Packaged artifacts only — source-checkout evidence goes in its own row and never satisfies
a desktop check (M6.03). Sizes are the published assets'; every SHA-256 matches `SHA256SUMS`.

| Artifact | SHA-256 | OS | Arch | Version (installed) | Engine git SHA | Install | Launch | Journey |
|---|---|---|---|---|---|---|---|---|
| `Research.Assistant_3.0.3_aarch64.dmg` (80.2 MB) | `0414c377b2a145bdf238062f7e2d07571110fedd3afab96c7d152ba7963a957a` | macOS | arm64 | 3.0.3 (Info.plist; packaged) | 0c72d37 — CI's bundled-copy check (M6.02) | NOT RUN — not installed here | release manager: launched (M7.07) | NOT RUN — this Mac's `syspolicyd` (M7.06) |
| `Research.Assistant_3.0.3_x64_en-US.msi` (82.1 MB) | `a8cfb4ce9c9868a8b747c3ec447b710a2f35fe90b5d1c976bac655259369aee4` | Windows | x64 | 3.0.3 — CI (packaged) | 0c72d37 — CI (A6.02) | CI only | NOT RUN — no machine | CI engine journey PASS (A6.02) |
| `Research.Assistant_3.0.3_amd64.AppImage` (191.6 MB) | `4e801584fa0089b67e3e39c8a17c092c1b15985e4d304bfb2d8ba3de3c51e317` | Linux | x86-64 | 3.0.3 — CI (packaged) | 0c72d37 — CI (A6.02) | CI only | NOT RUN — no machine | CI engine journey PASS (A6.02) |
| `Research.Assistant_3.0.3_amd64.deb` (138.0 MB) | `43f4a78c12e17268be32583fbcf6bf289878aa2f8cdb54e9cc67e37e38cf85f3` | Linux | x86-64 | 3.0.3 — CI (packaged) | 0c72d37 — CI (A6.02) | CI only | NOT RUN — no machine | CI engine journey PASS (A6.02) |

## Container images

| Image | Digest (`X.Y.Z`) | amd64 | arm64 | Provenance revision | Runs (M10.x) |
|---|---|---|---|---|---|
| api | `sha256:27ff1b16ff10d9179ec8b4a9382c562f8df6395b00014ef70fcb0453f2c898ec` (also `3.0`, `latest`) | ✓ | ✓ | 0c72d37 on both (A10.03) | M10.01-M10.04, arm64 |
| worker | `sha256:f3046d32d81cee91fc74988d7fcebb1a44c40c27f7253b73a0593daa65e0f997` (also `3.0`, `latest`) | ✓ | ✓ | 0c72d37 on both (A10.03) | M10.01-M10.04, arm64 |
| frontend | `sha256:176f518cea2616d933c72b63514a7485270b219974e1043e1f1c5605a584a98b` (also `3.0`, `latest`) | ✓ | ✓ | 0c72d37 on both (A10.03) | M10.01-M10.04, arm64 |

## Automated audit

| Stage | Command | Verdict | Counts | Evidence |
|---|---|---|---|---|
| ci | `release_audit.py --stage ci --version 3.0.3` on the release branch | PASS | 24 PASS | not committed — the `ci` stage is the per-commit check CI repeats on every push |
| pre-tag | `release_audit.py --version 3.0.3` on `0c72d37` | PASS | 34 PASS, 2 WARN | `pre-tag.json` |
| published | `… --published --download --docker`, run 2026-10-26T16:30Z | PASS | 50 PASS, 4 WARN | `published.json`. An earlier run at 07:10Z without `--docker` had A10.05 UNAVAILABLE and is superseded, not committed |
| post-release | `… --post-release --download --docker`, run 2026-10-26T17:47Z on `399c122` | PASS | 60 PASS, 4 WARN | `post-release.json`. A first run failed only A17.01 (M17.01) |

Disposition of every WARN and UNAVAILABLE (M21.01):

| Check | Result | Disposition |
|---|---|---|
| A2.03 (pre-tag) | WARN | Confirmed. The waiver's evidence is in "Evaluation" above: the two quality-path changes are a `#` comment in `retrievers.py` and the module docstring of `tools.py`, neither of which any model reads (#216 recorded it) |
| A2.03 (published) | WARN | As at pre-tag: the waiver above |
| A16.03 (published) | WARN | Historical only: v1.0.0 and v1.0.2's site dates disagree with their tags (Finding 7); 3.0.3's entry is dated 2026-10-26, the tag's date, by the flip PR |
| A19.02 (published) | WARN | As at pre-tag |
| A21.01 (published) | WARN | The audit ran before this record's stage B rows were written; the rows for Phases 14-17 and 22 are stage C and are filled after the flip deploys |
| A6.02 (post-release) | WARN | The macOS DMG-journey step (#234) was added after the tag, so the tag's run could not have it — designed to warn, not fail. The guard it adds is exactly the gap Finding 11 records for this release |
| A2.03, A16.03, A19.02 (post-release) | WARN | As at published |
| A19.02 (pre-tag) | WARN | No upgrade check is needed. The only file A19.02 flags, `backend/app/models/__init__.py`, changed in one comment word ("airgapped" → "local", the privacy-copy correction in #210); no table, column or constraint changed, so M19.02/M19.03 stay N/A as recorded |

## Manual checks

One row per `M…` item in RELEASE.md (A21.01 fails on a missing row).

| ID | Result | Check — evidence |
|---|---|---|
| **Phase 0 — Release Scope Freeze** | | |
| M0.01 | PASS | Create the release record — Created 2026-10-25 from TEMPLATE.md on `release/v3.0.3`, cut from `origin/main` at `41b7bf4`, before any version carrier changed |
| M0.02 | PASS | Freeze the scope: list every feature and fix in the record's Scope table, each with its PR numbers — Scope table above: every first-parent merge in `v3.0.2..41b7bf4` — #200, #201, #202, #203, #204, #205, #206 (`git log --first-parent --oneline v3.0.2..origin/main`; all merge commits), then #208, merged during stage A on the release manager's instruction — plus this release's own PR, #210, and the two record-only PRs merged after it, #216 (the eval waiver) and #218 (this row and the pre-tag dispositions). Nothing deferred |
| M0.03 | PASS | Choose the version number and record why: major for a breaking change (API contract, bundle format a… — Patch — reasoning under Scope: four fixes and release bookkeeping; no route added or reshaped, no migration, model or bundle-format change (A19.02) |
| M0.04 | PASS | Carry forward known limitations: start this release's `known` from the previous release's, and remove an… — `known` starts from 3.0.2's 22 items. Three removed with their fixes as evidence: the sign-in limit (#200, `test_login_rate_limit.py`), the Appearance hydration error (#201, `AppearanceSection.test.tsx`), desktop keyless research (#202, `test_desktop_local_models_without_a_key.py`). Two reworded to stay true: doubled evidence now says "before 3.0.2", and the citation-support item names 3.0.2's run, since nothing it measured changed. The other 17 carried unchanged. Two added with the privacy-copy correction: corpus-only mode does not keep model calls local, and desktop projects share one corpus. 21 in all. Details under Known issues |
| **Phase 1 — Repository / Version Consistency** | | |
| M1.01 | PASS | Bump and derive, in this order: `VERSION`; the new `releases.ts` entry at the top with `unreleased: true`… — `VERSION` 3.0.3; the 3.0.3 entry at the top of `releases.ts` with `unreleased: true`, written before `sync_version.py`; `sync_version.py` reported drift in `main.py`, `tauri.conf.json` and `Cargo.toml`; `--write` → "consistent across 4 files"; `cargo update -p research-desktop` → Cargo.lock 3.0.3; changelog `## v3.0.3 — unreleased` with **Known**. `--stage ci`: 24/24 PASS |
| M1.02 | PASS | Search for stale references the scanner cannot see: images and screenshots with text in them, the… — `git grep` for 3.0.2/v3.0.2, `releases/download/`, `ghcr.io/…:<tag>`: every hit is incident history (RELEASE.md's table, AGENTS.md, comments in `stamp_image.py`, `start.sh` and `release_checks`), a test fixture, an npm package that happens to be at 3.0.2, or a URL template built from `releases.ts`; no `ghcr.io` tag is pinned anywhere; the OpenGraph image names no version |
| M1.03 | PASS | Review every line A1.09 flags, one by one — A1.09 PASS — it flags no line: this release adds no version mention to user-facing text. The new mentions are in `releases.ts` and the changelog (version histories by design), and this record |
| **Phase 2 — Feature Completeness** | | |
| M2.01 | PASS | Fill the feature matrix in the record for every scope row: Implementation · Tests · UI · API · Desktop ·… — Matrix under Scope. Every fix row is Shipped on source evidence; #202's packaged-desktop column and #201's published-image check are confirmed at stage B (Extra checks) |
| M2.02 | PASS | For every feature on both hosts, confirm the desktop really has it: the route exists and behaves… — #202 on the packaged app (M7.08): a run with no key readable starts, Settings → Models offers the Ollama models, and Save URL saves the Custom Endpoint base URL. Two desktop gaps found alongside it are Findings 13 and 14. #200 is server-only by design; #201 and #205 are the same frontend on every host (X2, M5.01) |
| M2.03 | PASS | Read the `releases.ts` entry and the changelog entry against the matrix: `improved` states user-visible… — Read against the matrix: `improved` states user-visible effects only, one item per fix (four for #202's four defects, two for the privacy-copy correction); `known` is 3.0.2's minus the three fixed, two reworded to stay true, plus the two limitations the corrected copy now states; each summary compresses its list and adds nothing (A1.05 PASS; `releases.test.ts` bounds) |
| M2.04 | PASS | If A2.03 fails: run the release evaluation (`docs/developers/08-testing-and-evaluation.md`, "The release… — Waived, with the evidence in "Evaluation" above: the only quality-path changes are a comment in `retrievers.py` and the module docstring of `tools.py`; no text a model reads changed. #202 changes which runs the desktop refuses up front and the run form's default Local LLM, not what a run does with a model |
| **Phase 3 — Automated Testing** | | |
| M3.01 | PASS | Explain every re-run: any required job on the release commit that passed only on a retry is recorded with… — Release commit 0c72d37: CI 40280268307, Desktop 40280268289 and CodeQL 40280267377 succeeded on attempt 1; the tag's Release 40281625011 and Desktop 40281625023 on attempt 1 |
| M3.02 | PASS | Read the non-blocking dependency-audit output of the release commit's CI run — Release commit's CI (40280268307): pip-audit — No known vulnerabilities found; npm audit — 3 (1 high `zod` < 4.6.6 under the React-hooks lint plugin, 2 moderate `@vitest/mocker`), all in the test or lint toolchain and none in the standalone server bundle (Stage A results). `@vitest/mocker` is fixed on `main` since by #209 |
| **Phase 4 — Backend / API Verification** | | |
| M4.01 | PASS | If `backend/app/api/` changed since the previous release, `docs/reference/34-api.md` and `35-sse.md`… — `backend/app/api` changed in `auth.py` only (#200): the account counter is read with `peek` and raised on a failure; no shape change, and docs/34 and docs/06 §4 already said "5 failures / 15 min" — they were right and the code was wrong. The sidecar's two custom-endpoint routes moved above `/desktop/keys/{provider}` with the same paths and bodies (#202). Contract hash: re-read on the stage B stack |
| M4.02 | PASS | On the published images (Phase 10 stack), probe the boundaries: an unauthenticated `GET /api/v1/projects`… — Published 3.0.3 images (M10.01): unauthenticated GET /api/v1/projects 401; a wrong password and an unknown address both 401 with the identical body `{"detail":"Invalid email or password."}` (no enumeration); /health `{"status":"ok","version":"3.0.3"}`; /health/ready 200; /api/v1/version git_sha 0c72d371a64500ef5672c83dff543df3c4f386b4, dirty false. **X3 PASS:** six correct sign-ins to one account all 200; five wrong passwords then 401 each; the right password after them 429 "Too many attempts" |
| **Phase 5 — Frontend Verification** | | |
| M5.01 | PASS | On the Phase 10 stack, open dashboard, a project, a finished run (report, evidence, citations), Settings… — Published 3.0.3 images, in the browser pane: Overview (/project) with the project's runs; a finished run (demo banner, report, claims, evidence, sources, verified artifact); Settings → About shows 3.0.3 and 0c72d371a. **X2 PASS:** full loads of Settings → Appearance with light and with dark saved log no React error 418 — the session's only console errors are the sign-in page's two pre-login 401s (`/auth/me`, `/auth/refresh`). X5 (app half, web): the published frontend's chunks carry the corrected *My corpus* scope copy and none of the old |
| M5.02 | PASS | Keyboard-only pass over the two gates: plan approval and report approval are reachable and operable… — Keyboard only, on the published 3.0.3 web images (3.0.2 did this on the desktop app; it is the same frontend). Plan gate: Shift+Tab from the end reached *Approve plan* with a 2 px solid focus outline, Return approved it (PLAN APPROVED recorded). Report gate: Shift+Tab ×2 reached *Approve report*, 2 px outline, Space approved it; the run completed |
| **Phase 6 — Desktop Application Verification** | | |
| M6.01 | PASS | Record the artifact table in the record for all four installers: file name · SHA-256 · OS · architecture ·… — Artifact table above; every blank carries its NOT RUN reason |
| M6.02 | NOT RUN | On every platform, run the packaged-engine checker against the **installed** copy of the **published**… — macOS PASS (M7.06), after the release Mac was restarted (Finding 10). Windows and Linux: no machine here; CI installed the .msi, .deb and AppImage and drove each engine through a journey on the tag (A6.02), and since #234 CI drives the DMG's engine too |
| M6.03 | PASS | Mark every desktop row in the record as *packaged* or *source* — Every desktop row says packaged or source; the engine evidence above is packaged (the published DMG; CI's installed engines) |
| **Phase 7 — macOS Verification** | | |
| M7.01 | NOT RUN | Download the `.dmg` from the release in a browser (so it carries the quarantine flag) and verify it — Not downloaded through a browser: the DMG was fetched with `gh release download`, which sets no quarantine flag. Its SHA-256 matches SHA256SUMS (`shasum -a 256 -c`, re-run 2026-10-26) |
| M7.02 | PASS | The DMG opens and holds the app at the right version — `hdiutil attach -nobrowse -readonly`: the app and an Applications link; CFBundleShortVersionString 3.0.3; the app is 152 MB |
| M7.03 | PASS | The signature is whole and valid — `codesign --verify --deep --strict` passes; the signature is ad-hoc, as intended (no Developer ID) |
| M7.04 | PASS | Gatekeeper judges a quarantined copy as policy, not damage — The published app copied to /Applications and given the quarantine flag a browser download sets (`0081;…;Safari;`, by hand — M7.01): `spctl --assess` answers *rejected*. Opening it without the command: XProtect found nothing (`XProtectMalwareType = 0`), Gatekeeper rejected it for "lack of matching active rule" and showed the code-evaluation prompt (`Prompt shown (6, 0)`, `present code-evaluation prompt`), not the damaged one, and no app or engine process ran (2026-10-27, after the restart) |
| M7.05 | PASS | The bundled engine is present, native, and unmodified by hardened runtime — `Contents/Resources/sidecar/research-sidecar` is present, `Mach-O 64-bit executable arm64`, ad-hoc signed with flags 0x2 (no hardened runtime); the engine tree is 143.5 MB |
| M7.06 | PASS | The packaged engine identifies itself and completes the journey — `check_packaged_sidecar.py --search <mounted DMG> --expect-sha 0c72d37… --expect-version 3.0.3 --journey --require-verify` on 2026-10-27, after the release Mac was restarted: launch, token gate and identity PASS (3.0.3, `0c72d371a64500ef5672c83dff543df3c4f386b4`, not dirty), journey PASS (plan_approved → approved, 4 evidence, bundle v2), `verify_bundle` PASS; tree 143.5 MB |
| M7.07 | ACCEPTED | First launch as a user: drag to Applications; open it *without* the command and confirm the block is the… — After `xattr -dr com.apple.quarantine`, the app opened (launched with a throwaway HOME so the release manager's data was untouched): the window, no "damaged" dialog at any point, and Settings → About shows VERSION 3.0.3 and COMMIT 0c72d371a. **No demo banner or onboarding appeared:** the first-launch demo run failed with "no evidence was gathered" — the known issue 3.0.3 shipped with (`releases.ts` known: "On a fresh desktop install, the demo report the app prepares on first launch fails"), accepted at the release |
| M7.08 | PASS | The Phase 20 desktop journey on macOS (M20.02) — **The Phase 20 journey on a real provider, PASS** — at the release manager's instruction ("use omniroute, not local llms"): Settings → Connections saved `http://localhost:20128/v1` as the Custom Endpoint base URL ("Custom endpoint saved.", `custom_endpoint.json` written), Settings → Models set `auto/best-fast` ("Research will run on this endpoint."), and every role ran on `custom:auto/best-fast`: plan gate (3 areas) approved → executor 3/3 → critic → synthesizer → report gate approved. 33 claims (14 supported), 13 evidence, 3 sources, 1 contradiction; the review page warned "19 claims resolved to no evidence" before approval; "All 3 citation markers in this text resolve to a cited source". The exported bundle is v2, `demo: false`, models as dialled, and 3.0.3's standalone `verify_bundle` passes all seven checks, approval chain included. **X1 (Ollama, no key) — partly:** run on the published app in a throwaway home with `PYTHON_KEYRING_BACKEND=keyring.backends.null.Keyring`, so no key was readable (the login keychain holds a `custom` key, left untouched). Fixed and seen fixed: the run **starts** with no key (3.0.2 refused it at once); Settings → Models lists the Ollama models, Connected; the run form's Local LLM default (`ollama:deepseek-r1:14b`) is one Settings marks RESEARCH READY, not chat only; Save URL saves (above). **Not completed:** on that default the planner made 6 tasks and the plan was approved, but the executor returned 0 sources on every task, the critic passed three empty tasks, and the run FAILED at "time limit reached: 722s of 600s" (Finding 13). Not retried on another local model, at the release manager's instruction |
| M7.09 | PASS | Quit the app; no engine is left running — Quit Research Assistant (app menu): `pgrep -fl 'research-desktop|research-sidecar'` finds nothing — checked after each of the two GUI sessions |
| **Phase 8 — Windows Verification** | | |
| M8.01 | NOT RUN | Download the `.msi` in a browser; verify it — No Windows machine (as in 3.0.2) |
| M8.02 | NOT RUN | SmartScreen shows the unknown-publisher warning; **More info → Run anyway** proceeds, exactly as the… — No Windows machine |
| M8.03 | NOT RUN | Install completes; Start-menu entry exists; Settings → Apps shows version `X.Y.Z`; files under `C:\Program… — No Windows machine; CI installed the `.msi` on the tag (A6.02) |
| M8.04 | NOT RUN | Launch: the window opens without a crash; Task Manager shows `research-sidecar.exe`; no firewall prompt… — No Windows machine |
| M8.05 | NOT RUN | `python scripts\check_packaged_sidecar.py --search "C:\Program Files\Research Assistant" --expect-sha <tag… — No Windows machine; CI drove the installed `.msi`'s engine through a journey on the tag: 3.0.3 at 0c72d37, `verify_bundle` PASS (A6.02) |
| M8.06 | NOT RUN | The Phase 20 desktop journey on Windows (M20.02), from a user whose profile path has a space; exports save… — No Windows machine |
| M8.07 | NOT RUN | Local storage: data under `%USERPROFILE%\.research-engine`; provider keys in Windows Credential Manager,… — No Windows machine |
| M8.08 | NOT RUN | Quit: `research-sidecar.exe` exits (the watchdog — No Windows machine |
| M8.09 | NOT RUN | Uninstall from Settings → Apps: the Program Files directory is removed; user data remains (as documented) — No Windows machine |
| **Phase 9 — Linux Verification** | | |
| M9.01 | NOT RUN | AppImage: download, verify (`sha256sum -c SHA256SUMS --ignore-missing`), `chmod +x`, launch from a desktop… — No Linux machine; CI drove the AppImage's engine through a journey on the tag: 3.0.3 at 0c72d37, `verify_bundle` PASS (A6.02) |
| M9.02 | NOT RUN | `.deb`: `sudo apt install ./Research.Assistant_X.Y.Z_amd64.deb` on a clean supported Ubuntu LTS resolves… — No Linux machine; CI installed the `.deb` and drove its engine through a journey on the tag (A6.02) |
| M9.03 | NOT RUN | Key storage uses the Secret Service keyring; on a session without one, the app says so rather than storing… — No Linux machine |
| M9.04 | NOT RUN | `sudo apt remove research-assistant` removes the application; user data remains; no engine left running — No Linux machine |
| **Phase 10 — Docker / Container Verification** | | |
| M10.01 | PASS | Run the published images on the full-stack topology, on their own volumes: — Published 3.0.3 images via `release-audit/compose.published-images.yml` (project `release-check`, port 3041, `LLM_MODE=fake`): five services healthy; an empty database migrated to head (29 steps); /api/v1/version through the frontend proxy reports 3.0.3 at 0c72d37, dirty false |
| M10.02 | PASS | On that stack: register, log in, create a project, run a fake-mode research through both gates, export… — Register, log in, project, fake-mode run through both gates, export.md 200 (demo-stamped), export.pdf 200 (`%PDF`, 16.5 KB), bundle.json 200 — v2, `demo: true`, 3.0.3's `verify_bundle` PASS on all seven checks |
| M10.03 | PASS | On an arm64 host (Apple Silicon Docker or the Ampere target), the same stack starts from the same tags — This host is arm64 (Apple Silicon Docker), so every stack above ran the arm64 images. amd64: both architectures are published from 0c72d37 (A10.01, A10.03); no amd64 host for a stack |
| M10.04 | PASS | Tear down with `down -v` using the same flags; the developer's own `mara_full_*` volumes are untouched — `down -v` with the same flags removed only `release_check_*`; the owner's running stack and its `mara_full_*` volumes were untouched |
| **Phase 11 — GitHub Release Verification** | | |
| M11.01 | PASS | Add the hand-written summary at the top of the Release body (what changed for users, the macOS… — Summary added above the generated notes on 2026-10-26 and the whole body read as a user would: what changed (four fixes and the privacy copy, with PR numbers), the macOS first-launch command, and the three known issues most likely to matter with a link to the changelog's **Known**; the image list and generated PR list are kept below it |
| **Phase 12 — Documentation Verification** | | |
| M12.01 | PASS | For each scope row, the docs describe what shipped — on both hosts, with desktop differences stated… — #200: docs/06 §4, docs/34 and docs/36 already state "5 failures per 15 min per account", which is now true. #202: docs/23 and docs/22 already describe Ollama as a keyless path on the desktop, which is now true; nothing documented the bug. #201, #205: no doc describes them. Privacy copy: every doc that described corpus-only mode now states what it enforces (Scope table), and docs/28 states the desktop's shared corpus. Desktop differences: #202 is the desktop catching up with the server; the desktop's one corpus is now stated wherever per-project scope was claimed in copy this release touched (not on the corpus page — Finding 8). Unrelated, pre-existing: Finding 3 |
| M12.02 | N/A | Configuration: every environment variable added, renamed or removed since the previous release (`git diff… — No environment variable added, renamed or removed: `git diff v3.0.2 HEAD -- backend/app/config.py .env.example` is empty, and `research_engine/local.py`'s diff adds two functions and reads no new variable |
| M12.03 | PASS | Search the docs for removed or renamed features, commands and routes named in the diff (`git diff --stat… — Nothing removed or renamed; the custom-endpoint routes keep their paths (#202). `git grep` for the 3.0.2 workaround ("Custom Endpoint key", "No provider key found") finds it only in the 3.0.2 notes, where it belongs. For the privacy copy: `git grep -i` over `docs/`, `frontend/`, `backend/app`, `backend/research_engine` and the README for "network call", "zero network", "airgap", "air-gap", "nothing leaves", "never leaves" and "offline": every absolute corpus claim rewritten; what remains is the bundle verifier being offline (true), the guard's name ("airgap guard"), history comments saying the old claim was false, and honest negations |
| M12.04 | N/A | Architecture docs (`docs/architecture/02`, `04`) match the graph's nodes and gates — Graph nodes and gates unchanged — no change to `graph.py` since v3.0.2 |
| M12.05 | PASS | Known limitations agree across `releases.ts` `known`, the changelog **Known**, the Release body and the… — `releases.ts` known (21 items), the changelog's **Known** and the Release body's summary (three named, the changelog linked) agree |
| **Phase 13 — README Verification** | | |
| M13.01 | PASS | Read the README top to bottom against the release: the feature list (nothing unreleased, nothing removed),… — README unchanged since v3.0.2 (`git diff --stat v3.0.2 HEAD -- README.md` is empty). Its features, platforms and commands are unaffected by four fixes; the measured claim is A1.14 (PASS) |
| **Phase 14 — Landing Page Verification** | | |
| M14.01 | PASS | View `/` at desktop width and at 375 px, light and dark: hero, download call-to-action, "New in" link to… — Live `/` after the flip, at desktop width (light, and dark through the site's toggle) and at 375 px: the hero; *Get the desktop app →* to `/download/`; "NEW IN V3.0.3 … What changed →" to `/releases/#v3.0.3`; the feature cards, with the corrected corpus card (X5). No horizontal scroll at 375 px (`scrollWidth` 375) |
| M14.02 | PASS | `/why`: every comparison claim (`frontend/lib/comparison.ts`) still holds for this release — **X5 PASS:** `/why`'s corpus row reads "evidence from your uploads only, web search off, local indexing model required. The question and excerpts still go to the provider each research model uses", and its detail says the manuscript stays local only when all four research models are local; every remaining "offline"/"no network" claim on the page is about the bundle verifier, which is true. The other claims are unchanged by this release. Still dated rather than wrong: the unattributed 96.4% (Finding 6) |
| **Phase 15 — Download Page Verification** | | |
| M15.01 | PASS | On each OS (or with a UA override), the detected-OS card leads; the big button and every card button point… — Live `/download/` on a Mac: the macOS card leads with *Download for macOS — Apple Silicon*; it and all four card links point at the v3.0.3 assets; the size note "~80 MB download, ~150 MB installed" is within 15% of the 80.2 MB DMG and the 152 MB app. No UA override for Windows or Linux; A15.01-A15.03 PASS on the file names |
| M15.02 | NOT RUN | Download one installer by clicking the page's button in a real browser; the file name and checksum are right — Not clicked through in a browser: a browser download needs the release manager's own go-ahead. The post-release audit's `--download` fetched and hashed every installer at the URLs the buttons use (A11.06), and the DMG's SHA-256 matched `SHA256SUMS` here (M7.01) |
| **Phase 16 — Releases Page Verification** | | |
| M16.01 | PASS | View `/releases`: the new entry is first with the tag's date; its summaries are shown and the lists fold… — Live `/releases/`: v3.0.3 first, marked LATEST, dated 2026-10-26, headline and both summaries shown; *All 9 improvements* and *All 21 known gaps* fold; all eleven releases in the index. No "unreleased" text on the page |
| **Phase 17 — GitHub Pages / Deployment Verification** | | |
| M17.01 | PASS | If A17.01 fails because `main` moved after the flip, wait for the newer deploy and re-run; if the deploy… — A17.01 first FAILED: `main` moved after the flip to `399c122` (#234), which changes nothing the site is built from (`git diff 1c72e9b 399c122 -- frontend docs .github/workflows/pages.yml` is empty), so no deploy followed. Pages dispatched on `399c122` (run 40370850385) published the identical site; the re-run passed |
| **Phase 18 — Security / Configuration Verification** | | |
| M18.01 | PASS | Review `git diff vPREV..HEAD` for debug flags, test accounts, credentials, private URLs, and anything that… — Added lines since v3.0.2 searched for prints, debuggers, credentials, test accounts and private URLs: every hit is a comment or a test fixture (`http://test`, a loopback Ollama URL, a test token); no credential, no debug flag |
| M18.02 | PASS | If `backend/app/config.py`, the security middleware, auth, or the SSRF guard changed: re-check CORS… — Auth changed (#200), so re-checked on the diff: the login limits are unchanged (`LOGIN_IP` 20/60 s counts every attempt; `LOGIN_EMAIL` 5/900 s now counts failures only, as docs/06 §4 states); an unknown address raises the account counter exactly as a wrong password does, so the lock cannot enumerate accounts; five failures still lock the right password out. CORS, CSP, cookies, JWT lifetimes, refresh rotation, `ENCRYPTION_KEY`, `/docs` and the SSRF guard are untouched (no diff in `config.py`, `security`, the middleware or `ssrf`). Re-probed on the published images at M4.02 |
| M18.03 | PASS | No secret or env file ships in an artifact — App inside the published DMG and its engine binary: no env file, no key-shaped string. Published api and worker images: no env file anywhere on the filesystem, no key-shaped string under /app outside tests |
| M18.04 | PASS | Public surface: `/api/v1/version` is unauthenticated on the server by design; nothing else new is — No route added on either host since v3.0.2: `auth.py` changed only inside `login`, and the sidecar's custom-endpoint routes were moved, not added |
| **Phase 19 — Upgrade / Migration Verification** | | |
| M19.01 | PASS | Fresh install: an empty database migrates to head (CI), and a fresh desktop data directory starts (M6.02… — A fresh Postgres migrated to head on the published images (M10.01). A fresh desktop data directory: CI's packaged engines started on fresh directories on all three OSes (A6.02, M6.02); not on this Mac (M7.06) |
| M19.02 | N/A | Server upgrade from the previous release: run the previous release's images (`RELEASE_TAG=PREV` with the… — A19.02 has nothing to declare: no migration, ORM model or bundle-format change since v3.0.2, and the same Python (3.14) as 3.0.2 |
| M19.03 | N/A | Desktop upgrade from the previous release: install the previous release, create the same data, install… — As M19.02 — the desktop data directory's schema is unchanged. The update path a 3.0.2 desktop user takes is still exercised at M22.04 |
| M19.04 | N/A | Downgrade: CI's round-trip proves the schema reverses; record whether running the previous images against… — No migration in this release, so a 3.0.2 image against a 3.0.3 database is the same schema |
| M19.05 | PASS | A bundle exported by the previous release verifies with this release's verifier, unchanged (`python -m… — `verify_bundle.py` and `bundle.py` are unchanged between v3.0.2 and v3.0.3 (`git diff v3.0.2 v3.0.3` is empty for both), so 3.0.3's verifier is the one that verified 3.0.2's own bundles. 3.0.3's verifier also passes the committed v1 and v2 fixtures and both v2.1.0 upgrade bundles |
| **Phase 20 — Final End-to-End Production Smoke Test** | | |
| M20.01 | NOT RUN | The web/self-hosted journey on the Phase 10 stack, **with a real provider at least once** (fake mode… — Only fake mode was run (M10.02). No real-provider run: nothing in the pipeline, prompts, tools or routing changed since v3.0.2 ("Evaluation" above), where M20.01 passed with a real provider |
| M20.02 | NOT RUN | The desktop journey on each platform (M7.08, M8.06, M9.01/M9.02), with a real provider or Ollama — macOS PASS (M7.08, on OmniRoute; the Ollama half of X1 did not complete — Finding 13). Windows and Linux: no machine; CI drove the installed engines (A6.02) |
| M20.03 | NOT RUN | Negative paths on the published build: an invalid provider key is reported as rejected by its provider as… — Partly, on the published server images: a run cancelled straight after start was still `CANCELLED` 60 s later; one byte flipped in an exported bundle's report fails `verify_bundle` (`bundle_integrity` and `report_integrity`, exit 1). Not run: the invalid-key report, a rework resuming at the synthesizer, a browser refresh mid-run, a worker restart at a gate |
| M20.04 | PASS | Every `[n]` in the final report resolves on hover to a source and its snippet; an unresolved one renders… — Published web images: the report says "All 2 citation markers in this text resolve to a cited source"; hovering `[1]` shows the source's title, the quoted snippet and *Open source ↗*. No unresolved `[n]` occurred, so the ⚠ chip was not seen live; `test_citation_verification.py` pins it. At 800 px the hover card is clipped by the viewport's right edge (cosmetic) |
| **Phase 21 — Release Approval** | | |
| M21.01 | PASS | Every WARN and UNAVAILABLE in the published audit has a written disposition in the record — Dispositions above for every WARN and UNAVAILABLE in `pre-tag.json` and `published.json` |
| M21.02 | PASS | Known issues are documented everywhere they belong (M12.05), including anything this audit found and the… — Known issues section below; this audit found no new defect in the release, and the one environmental failure (M7.06) is this Mac's, recorded in Findings |
| M21.03 | PASS | The release manager signs the approval block in the record — Signed below by Claude Code on the release manager's instruction of 2026-10-26 ("I rebooted and the 3.0.3 app launched fine. Go ahead with the Stage C flip PR for 3.0.3."). What they should review: the macOS rows left NOT RUN, above all M7.08 — the headline fix not yet seen in the published app |
| **Phase 22 — Post-Release Verification** | | |
| M22.01 | PASS | The flip PR: drop `unreleased`, set the entry's `date` to the tag's date, date the changelog heading,… — #233 merged as merge commit `1c72e9b` (2026-10-26): `unreleased` dropped, dated 2026-10-26, the changelog heading dated, the stage B record and audits committed. Pages run 40362741857 deployed it at 16:50Z, and the live download page offers 3.0.3 |
| M22.02 | PASS | After Pages deploys: run the post-release audit with `--download --docker`, commit its JSON (write-once)… — Post-release audit with `--download --docker` on `399c122` (the flip, plus #234) after these rows were filled, saved as `post-release.json` |
| M22.03 | NOT RUN | Load `/`, `/why`, `/docs`, `/download`, `/releases` on a phone and a desktop browser with the cache disabled — Not on a phone. In the browser pane at desktop width and at 375 px emulation, `/`, `/why`, `/docs`, `/download` and `/releases` load with their content and log no console error. **X4 PASS:** none of the five requested anything under `/api/v1/` (3.0.2's M22.03 saw a 404 on each) |
| M22.04 | PASS | In an installed copy of the **previous** desktop release, Settings → About → *Check for updates* reports… — The published 3.0.2 desktop engine (0a9de70, from its DMG) answers `/api/v1/updates/check` with `update_available`, running 3.0.2, latest 3.0.3, and the v3.0.3 release URL |
| M22.05 | NOT RUN | For 48 hours, watch issues and discussions for install or launch reports; any release-blocking report… — The window is open until 2026-10-28T16:50Z, 48 h after the site began offering 3.0.3. As of 2026-10-26T17:00Z: no issues or discussions opened since the tag |
| M22.06 | PASS | Every incident found during this release becomes a check: an `A…` check (preferred) or an `M…` item, plus… — Incidents table below: the template's stale M20.03 text and the corpus privacy overclaim, each fixed in the release PR, the second with a test; and the macOS packaged-journey gap found at stage B (Finding 11), which became a `desktop.yml` step that A6.02 requires on a tag and A6.03 keeps in place (#234) |

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
   scope, not in the standalone bundle. No Dependabot PR existed for it.

   **Resolved for #50** at the release manager's choice: an `overrides` entry scoped to
   `jsdom` pins `undici` to 8.12.2, inside jsdom's own `^8.10.2`, in this PR — the shape #199
   used for 3.0.2. One lock entry changes, still `dev: true`; checks under Stage A results.
   The moderate #45 and #46 (`@vitest/mocker`, fixed by #209) do not stop A18.05. `npm audit`
   still lists `zod` < 4.6.6 (high) under the React-hooks lint plugin, which Dependabot has
   not raised as an alert; lint-time only.
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

**Found at stage B (2026-10-26)**

10. **The packaged engine would not start on the release Mac, because the Mac was broken, not
    the build.** `syspolicyd` had been failing every request since before the tag (`Unable to
    initialize qtn_proc: 3`, `dispatch_mig_server returned 268435459`, 0% CPU, up since
    2026-10-23), and the kernel holds a binary it has not yet assessed until that daemon answers:
    the 3.0.3 engine sat at 32 KB resident with only `dyld` mapped, and was killed with
    `ASP: Security policy would not allow process` (exit -9 in the checker). The 3.0.2 engine,
    assessed before the wedge, started at once; a re-signed copy of 3.0.3 hung the same way. The
    release manager restarted a Mac and the 3.0.3 app launched. M6.02, M7.06-M7.09 and X1 are
    NOT RUN for this reason until the Mac was restarted on 2026-10-27; they were run then.
11. **No CI job runs the packaged journey on the macOS app's engine.** `desktop.yml`'s Linux and
    Windows `Shell` jobs run `check_packaged_sidecar.py --journey --require-verify` on the
    installed engine; the macOS `Shell` job only waits for the bundled copy's handshake and
    compares its git SHA, and the full journey runs on the frozen engine in `Sidecar`, before it
    is bundled. With M7.06 not runnable here, nothing drove the published macOS engine through
    the gates. **Fixed by #234** (merged as `399c122`): the macOS `Shell` job now mounts the DMG
    and runs the same checker with `--journey --require-verify`; on that PR's run it passed
    (`"journey": "PASS"`, `"verify_bundle": "PASS"`). The 3.0.3 tag predates it.
12. At 800 px wide, a citation's hover card on the run page is clipped by the viewport's right
    edge (M20.04). Cosmetic; not compared against 3.0.2.

**Found at the macOS checks (2026-10-27, after the restart)**

13. **On the desktop, the run form's default local model could not do the research, and the desktop
    stops every run at 10 minutes.** With no key and Ollama running, the form defaulted to
    `ollama:deepseek-r1:14b` (#202 picks a model large enough to cite; Ollama reports it as
    tool-capable). Its executor returned 0 sources on all 6 tasks (about 50 s each), the critic
    still passed three of them ("two independent sources"), and the run FAILED at "time limit
    reached: 722s of 600s". The cap is `sidecar_run_config`'s `MAX_WALLCLOCK_SECONDS` default
    of **600**, while the server and `local.py` default to 0 — AGENTS.md: every run limit is
    `0 = unlimited` — and `local.py`'s own comment records that 600 s timed out three of ten
    Ollama runs. The cap has been 600 since 3.0.0; what is new is the default model. 3.0.2's
    journey completed on `qwen2.5:7b`. Not fixed; not yet in the known issues.
14. **The desktop's Custom Endpoint status ignores the saved base URL.** After Save URL wrote
    `custom_endpoint.json`, Settings → Models still showed the endpoint *stopped* / "No endpoint
    configured", and the run form warned "Custom Endpoint is not reachable right now. Starting
    a run on it will fail" — yet the run on it planned in 10 s and completed. The sidecar's
    `/models/custom/status` calls the shared handler, whose probe reads the server's
    `custom_base_url` setting, never the desktop's file (`sidecar.py` passes the stored URL only
    on the key-test route). Desktop only; not fixed.

Finding 10 is closed: after the release Mac was restarted (2026-10-27 05:09), the published
engine started in 3 s and every macOS row was run.

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
| No CI job drove the bundled macOS engine through the gates, and the release Mac could not launch the published one (Finding 11) | `desktop.yml` step *The engine inside the published disk image completes a journey*, in A6.02's required steps and A6.03's guards, with the checker-call count in `test_packaged_checker_requires_verify.py` (#234) |
| The record template's M20.03 row kept the wording RELEASE.md had dropped (Finding 4) | Fixed in this PR. No new check: `test_the_record_template_starts_with_a_row_for_every_manual_check` compares IDs, and the row text is a copy for the reader |

## Release approval

```text
Version:            v3.0.3
Commit:             0c72d371a64500ef5672c83dff543df3c4f386b4
Tag:                v3.0.3 (annotated)
Release manager:    Aditya Mhaske

Automated checks    [x] pre-tag PASS   [x] published PASS   [x] post-release PASS
Desktop             [ ] macOS PASS     [ ] Windows PASS     [ ] Linux PASS
Web                 [x] Landing PASS   [x] Download PASS    [x] Releases PASS   [x] Docs PASS
Distribution        [x] GitHub Release PASS   [x] Docker PASS   [x] Checksums PASS
Security            [x] PASS
Upgrade/migration   [x] PASS
Critical journey    [ ] web PASS   [ ] desktop PASS
Known issues        [x] documented everywhere they belong
```

Not ticked, and why: macOS has M7.01 NOT RUN (no browser download) and M7.07 ACCEPTED, and X1's
Ollama journey did not complete (Finding 13); there is no Windows or Linux machine. The web journey
ran in fake mode only (M20.01); the desktop journey ran on a real provider (M7.08).

- [x] **Release approved** — by Claude Code on the release manager's instruction of 2026-10-26, after
  they restarted a Mac and launched the published 3.0.3 app: "Go ahead with the Stage C flip PR for
  3.0.3." Review M7.08: the headline fix (#202) has not been seen working in the published app.
