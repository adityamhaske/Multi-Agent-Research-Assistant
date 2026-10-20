# Release record — v3.0.2

Copied from `release-audit/TEMPLATE.md` at the start of the release (RELEASE.md, M0.01).
Everything a person decided, checked or accepted for this release is written here; everything
a machine checked is in the audit JSON beside it. Nothing is marked PASS without evidence a
reader can re-check.

Stage A (prepare) was run on 2026-10-18 from an Apple Silicon Mac, on the release branch
`release/v3.0.2` cut from `origin/main` at `a887720`. Every row below that needs the merged
release commit, the tag or the published artifacts is `PENDING`.

| | |
|---|---|
| Version | v3.0.2 |
| Previous release | v3.0.1 (`d53d645`) |
| Release manager | Aditya Mhaske (stage A prepared with Claude Code; the sign-off is the release manager's) |
| Release commit (tag target) | PENDING — the merge of the release PR into `main` |
| Tag | v3.0.2 (annotated) |
| Tag date | PENDING |
| Audit evidence | `pre-tag.json`, `published.json`, `post-release.json` in this directory |

Result values: `PASS` · `FAIL` · `N/A` (why it does not apply) · `NOT RUN` (why not) ·
`ACCEPTED` (a known failure the sign-off accepts, with the reason) · `PENDING`.

---

## Scope

Every PR merged since the previous release, in or out (A2.01 fails on a `#N` missing here).
Version rationale (M0.03): **patch**. Every scope row is a fix, a test, a dependency update or
a release-process change. Two rows add something, and neither is a new capability: #179 offers
in the agent editor the reset the agent's card already offered (the same `prompt_overrides`
call, no new route), and #181's `cited_indices` is an additive response field that the fix
for wrong cited counts needed, which no existing client breaks on. No migration, ORM model or
bundle-format change (A19.02).

| Feature / fix | PRs | Implementation | Tests | UI | API | Desktop | Docs | Website | Release notes | Known limitations | Status |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Custom, OpenRouter and Ollama setups research for real (`start.sh` stopped forcing demo mode) | #171, #177 | `start.sh` mirrors `_validate_secrets` | `test_start_sh_mode.py` (8 of 10 cases fail on the old script) | — | — | n/a — the desktop does not use `start.sh` | ✓ 20-quick-start | — | ✓ | — | Shipped |
| Plan approval no longer fails the run (one event loop per worker process; failures not masked) | #171, #177 | `app/workers/event_loop.py`, `research_engine/concurrency.py` | `test_worker_event_loop.py`, `test_node_failure_is_not_masked.py`, `test_worker_task_lifecycle.py` | — | — | `gather_or_cancel` is shared; the loop fix is server-only (the desktop drives runs on its own loop) | ✓ backend/AGENTS.md | — | ✓ | — | Shipped |
| Provider SDKs and HTTP stack pinned | #171 | `backend/constraints.txt` | `test_dependency_constraints.py` | — | — | ✓ the sidecar build resolves the same set | ✓ backend/AGENTS.md | — | ✓ changelog | — | Shipped |
| A non-string `read_webpage` url is an observation | #171 | `graph.py` | `test_executor_tool_arguments.py` | — | — | ✓ same engine | — | — | ✓ | — | Shipped |
| Search-engine results pages refused; executor steered to `web_search` | #178 | `tools.py`, `prompts.py` | `test_search_pages_steer_to_web_search.py` (24 cases); golden parity re-recorded | — | — | ✓ same engine | ✓ docs/04 §4 | — | ✓ | — | Shipped — prompt change, evaluated (M2.04) |
| A rework stores no second copy of the evidence | #181 | `run_lifecycle.record_evidence`, `record_contradictions` | `test_rework_keeps_evidence_and_citations_honest.py` on server and desktop drivers; four lifecycle tests | ✓ | — | ✓ shared `persist_outcome` | — | — | ✓ | ✓ older runs keep their duplicates | Shipped |
| Cited counts and "backs N claims" describe the latest revision | #181 | `project_run` `cited_indices`; `primitives.tsx`, `SourcesPanel.tsx` | `RunWorkspace.test.tsx` rework scenario | ✓ | ✓ additive `cited_indices` | ✓ the sidecar serves the same projection | ✓ docs/19, docs/34 | — | ✓ | — | Shipped |
| An approval is not a 500 when project memory cannot take the report | #180 | `runs._ingest_report_into_memory` | `test_approval_survives_memory_ingest_failure.py` (Postgres) | ✓ | ✓ | n/a — project memory is pgvector-only, server-only by design | — | — | ✓ | — | Shipped |
| A demo run says first that nothing was researched | #177 | `DemoNotice.tsx` | `DemoNotice.test.tsx`, run page test | ✓ | — | ✓ same frontend | — | — | ✓ | — | Shipped |
| Reset an agent from inside its editor | #179 | `RolePromptEditor.tsx`, `AgentsSection.tsx` | 4 tests | ✓ | — (existing call) | ✓ same frontend | — | — | ✓ | — | Shipped |
| Server images stamped with the commit that built them | #170 | `release.yml` `stamp` job + image step | runs only on a tag: A10.05, A11.09 | ✓ Settings → About | ✓ `/api/v1/version` | n/a | ✓ AGENTS.md, RELEASE.md | — | ✓ | — | PENDING — first exercised by this tag (stage B) |
| Oracle deploy defaults to `latest`, not a pre-1.0 `edge` build | #170 | `deploy/oracle-bootstrap.sh` | A10.04 | — | — | n/a | ✓ deploy/README.md | — | ✓ | — | Shipped |
| Release process, audit, installed-installer CI steps, `/build.json` | #170 | `RELEASE.md`, `scripts/release_audit.py`, `desktop.yml`, `pages.yml` | `test_release_audit.py` | — | — | ✓ `.deb`/AppImage/`.msi` journeys in CI | ✓ RELEASE.md, release-audit/README.md, README | ✓ `/build.json` | ✓ changelog *Process* | — | Shipped (process) |
| Refresh-token rotation and reuse detection tested | #170 | test only | `test_refresh_token_reuse.py` | — | — | — | — | — | — | — | Shipped (test) |
| This release's preparation: version, notes, changelog, record, the release evaluation, and the A2.01/A2.03 audit fixes | #186 | `VERSION` and its carriers, `releases.ts`, the changelog, this record, `eval-2026-10-19-custom.json`, `release_checks/evaluate.py` | `test_release_audit.py` negative controls; release-entry tests | — | — | — | ✓ RELEASE.md incident rows | ✓ releases.ts (unreleased) | ✓ | — | Shipped (process) |
| Scope update: #187-#189 recorded, extra checks planned | #192 | this record, changelog, `releases.ts` | release-entry tests; `--stage ci` | — | — | — | — | ✓ releases.ts (unreleased) | ✓ | — | Shipped (process) |
| Python 3.14 is the stated floor everywhere — `requires-python`, ruff's target, the engine's import guard, the standalone verifier, the release audit — and A10.06 holds every floor to the image | #193 | `research_engine/__init__.py` guard, both `pyproject.toml`, 3.14 syntax (unquoted annotations, PEP 758 `except`), docs | `test_engine_python_floor.py`; A10.06 | — | — | ✓ same engine | ✓ docs/15, docs/20, docs/32, README, CONTRIBUTING | — | ✓ | ✓ the verifier needs 3.14 (Finding 8) | Shipped |
| A packaged-app check whose bundle verification did not run fails CI | #194 | `check_packaged_sidecar.py --require-verify`; `desktop.yml` installs the verifier's one dependency | `test_packaged_checker_requires_verify.py` | — | — | ✓ `.deb`/AppImage/`.msi` journeys | ✓ RELEASE.md, AGENTS.md | — | ✓ changelog *Process* | — | Shipped (process) |
| Next.js and `eslint-config-next` 16.4.2, Playwright 1.64.1 | #191 | `frontend/package*.json` | CI; lint, typecheck, 495 tests and all three builds — `build:pages` included, which CI does not run — on the PR's tree | — | — | ✓ same frontend | — | ✓ `build:pages` | ✓ changelog | — | Shipped |
| Frontend image on Node 26 (from 25) | #172 | `frontend/Dockerfile` | CI does not build the image: built and run locally from the PR's tree (Finding 9) | — | — | n/a | — | — | ✓ changelog | — | Shipped |
| The frontend image, CI, the desktop and Pages builds, and every stated floor on Node 26, enforced (A10.07) | #196 | `setup-node` 26 in ci.yml (`frontend`, `golden-e2e`), desktop `shell`, pages `build`; `engines >=26`; docs floors; `Runtime` shared by A10.06 and A10.07 | 10 A10.07 tests (planted drift, unreadable versions, a lost `setup-node`, the real stale floors, a real-repo negative control); A10.06 tests unchanged and passing; on main's prior tree A10.07 fails naming every drift | — | — | ✓ desktop `shell` builds the static export on 26 | ✓ CONTRIBUTING, frontend/README, docs/20, docs/32, RELEASE.md, AGENTS.md | ✓ `build:pages` on 26 | ✓ changelog | — | Shipped |
| `numpy>=2.5.4` | #190 | `backend/requirements.txt` | CI on 3.14 | — | — | ✓ the sidecar resolves the same set | — | — | ✓ changelog | — | Shipped |
| Record updates: #192-#196 scoped, E1-E3 results, Findings 8 and 9 | #195 | this record, changelog, `releases.ts` | `--stage ci`; release-entry tests | — | — | — | — | ✓ releases.ts (unreleased) | ✓ | — | Shipped (process) |
| Scoping the record PRs themselves, after the first pre-tag run failed A2.01 on #195 | #197 | this record | the pre-tag audit's A2.01 | — | — | — | — | — | — | — | Shipped (process) |
| A3.02 judges the site a release commit serves when the path filter gives it no Pages run (Finding 10) | #198 | `release_checks/workflows.py` `_pages_run_for`, `evaluate.push_paths` | 2 tests; the fixed check passes on `dedfbb0` via f51800f's Pages run | — | — | — | ✓ RELEASE.md | — | ✓ changelog | — | Shipped (process) |
| `postcss-selector-parser` 7.1.6 under `@tailwindcss/typography`, via `overrides` (alert #31, GHSA-rj75-hqrm-r3gf) | #199 | `frontend/package.json` `overrides`; one lock entry | compiled CSS byte-identical with and without it (web and Pages builds, Node 26); lint, typecheck, 495 tests, `build:desktop` | — | — | ✓ same frontend | — | ✓ same CSS | ✓ changelog | — | Shipped |
| v3.0.1 offered for download (the previous release's flip) | #169 | `releases.ts` | `download/unreleased.test.tsx` | ✓ | — | — | — | ✓ | — | — | Shipped (process) |
| Frontend dependency updates: Next.js 16.3.6, the frontend minor group, undici 8.11.2, brace-expansion 1.1.21 | #174, #175, #176, #182 | `frontend/package*.json` | CI on each PR | — | — | ✓ same frontend | — | — | ✓ changelog | — | Shipped |
| Security updates past three high-severity advisories: Next.js 16.3.8, sharp 0.35.5, source-map-js 1.2.2 | #185, #184, #183 | `frontend/package*.json` | CI on each PR; merged during stage A (Finding 1), then lint, typecheck, tests and all three builds re-run on the release branch | — | — | ✓ same frontend | — | — | ✓ | — | Shipped |
| Backend images on Python 3.14 (from 3.11) | #173 | `backend/Dockerfile` | Built and the full suite run inside the image (Finding 2) | — | — | see #189 | — | — | ✓ changelog | — | Shipped |
| CI, the release stamp job and the image on one Python, enforced (A10.06) | #187 | `ci.yml`, `release.yml` on 3.14; `release_checks` A10.06; Dependabot ignores backend-image Python minors | A10.06 negative controls in `test_release_audit.py` | — | — | — | ✓ RELEASE.md, AGENTS.md | — | ✓ changelog | — | Shipped |
| The desktop engine frozen on 3.14, so every workflow's Python is the image's | #189 | `desktop.yml` on 3.14; A10.06's desktop exception removed | Sidecar ×3 and Shell ×3 green on 3.14 (the frozen engine, `.deb`, AppImage, `.msi` journeys) | — | — | ✓ packaged — stage B checks below | ✓ RELEASE.md, AGENTS.md | — | ✓ | — | PENDING — packaged checks (Extra checks) |
| Every build reports its own identity or `unknown`, never a stale stamp's | #188 | `docker/stamp_image.py`, `BUILD_STAMP` in the Dockerfile and compose, `start.sh` exports the checkout's facts, `release.yml` keeps its own stamp, the sidecar spec refuses a stale one | `test_local_build_stamp.py`; real local builds | ✓ Settings → About | ✓ `/api/v1/version` | ✓ the spec refuses a stale stamp | ✓ docs/09, AGENTS.md, RELEASE.md | — | ✓ | — | PENDING — the `release.yml` path first runs on the tag (Extra checks) |

Deferred (merged but not part of this release's story): none.

### Evaluation (A2.03, M2.04)

Quality paths changed since v3.0.1: `graph.py` (#171), `prompts.py` and `tools.py` (#178 —
the executor prompt and both tools' descriptions, which the model reads). A waiver needs a
change that provably cannot alter output, and this one can, so the release was evaluated:

| | |
|---|---|
| Result | `backend/evals/results/eval-2026-10-19-custom.json` (new, write-once) |
| Command | `LLM_MODE=real MAX_PARALLEL_TASKS=1 MODEL_{PLANNER,EXECUTOR,CRITIC,SYNTHESIZER,CHAT}=custom:antigravity/gemini-2.5-flash python -m evals.harness --judge custom:kiro/claude-sonnet-4.5` — docs/developers/08 "The release run", without `--candidate` (the candidate measures a custom planner prompt, which nothing in this release touches) |
| Code measured | `backend/` at `a887720`; between it and this branch's head the only backend change is `APP_VERSION` |
| Environment | Python 3.11.15, a fresh venv from `requirements.txt` + `constraints.txt` (openai 3.21.0, langchain-openai 1.6.6); retrieval Tavily |
| Completion | 10 / 10 (threshold 0.90) |
| Citation support | **0.9693** over 190 judged claims, 0 unjudged (threshold 0.95) |
| Judge | `custom:kiro/claude-sonnet-4.5`, independent of all five pipeline routes; every ruling served by `claude-sonnet-4.5` via Kiro, strategy `single`, none without routing headers |
| Compared with | 3.0.0's release run, same routing and judge: 0.9638. One run each — not evidence of a change |

Operational, not quality: the run took 64 minutes from start to result file (00:42–01:46 UTC). About 30
minutes were spent waiting on OmniRoute between 00:47 and 01:17 UTC — three judge calls
arrived roughly ten minutes apart (the client's request timeout) and no pipeline call was
served — after which it recovered. Per-question latency in the result (44–79 s) excludes
judging, so the stall is not in it.

## Desktop artifacts (M6.01)

Packaged artifacts only — source-checkout evidence goes in its own row and never satisfies
a desktop check (M6.03).

| Artifact | SHA-256 | OS | Arch | Version (installed) | Engine git SHA | Install | Launch | Journey |
|---|---|---|---|---|---|---|---|---|
| `Research.Assistant_3.0.2_aarch64.dmg` | `827c6a04…d688cc01` ✓ | macOS | arm64 | 3.0.2 (Info.plist) | `0a9de70` (packaged) | mounted, not installed — NOT RUN | engine: PASS (packaged); GUI: NOT RUN | engine: PASS, verifier PASS (packaged) |
| `Research.Assistant_3.0.2_x64_en-US.msi` | `ac7288f7…e645e317` ✓ (GitHub digest, downloaded bytes) | Windows | x64 | NOT RUN — no machine | CI only: the installed engine on the tag (A6.02) | NOT RUN | NOT RUN | NOT RUN |
| `Research.Assistant_3.0.2_amd64.AppImage` | `2c7cff61…3ac12f20` ✓ (GitHub digest, downloaded bytes) | Linux | x86-64 | NOT RUN — no machine | CI only (A6.02) | n/a | NOT RUN | NOT RUN |
| `Research.Assistant_3.0.2_amd64.deb` | `26476b5d…e1a37247` ✓ (GitHub digest, downloaded bytes) | Linux | x86-64 | NOT RUN — no machine | CI only (A6.02) | NOT RUN | NOT RUN | NOT RUN |

Full hashes, and A11.06's downloaded-bytes check of all four, are in `published.json`.

## Container images

| Image | Digest (`X.Y.Z`) | amd64 | arm64 | Provenance revision | Runs (M10.x) |
|---|---|---|---|---|---|
| api | in `published.json` (A10.01) | ✓ | ✓ | `0a9de70` both (A10.03) | arm64: PASS — reports `0a9de70` (A10.05, M4.02) |
| worker | in `published.json` (A10.01) | ✓ | ✓ | `0a9de70` both (A10.03) | arm64: PASS; amd64 started under emulation (E1) |
| frontend | in `published.json` (A10.01) | ✓ | ✓ | `0a9de70` both (A10.03) | arm64: PASS (M5.01) |

## Automated audit

| Stage | Command | Verdict | Counts | Evidence |
|---|---|---|---|---|
| pre-tag | `release_audit.py --version 3.0.2` on `0a9de70` | PASS | 35 PASS, 1 WARN | `pre-tag.json` — the run the tag rests on. Earlier runs on `f51800f` (A2.01: #195 unscoped) and `dedfbb0` (A3.02: no Pages run, Finding 10) failed, each fixed by a PR, and were not committed |
| published | `… --published --download --docker` | PASS | 51 PASS, 3 WARN | `published.json` |
| post-release | `… --post-release --download --docker` | | | `post-release.json` |

Disposition of every WARN and UNAVAILABLE (M21.01):

| Check | Result | Disposition |
|---|---|---|
| A16.03 (published) | WARN | Historical: v1.0.0 and v1.0.2's site dates differ from their tags by a day, carried from the v3.0.1 record (its Finding 4); not this release |
| A21.01 (published) | WARN | Manual rows open at the published stage, as expected: the rows this Mac could settle are now recorded; the rest are listed under "What stage B could not settle here" |
| A19.02 (pre-tag) | WARN | #193 touched six ORM model files and `verify_bundle.py`. The model changes are annotation syntax only, with no schema change and no migration; the verifier's bundle format is unchanged (Finding 8). M19.02–M19.05 are required regardless, by the interpreter move, and are planned under Extra checks |

## Manual checks

One row per `M…` item in RELEASE.md (A21.01 fails on a missing row).

| ID | Result | Check — evidence |
|---|---|---|
| **Phase 0 — Release Scope Freeze** | | |
| M0.01 | PASS | Create the release record — Created 2026-10-18 from TEMPLATE.md on `release/v3.0.2`, before any version carrier changed |
| M0.02 | PASS | Freeze the scope: list every feature and fix in the record's Scope table, each with its PR numbers — Scope table above: every first-parent merge in `v3.0.1..a887720` — #169, #170, #171, #173-#182, merge commits and squash merges alike. Preparing it found A2.01 blind to squash merges (#179-#181); fixed in this PR (`merged_prs`) |
| M0.03 | PASS | Choose the version number and record why: major for a breaking change (API contract, bundle format a… — Patch — reasoning under Scope: fixes, tests, dependencies and process; #179 reuses an existing operation and `cited_indices` is an additive field the fix needed; no migration, model or bundle-format change (A19.02) |
| M0.04 | PASS | Carry forward known limitations: start this release's `known` from the previous release's, and remove an… — `known` starts from 3.0.1's sixteen items, all carried unchanged except the citation-support item, now worded as this release's own run; two added (pre-3.0.2 duplicated evidence; the spend limit on `openrouter`/`custom`). Nothing removed |
| **Phase 1 — Repository / Version Consistency** | | |
| M1.01 | PASS | Bump and derive, in this order: `VERSION`; the new `releases.ts` entry at the top with `unreleased: true`… — `VERSION` 3.0.2; entry at the top with `unreleased: true`; `sync_version.py --write` → "consistent across 4 files"; `cargo update -p research-desktop` → Cargo.lock 3.0.2; changelog `## v3.0.2 — unreleased` with **Known**. `--stage ci`: 22/22 PASS |
| M1.02 | PASS | Search for stale references the scanner cannot see: images and screenshots with text in them, the… — `git grep` for 3.0.1/v3.0.1, `releases/download/`, `ghcr.io/…:<tag>`: every hit is incident history (RELEASE.md, AGENTS.md, a release.yml comment), a test fixture, or a URL template built from `releases.ts`; the OpenGraph image names no version |
| M1.03 | PASS | Review every line A1.09 flags, one by one — A1.09 PASS — no new version mention in user-facing text; the new mentions are in `releases.ts` and the changelog (version histories by design), RELEASE.md and this record |
| **Phase 2 — Feature Completeness** | | |
| M2.01 | PASS | Fill the feature matrix in the record for every scope row: Implementation · Tests · UI · API · Desktop ·… — Matrix under Scope, #187-#189 included. Two rows are PENDING on stage B: #188's `release.yml` stamp path and #189's packaged engine (Extra checks); the image-stamping row likewise |
| M2.02 | PASS | For every feature on both hosts, confirm the desktop really has it: the route exists and behaves… — Packaged desktop: the published macOS engine's journey and the 3.0.1→3.0.2 desktop upgrade (M7.06, M19.03); published images: the web journey in fake and real mode (M10.02, M20.01). Server-only by design: project memory (#180) |
| M2.03 | PASS | Read the `releases.ts` entry and the changelog entry against the matrix: `improved` states user-visible… — Read against the matrix: `improved` is user-visible effects only and includes the measured result; `known` carries 3.0.1's list plus the two new gaps; each summary compresses its list and adds nothing (A1.05 PASS; `releases.test.ts` bounds) |
| M2.04 | PASS | If A2.03 fails: run the release evaluation (`docs/developers/08-testing-and-evaluation.md`, "The release… — A2.03 required it (graph.py, prompts.py, tools.py changed). Release run under an independent judge: completion 1.0, citation support 0.9693 over 190 judged claims — both above threshold. `eval-2026-10-19-custom.json`; details under Scope → Evaluation |
| **Phase 3 — Automated Testing** | | |
| M3.01 | PASS | Explain every re-run: any required job on the release commit that passed only on a retry is recorded with… — Release commit 0a9de70: CI 39302781732, Desktop and Pages all succeeded on attempt 1; the tag's Release 39304912886 and Desktop 39304912946 on attempt 1 |
| M3.02 | PASS | Read the non-blocking dependency-audit output of the release commit's CI run — Release commit's CI: pip-audit — No known vulnerabilities; npm audit — 5 high, 0 critical, all the dev-only braces → micromatch → fast-glob → eslint-config-next lint chain, none in the 12-package standalone server bundle (checked). Alert #31's two moderates were fixed by #199 |
| **Phase 4 — Backend / API Verification** | | |
| M4.01 | PASS | If `backend/app/api/` changed since the previous release, `docs/reference/34-api.md` and `35-sse.md`… — `backend/app/api` changed in `runs.py` only: #180 (no shape change) and #181's additive `cited_indices` on each revision, documented in docs/34; the sidecar serves the same projection. Contract hash re-checked on the stage B stack |
| M4.02 | PASS | On the published images (Phase 10 stack), probe the boundaries: an unauthenticated `GET /api/v1/projects`… — Published 3.0.2 images: unauthenticated GET /projects 401; wrong password and unknown user both 401 with the identical body (no enumeration); /health {"version":"3.0.2"}; /health/ready 200; /api/v1/version git_sha 0a9de70ee90485531120856fce7f5dde4041c0aa, dirty false (A10.05) |
| **Phase 5 — Frontend Verification** | | |
| M5.01 | ACCEPTED | On the Phase 10 stack, open dashboard, a project, a finished run (report, evidence, citations), Settings… — Dashboard (/project), a finished run (report, evidence, citations, artifact), Settings (Models, About) in light and dark: About shows 3.0.2 and 0a9de70ee; failed requests only the five deliberate pre-login session probes. One uncaught React error 418 (hydration) on every full load of /settings/appearance — present in 3.0.1 too, so pre-existing (Finding 12). Accepted for 3.0.2 by the release manager on 2026-10-19, documented in releases.ts known and the changelog; fixed on main by #201 (f60b28a) for the next release |
| M5.02 | PASS | Keyboard-only pass over the two gates: plan approval and report approval are reachable and operable… — Keyboard only, on the published macOS app (3.0.2, 0a9de70). Plan gate: Shift+Tab reached *Approve plan* with a visible focus ring and Return approved it. Report gate: Tab from the Review tab through *See which* and the feedback box reached *Approve report*, focus ring visible, and Space approved it. *Request changes* and *Request rework* sit next in the same order |
| **Phase 6 — Desktop Application Verification** | | |
| M6.01 | PASS | Record the artifact table in the record for all four installers: file name · SHA-256 · OS · architecture ·… — Artifact table above; every blank carries its NOT RUN reason |
| M6.02 | NOT RUN | On every platform, run the packaged-engine checker against the **installed** copy of the **published**… — macOS PASS — check_packaged_sidecar.py --journey --require-verify on the engine inside the published DMG: 3.0.2 at 0a9de70 (not dirty), plan_approved + approved, bundle v2 verify PASS, tree 143.4 MB. Windows and Linux: no machine here; CI drove the installed .msi, .deb and AppImage engines through a journey on the tag (A6.02 PASS), which is the engine, not a person's install |
| M6.03 | PASS | Mark every desktop row in the record as *packaged* or *source* — Every desktop row says packaged or source; the engine checks above are packaged, from the published DMG |
| **Phase 7 — macOS Verification** | | |
| M7.01 | PASS | Download the `.dmg` from the release in a browser (so it carries the quarantine flag) and verify it — Research.Assistant_3.0.2_aarch64.dmg (80,098,041 bytes): shasum -a 256 -c SHA256SUMS → OK. Downloaded with gh, which sets no quarantine flag, so M7.04 applied one by hand |
| M7.02 | PASS | The DMG opens and holds the app at the right version — Mounted: the app and an Applications link; CFBundleShortVersionString 3.0.2; 152 MB (3.0.1: 146 MB) |
| M7.03 | PASS | The signature is whole and valid — flags=0x10002(adhoc,runtime), not linker-signed; Sealed Resources version=2 files=283; valid on disk; satisfies its Designated Requirement |
| M7.04 | PASS | Gatekeeper judges a quarantined copy as policy, not damage — Quarantined copy: spctl --assess --type execute → rejected (a policy verdict, not damage) |
| M7.05 | PASS | The bundled engine is present, native, and unmodified by hardened runtime — research-sidecar: Mach-O 64-bit executable arm64; flags=0x2(adhoc), no hardened runtime; its _internal holds python3.14 (#189) |
| M7.06 | PASS | The packaged engine identifies itself and completes the journey — check_packaged_sidecar.py on the mounted published app: 3.0.2, git_sha 0a9de70 (not dirty), journey PASS, verify_bundle PASS, tree 143.4 MB |
| M7.07 | PASS | First launch as a user: drag to Applications; open it *without* the command and confirm the block is the… — Installed over the release manager's 3.0.0 (the app and `~/.research-engine` backed up first), with the download's quarantine flag set: `spctl` rejected it, and the first launch without the command showed "“Research Assistant.app” Not Opened — Apple could not verify…" with *Move to Trash* / *Done*: the documented block, not "damaged". After `xattr -dr com.apple.quarantine` it opened the existing data. Settings → About: 3.0.2, 0a9de70ee, built 2026-10-19T18:44:17Z, API contract fdcd9fceecf4f347 |
| M7.08 | ACCEPTED | The Phase 20 desktop journey on macOS (M20.02) — On the published app in a throwaway home, with Ollama and no key. The first run failed at once with "No provider key found" (Finding 14). Settings offered no local preset, and Save URL for a custom endpoint answered "Unknown provider." The journey continued after the two settings the GUI could not save (the endpoint URL, and routing `ollama:qwen2.5:7b`) were written into that profile: planner (4 tasks) → plan gate (keyboard) → executor 4/4 → critic → synthesizer → report gate (keyboard) → approved. "All 4 citation markers resolve"; `.md` and bundle exported; the bundle verifies offline (7/7), models `ollama:qwen2.5:7b`, `demo: false`. **Accepted:** present in every desktop release since 2.1.0, including 3.0.1, which the site offers today; fix #202 is in review for the next release; known issue with a workaround |
| M7.09 | PASS | Quit the app; no engine is left running — Quit from the app menu twice, on the release manager's data and on the throwaway profile: `research-desktop` and `research-sidecar` were both gone within 1 s, and nothing was listening on the engine's port |
| **Phase 8 — Windows Verification** | | |
| M8.01 | NOT RUN | Download the `.msi` in a browser; verify it — No Windows machine available |
| M8.02 | NOT RUN | SmartScreen shows the unknown-publisher warning; **More info → Run anyway** proceeds, exactly as the… — No Windows machine |
| M8.03 | NOT RUN | Install completes; Start-menu entry exists; Settings → Apps shows version `X.Y.Z`; files under `C:\Program… — No Windows machine |
| M8.04 | NOT RUN | Launch: the window opens without a crash; Task Manager shows `research-sidecar.exe`; no firewall prompt… — No Windows machine |
| M8.05 | NOT RUN | `python scripts\check_packaged_sidecar.py --search "C:\Program Files\Research Assistant" --expect-sha <tag… — No Windows machine; CI installed the published .msi's twin and drove its engine (A6.02) |
| M8.06 | NOT RUN | The Phase 20 desktop journey on Windows (M20.02), from a user whose profile path has a space; exports save… — No Windows machine |
| M8.07 | NOT RUN | Local storage: data under `%USERPROFILE%\.research-engine`; provider keys in Windows Credential Manager,… — No Windows machine |
| M8.08 | NOT RUN | Quit: `research-sidecar.exe` exits (the watchdog — two Windows-only crashes lived here, #113) — No Windows machine |
| M8.09 | NOT RUN | Uninstall from Settings → Apps: the Program Files directory is removed; user data remains (as documented) — No Windows machine |
| **Phase 9 — Linux Verification** | | |
| M9.01 | NOT RUN | AppImage: download, verify (`sha256sum -c SHA256SUMS --ignore-missing`), `chmod +x`, launch from a desktop… — No Linux desktop session; CI extracted the AppImage and drove its engine (A6.02) |
| M9.02 | NOT RUN | `.deb`: `sudo apt install ./Research.Assistant_X.Y.Z_amd64.deb` on a clean supported Ubuntu LTS resolves… — No Linux machine; CI installed the .deb and drove its engine (A6.02) |
| M9.03 | NOT RUN | Key storage uses the Secret Service keyring; on a session without one, the app says so rather than storing… — No Linux desktop session |
| M9.04 | NOT RUN | `sudo apt remove research-assistant` removes the application; user data remains; no engine left running — No Linux machine |
| **Phase 10 — Docker / Container Verification** | | |
| M10.01 | PASS | Run the published images on the full-stack topology, on their own volumes: — Published 3.0.2 images via release-audit/compose.published-images.yml (project release-check, port 3041): five services healthy; an empty database migrated to head (29 steps); /api/v1/version through the frontend proxy reports 0a9de70 |
| M10.02 | PASS | On that stack: register, log in, create a project, run a fake-mode research through both gates, export… — Register, login, project, fake-mode run through both gates, export.md 200, export.pdf 200 (%PDF, 16 KB), bundle.json 200 — v2, demo-stamped (banner, demo: true, .md stamped), verify_bundle PASS |
| M10.03 | PASS | On an arm64 host (Apple Silicon Docker or the Ampere target), the same stack starts from the same tags — This host is arm64: every stack above ran the arm64 images. amd64: the worker image started under emulation and reported 3.0.2 at 2a560d2 (E1, the same Dockerfile and stamp path); no amd64 host for a full stack |
| M10.04 | PASS | Tear down with `down -v` using the same flags; the developer's own `mara_full_*` volumes are untouched — down -v with the same flags removed only release_check_*; the three mara_full_* volumes and the owner's running stack untouched |
| **Phase 11 — GitHub Release Verification** | | |
| M11.01 | PASS | Add the hand-written summary at the top of the Release body (what changed for users, the macOS… — Summary added above the generated notes on 2026-10-19, and the whole body read as a user would. It covers what changed for users, the macOS first-launch command, and the three known issues most likely to matter (with a link to the changelog's **Known**); the image list and the generated PR list are kept below it |
| **Phase 12 — Documentation Verification** | | |
| M12.01 | PASS | For each scope row, the docs describe what shipped — on both hosts, with desktop differences stated… — docs/04 §4 (results-page refusal), docs/19 (citation number ≠ cited, corrected), docs/34 (`cited_indices`), docs/20 (start.sh's real-or-demo rule), deploy/README.md (`latest`); desktop differences: none for these rows |
| M12.02 | N/A | Configuration: every environment variable added, renamed or removed since the previous release (`git diff… — `git diff --stat v3.0.1..a887720 -- backend/app/config.py backend/research_engine/local.py .env.example` is empty |
| M12.03 | PASS | Search the docs for removed or renamed features, commands and routes named in the diff (`git diff --stat… — Nothing removed or renamed; `start.sh`'s mode rule widened (docs/20 updated), the Oracle default changed (deploy/README.md updated) |
| M12.04 | N/A | Architecture docs (`docs/architecture/02`, `04`) match the graph's nodes and gates — Graph nodes and gates unchanged — graph.py's diff is the fan-out primitive and a url type guard |
| M12.05 | PASS | Known limitations agree across `releases.ts` `known`, the changelog **Known**, the Release body and the… — `releases.ts` known (22 items), the changelog's **Known** and the Release body's summary (which names the three that matter most and links the changelog) agree, including Findings 11, 12 and 14 |
| **Phase 13 — README Verification** | | |
| M13.01 | PASS | Read the README top to bottom against the release: the feature list (nothing unreleased, nothing removed),… — README diff since 3.0.1: one sentence linking RELEASE.md and release-audit/. Features, platforms, commands and the measured claim (A1.14 PASS) still current |
| **Phase 14 — Landing Page Verification** | | |
| M14.01 | PASS | View `/` at desktop width and at 375 px, light and dark: hero, download call-to-action, "New in" link to… — Live `/` after the flip, at desktop width (light) and at 375 px (light, and dark through the site's toggle): the hero; *Get the desktop app →* to `/download/`; "NEW IN V3.0.2 … What changed →" to `/releases/#v3.0.2`; feature cards. No horizontal scroll at 375 px. Dark at desktop width was not checked |
| M14.02 | PASS | `/why`: every comparison claim (`frontend/lib/comparison.ts`) still holds for this release — `lib/comparison.ts` and `lib/features.ts` are unchanged since v3.0.1, and nothing in this release removes what they claim. One figure is dated rather than wrong: "citation support is 96.4%" is 3.0.0's run, stated without attribution, while 3.0.2's run measured 96.9% (Finding 16) |
| **Phase 15 — Download Page Verification** | | |
| M15.01 | PASS | On each OS (or with a UA override), the detected-OS card leads; the big button and every card button point… — Live `/download/` on a Mac UA: the macOS card leads; the selector reads "v3.0.2 (latest)"; the big button and all four card links point at the v3.0.2 assets, each answering 200 from release-assets; the command is the documented `xattr -dr com.apple.quarantine` line (A12.02). The size note now reads "~80 MB download, ~150 MB installed", within 15% of 80.1 MB and 152 MB (Finding 13). No UA override for Windows or Linux; A15.01–A15.03 PASS on the file names |
| M15.02 | NOT RUN | Download one installer by clicking the page's button in a real browser; the file name and checksum are right — Not clicked through in a browser: a browser download needs the release manager's own go-ahead. A11.06 (post-release, `--download`) fetched and hashed every installer at the same URLs the buttons use, and each matched `SHA256SUMS` |
| **Phase 16 — Releases Page Verification** | | |
| M16.01 | PASS | View `/releases`: the new entry is first with the tag's date; its summaries are shown and the lists fold… — Live `/releases/`: v3.0.2 first, dated 2026-10-19, headline and both summaries shown. *All 15 improvements* and *All 22 known gaps* fold open, the latter with the desktop keyless issue. The index link `#v3.0.1` jumps to its entry, and all ten releases are present. No "unreleased" text on the page |
| **Phase 17 — GitHub Pages / Deployment Verification** | | |
| M17.01 | N/A | If A17.01 fails because `main` moved after the flip, wait for the newer deploy and re-run; if the deploy… — A17.01 PASS: the deployed site is the flip commit's build |
| **Phase 18 — Security / Configuration Verification** | | |
| M18.01 | PASS | Review `git diff vPREV..HEAD` for debug flags, test accounts, credentials, private URLs, and anything that… — Added lines searched for prints, debuggers, test accounts, credentials and private URLs: every `print` is in a CLI script (`scripts/`) or a workflow step, every loopback URL in a test fixture or the packaged-engine checker; no credentials |
| M18.02 | N/A | If `backend/app/config.py`, the security middleware, auth, or the SSRF guard changed: re-check CORS… — No change to app/config.py, auth, middleware or the SSRF guard since 3.0.1 |
| M18.03 | PASS | No secret or env file ships in an artifact — Engine inside the published DMG: no key-shaped string, no env file (3.0.1's primp look-alike is gone). Published api and worker images: no /app/.env, no env files, no key-shaped string outside tests |
| M18.04 | PASS | Public surface: `/api/v1/version` is unauthenticated on the server by design; nothing else new is — No route added on either host since v3.0.1 (git diff v3.0.1 v3.0.2 of backend/app/api and the sidecar) |
| **Phase 19 — Upgrade / Migration Verification** | | |
| M19.01 | PASS | Fresh install: an empty database migrates to head (CI), and a fresh desktop data directory starts (M6.02… — A fresh Postgres migrated to head on the published images (M10.01); a fresh desktop data directory started on the published engine (M7.06) |
| M19.02 | PASS | Server upgrade from the previous release: run the previous release's images (`RELEASE_TAG=PREV` with the… — Published 3.0.1 images (Python 3.11.16) seeded a database: an approved and exported run, saved preferences and custom planner instructions, a run at each gate. 3.0.2 swapped onto the same volumes (Python 3.14.8, no migration): the account logs in; preferences and instructions intact; all three runs in their states; the old run re-exports md/pdf/bundle (byte-identical); the plan-gate run approved, researched, reworked, approved; the report-gate run reworked — resuming its 3.11-written checkpoint on 3.14 — and approved; both bundles verify, recording the frozen custom planner. (Login was first refused 429 by the per-email limiter after six logins in 15 minutes — Finding 11, pre-existing.) BYOK key and sessions not seeded |
| M19.03 | PASS | Desktop upgrade from the previous release: install the previous release, create the same data, install… — Manual procedure (make_upgrade_fixture.py refuses anything but v2.1.0): the published 3.0.1 engine (d53d645, Python 3.11) wrote a data directory — saved instructions, a completed run, runs at both gates — and the published 3.0.2 engine (0a9de70, Python 3.14) opened it: all present; the old bundle byte-identical and verifying; both waiting runs resumed, reworked and approved with verifying bundles; no engine left running. macOS only |
| M19.04 | PASS | Downgrade: CI's round-trip proves the schema reverses; record whether running the previous images against… — Supported: 3.0.1's images on the database 3.0.2 touched start healthy, log in, list every run COMPLETED, and serve the run 3.0.2 finished (the same 37,083-byte frozen bundle). No migration in this release |
| M19.05 | PASS | A bundle exported by the previous release verifies with this release's verifier, unchanged (`python -m… — Bundles exported by 3.0.1 — on the server and on the desktop — verify with 3.0.2's verifier on Python 3.14 |
| **Phase 20 — Final End-to-End Production Smoke Test** | | |
| M20.01 | PASS | The web/self-hosted journey on the Phase 10 stack, **with a real provider at least once** (fake mode… — Published 3.0.2 images with LLM_MODE=real through the owner's OmniRoute (custom:auto/best-fast, a router alias): heat pumps vs gas boilers, both gates, export.md/.pdf, bundle v2 demo: false, 10 evidence, 7 sources, 23 claims, verify_bundle PASS 7/7 including citation_resolution |
| M20.02 | ACCEPTED | The desktop journey on each platform (M7.08, M8.06, M9.01/M9.02), with a real provider or Ollama — macOS: M7.08. The journey completes on the published app with Ollama once past Finding 14, which is accepted with it. Windows and Linux: no machine here; CI drove the installed engines (A6.02) |
| M20.03 | PASS | Negative paths on the published build: an invalid provider key is reported as rejected by its provider as soon as it is saved… — On published builds. **Invalid key:** the 3.0.2 server images stored it and reported at once "openrouter answered, but rejected this key (HTTP 401)." That is the shipped design (internal/07 Phase 2a: saving is testing, and a failed probe never blocks the save); this check's old wording, "refused before it is stored", described behaviour that never shipped, and is reworded in the flip PR. **Cancel:** in the desktop GUI, stopped during the critic, still `CANCELLED` 80 s later; on the packaged engine, cancelled straight after plan approval, `CANCELLED`, and an approval answered 409. **Rework:** resumes and is approvable on the second pass (M19.02, M19.03). **Refresh:** reopening the run page mid-run resumed the live feed at the run's real state, and it kept updating; the desktop shell has no reload command, and a browser reload on the web host was not exercised. **Restart at a gate:** packaged engine stopped and relaunched with a run at the plan gate; still `AWAITING_PLAN`, then approved, completed, bundle verify PASS. **Tamper:** one byte changed in that bundle, `verify_bundle` FAIL |
| M20.04 | PASS | Every `[n]` in the final report resolves on hover to a source and its snippet; an unresolved one renders… — Desktop run page: "All 4 citation markers in this text resolve to a cited source". Hovering `[1]` shows the source title, its domain, the quoted snippets and *Open source ↗*. Claims the synthesizer could not tie to evidence carry an inline "(citation could not be verified)", and the review page warned "20 claims resolved to no evidence" before approval. No unresolved `[n]` occurred in this report, so the ⚠ chip was not seen live; `test_citation_verification.py` and the uiqa fixture pin it |
| **Phase 21 — Release Approval** | | |
| M21.01 | PASS | Every WARN and UNAVAILABLE in the published audit has a written disposition in the record — Dispositions above for every WARN in pre-tag.json and published.json |
| M21.02 | PASS | Known issues are documented everywhere they belong (M12.05), including anything this audit found and the… — Known issues section below: every defect this audit found and the release accepted (Findings 11, 12, 14) is in `releases.ts` known, the changelog's **Known**, and the Release body |
| M21.03 | PASS | The release manager signs the approval block in the record — Signed below by Claude Code on the release manager's instruction of 2026-10-19 ("do all for me what is left behind"); the acceptance of Finding 14 is the call they should review |
| **Phase 22 — Post-Release Verification** | | |
| M22.01 | PASS | The flip PR: drop `unreleased`, set the entry's `date` to the tag's date, date the changelog heading,… — #203 merged as merge commit `fb3db0a` (2026-10-20T00:45Z): `unreleased` dropped, dated 2026-10-19, changelog heading dated, size note corrected. Pages run 39349541844 deployed it, and the live download page offered 3.0.2 from 00:47Z |
| M22.02 | PASS | After Pages deploys: run the post-release audit with `--download --docker`, commit its JSON (write-once)… — Post-release audit with `--download --docker` on `fb3db0a` after these rows were filled, saved as `post-release.json` |
| M22.03 | NOT RUN | Load `/`, `/why`, `/docs`, `/download`, `/releases` on a phone and a desktop browser with the cache disabled — Not on a phone. In the browser pane at desktop width and 375 px emulation, all five pages load (200) with their content; each logs one 404, for `/api/v1/projects` (Finding 15) |
| M22.04 | PASS | In an installed copy of the **previous** desktop release, Settings → About → *Check for updates* reports… — The installed 3.0.0 and 3.0.1 desktop engines both answer `/updates/check` with `update_available` → 3.0.2 |
| M22.05 | NOT RUN | For 48 hours, watch issues and discussions for install or launch reports; any release-blocking report… — The window is open until 2026-10-22T00:47Z, 48 h after the site began offering 3.0.2. As of 2026-10-20T00:55Z: no issues opened since the tag |
| M22.06 | PASS | Every incident found during this release becomes a check: an `A…` check (preferred) or an `M…` item, plus… — Incidents table below: two audit gaps became fixes with negative-control tests in this PR |

## Findings

Found while preparing stage A, separated by kind.

**Release-blocking, resolved during stage A**

1. **Open high-severity dependency alerts (A18.05, STOP).** On 2026-10-18: `next` < 16.3.8
   (high: SSRF in Image Optimization, which the standalone server leaves enabled; plus two
   medium and one low advisories), `sharp` < 0.35.5 (high: librsvg), `source-map-js` < 1.2.2
   (high: event-loop denial of service), and `postcss-selector-parser` < 7.1.6 (medium).
   Dependabot's #185, #184 and #183 — green — were merged on 2026-10-18 with the release
   manager's approval and are in the scope table. `postcss-selector-parser` (medium, alert #31, GHSA-rj75-hqrm-r3gf) had no
   upstream fix: `@tailwindcss/typography` pins 6.0.10 exactly, in its latest release too.
   **Resolved by #199** with an `overrides` entry scoped to the plugin. On Node 26 the
   compiled CSS of the web build and the Pages export is byte-identical with and without it.

**Verified, with a gap left open**

2. **#173 moved the server images from Python 3.11 to 3.14, and nothing had built them.**
   `ci.yml` and `desktop.yml` never build `backend/Dockerfile`; `release.yml` builds it only
   from a tag, so this release's images would have been the first 3.14 build anywhere — while
   every test job, the desktop engine and the release tooling run 3.11. Checked on
   2026-10-18 on Apple Silicon: the `api` target builds (`python:3.14-slim-bookworm`,
   Python 3.14.8; every pinned package installs), and the full backend suite on `a887720`'s
   tree, run inside that image against pgvector and Redis, gave **2072 passed, 1 failed, 1
   skipped**. The failure is the container, not the interpreter:
   `test_routing_is_read_through_the_real_openai_client_end_to_end` serves a stub on
   `127.0.0.1`, and inside Docker Desktop `map_local_host` rewrites that to
   `host.docker.internal`; with no network, so the name cannot resolve, the same file passes
   30/30 under 3.14. The skip is the retrieval eval's missing local embedder. The real-mode
   worker lifecycle tests — the path #171 fixed — ran and passed, and no asyncio deprecation
   was raised. **Not checked:** the amd64 image (release.yml builds both), and the image
   running a real-provider journey (stage B, M20.01). **Gap:** the image and CI run different
   interpreters, and nothing would notice the next drift.

   **Resolved in this release:**
   - The release manager chose to move CI to the image's Python before the tag.
   - #187 moves `ci.yml` and `release.yml`'s stamp job to 3.14, and adds A10.06, which fails a
     commit that moves any workflow's Python alone.
   - #189 freezes the desktop engine on 3.14 too, so A10.06 holds with no exception.
   - The release evaluation ran on 3.11.15, before this change. The code it measured is
     unchanged, and the interpreter isn't one of A2.03's quality paths.

**Release-process defects (fixed in this PR)**

3. **A2.01 was blind to squash merges.** It counted only `Merge pull request #N`, so #179,
   #180 and #181 — squash-merged — were outside the scope check. `evaluate.merged_prs` reads
   both styles.
4. **A2.03 read the template's placeholder as a waiver.** `Eval waiver: <!-- … -->` matched
   `^Eval waiver:\s*\S`, so a record copied and never edited downgraded a missing evaluation
   to a WARN — the first preview of this release's pre-tag audit showed exactly that.
   `evaluate.records_eval_waiver` ignores the placeholder.

**Found on a local build, not in any published artifact**

7. **A local image reports another build's identity.** `backend/research_engine/_build.py` is
   generated by `stamp_build.py` and git-ignored, but `backend/.dockerignore` does not exclude
   it, so a stale stamp left in a checkout is copied into every image built from it. On
   2026-10-18 this machine's `./start.sh --rebuild` of the 3.0.2 tree answered
   `/api/v1/version` with `version 2.1.0`, `git_sha 33f1916`, `built_at 2026-09-27` — a
   leftover from a September stamp — while `/health` and the code said 3.0.2. Published images
   are stamped fresh by `release.yml` (A10.05 checks the result), so this is a local-build
   defect. Excluding the file from the image would break that stamping.

   **Resolved in this release by #188:**
   - The Dockerfile discards any stamp in its build context, unless `release.yml` passes
     `BUILD_STAMP=context`.
   - `start.sh` hands the image the checkout's own version, commit and dirty flag.
   - The sidecar spec refuses a stamp that doesn't describe the checkout.

8. **#193 raised the Python needed to run the engine, and the bundle verifier, to 3.14.**
   It was merged on 2026-10-19 by the release manager, after #187–#189.
   - `research_engine/__init__.py` now refuses older interpreters. `verify_bundle.py` uses
     3.14-only syntax (PEP 758 `except A, B:`), so it can't even be parsed on 3.13 or earlier.
   - The **bundle format is unchanged** (still v2). The v3.0.1 verifier at `d53d645`, on
     Python 3.11.15, verifies E3's 3.0.2 bundle **PASS 7/7**. So a third party on an older
     Python has a working path: the previous release's verifier. That's why the version stays
     patch (M0.03): no bundle is refused, only a newer interpreter is needed for the newest
     verifier. The changelog and `releases.ts` both carry the floor and the workaround.
   - E3's 3.11 verification ran on `2a560d2`'s verifier, before #193. On `3d5af71`, that same
     interpreter is refused with `research_engine needs Python 3.14+`, which was checked
     directly.
   - A19.02 warns because #193 touched six ORM model files and `verify_bundle.py`. The
     models changed only in annotation syntax (forward references unquoted, which 3.14's
     deferred annotations allow); no column, constraint or table changed, and there is no
     migration. `verify_bundle.py` changed its docstring and that one `except` line. The
     upgrade rows A19.02 makes required (M19.02–M19.05) were already required by the
     interpreter move and are planned under Extra checks.

9. **The frontend image's Node is not the Node anything tests.** CI's `frontend` job, the
   desktop build and the Pages build use Node 22 (`setup-node`). `frontend/Dockerfile` was
   already on Node 25 before this release, and #172 moves it to 26. No job builds that image
   before a tag, so it's the frontend twin of Finding 2.
   - Checked for this release on 2026-10-19: #172's tree builds the `runtime` target on
     `node:26-bookworm-slim` (v26.12.0). The container comes up healthy.
   - `/`, `/login`, `/settings` and `/dashboard` answer exactly as the current Node 25 stack
     does (200, 200, 307, 404; `/dashboard` is not a route).
   - **Resolved in this release by #196**, at the release manager's choice of Node 26
     everywhere:
     - ci.yml's `frontend` and `golden-e2e`, desktop's `shell` and pages' `build` set up
       Node 26.
     - `frontend/package.json` declares `engines >=26`, and every `Node N+` in the docs
       says 26.
     - A10.07 fails a commit that splits them again. It shares A10.06's implementation
       through a `Runtime` descriptor.
     - Checked on 2026-10-19 in `node:26-bookworm-slim` (v26.12.0): `npm ci` (no engine
       warnings), lint, typecheck, 495/495 tests, and `build`, `build:desktop` and
       `build:pages`.

10. **A3.02 failed a release commit that changed nothing the site is built from (#198).** The first
    pre-tag run on `dedfbb0` (the merge of #197, which touched only this record) found no
    Pages run on it, because `pages.yml` runs only when `frontend/`, `docs/` or itself
    changes. The check assumed every release commit changes `releases.ts`. The site
    `dedfbb0` serves is the one `f51800f`'s Pages run built and deployed. **Fixed in this
    release:** A3.02 now judges the Pages run of the last first-parent commit that touched
    `pages.yml`'s own `paths:` filter, read from the workflow so the two can't drift. Run
    against `dedfbb0`, it passes on run 39269503933 (`site_built_from: f51800f`).

11. **The per-email login limit counts successful logins.** `LOGIN_EMAIL = RateLimit(5, 900)`
    carries the comment "5 failures / 15 min", but `auth.login` calls `rate_limit.check` on
    both counters *before* it verifies the password, so every attempt counts. A sixth login
    within 15 minutes, on a correct password, gets 429 — found when M19.02's sixth login of
    one test account was refused. Unchanged since M2 (`ad1db37`, July), so not a 3.0.2
    regression; it ships in 3.0.2 and is in its known issues. **Fixed on main by #200**
    (`0720cba`) for the next release: the account limit counts failures only.
12. **An uncaught React #418 hydration error on page load.** Seen in the browser on the
    published 3.0.2 frontend, and on the published 3.0.1 frontend before any theme change, so
    it predates this release (the theme code is unchanged since v3.0.1; #191's Next.js
    16.4.2 is not the cause). React recovers by re-rendering on the client, but M5.01 asks for
    no uncaught errors. **Accepted for 3.0.2** by the release manager (M5.01 ACCEPTED) and
    in its known issues. The cause, found afterwards: the theme picker rendered its selection
    from next-themes' `resolvedTheme`, undefined on the server, so every full load of
    /settings/appearance threw. **Fixed on main by #201** (`f60b28a`) for the next release.
13. **The download page's size note, measured on 3.0.2:** ~80 MB download (actual 80.1 MB,
    fine) and ~180 MB installed (actual 152 MB, 15.6% under — just past M15.01's 15%). Carried
    from the v3.0.1 record's Finding 3. **Fixed in the flip PR:** the note says ~150 MB installed,
    within 15% of 3.0.2's 152 MB and 3.0.1's 146 MB.
14. **A desktop with Ollama and no API key cannot research (M7.08).** Found in the GUI journey on
    the published app, in a throwaway home with Ollama running and no key stored. Three desktop-only
    defects close the path that Settings describes as "no API key":
    - `sidecar_run_config` refused any run with no key stored, whatever the routing ("No provider
      key found"). The CLI and the server both exempt `ollama` and `custom`.
    - The desktop catalog answered `available_providers` from keys alone, so `ollama` was never
      listed, and the Models card offered no local preset beside an Ollama card reading
      *Connected*.
    - `PUT /desktop/keys/custom_endpoint` was shadowed by `PUT /desktop/keys/{provider}`, so Save
      URL answered "Unknown provider." `test_host_parity` passed, because the route was registered
      and nothing called it.
    The run form also defaults *Local LLM* to the first installed model, even one Settings marks
    *chat only*. All four are unchanged since 2.1.0 (`9ad114de`), so every desktop release since has
    them, including 3.0.1, which the site offers today; holding the flip would not protect
    anyone. **Accepted for 3.0.2** (M7.08, M20.02 ACCEPTED). Known issue with a workaround: save
    any text as the Custom Endpoint key, which Ollama ignores; verified on 3.0.2's own
    `sidecar_run_config`. **Fix in review: #202** (five new tests fail on `main` and pass there).
15. **Every public site page asks the app's API for projects, and logs a 404.** `ActiveProjectProvider`
    sits in the root `Providers`, so on GitHub Pages `/`, `/why`, `/docs`, `/download` and
    `/releases` each fire `GET /api/v1/projects?archived=false` at the domain root. There is no
    backend there, so each page logs a 404. The pages work. Present since 2.0.1 (`39efade5`);
    found at M22.03; not fixed in this release.
16. **The site's headline citation figure is 3.0.0's, and does not say so.** `lib/features.ts` and
    `lib/comparison.ts` say "citation support … 96.4%". 3.0.2's own run, on the same routing and
    judge, measured 96.9%. The README and docs attribute 96.4% to "the 3.0.0 release run"; the
    two site strings do not. True, but unattributed. Whether the site quotes the newest run is the
    release manager's call. Found at M14.02.

**Carried over from the v3.0.1 record, still open**

5. The download page's size note (~80 MB download, ~180 MB installed) against 3.0.1's
   measured 70.3 MiB and 146 MB; re-measure on 3.0.2's artifacts at M15.01.
6. Two historical release dates disagree with their tags (A16.03 WARN): v1.0.0 and v1.0.2.

## Extra checks this release needs (#173, #187, #188, #189)

This release moves the server and the desktop engine from Python 3.11 to 3.14, and changes
how every build stamps itself. That turns several rows a plain patch would mark `N/A` into
required ones. Each line names the row it decides; none is satisfied by source evidence
(M6.03).

**Before the tag (stage A), on the final `main`:**

- **E1.** Run `release.yml` by manual dispatch on the release commit. That builds images only,
  tagged `edge`, never `latest`. It runs #188's `BUILD_STAMP=context` path and the 3.14 stamp
  job once before the tag does. Its "the pushed image reports the commit that built it" step
  must pass for api and worker on both architectures. It publishes `edge` images to GHCR, so
  it needs the release manager's go-ahead.
- **E2.** Run `./start.sh --rebuild` on a clean checkout. `/api/v1/version` must report
  `3.0.2`, the checkout's commit and `dirty: false`. Then plant a stale `_build.py` in the
  checkout and rebuild: the image must still report the checkout, not the plant. This is
  #188's local path.
- **E3.** Run `./start.sh --rebuild` against the existing local database, which 3.11 images
  wrote. Migrations must apply on 3.14, a run left waiting at a gate before the switch must be
  approvable, and its bundle must verify.

**Stage A results:**
- **E1 — PASS.** I dispatched `release.yml` on `main` at `2a560d2` (the merge of #192) with
  `tag=edge`: [run 39261742738](https://github.com/adityamhaske/Multi-Agent-Research-Assistant/actions/runs/39261742738),
  2026-10-19.
  - The run passed: the stamp job on 3.14, all six image builds, and all three manifests.
    `release` was skipped, so no GitHub Release was created and `latest` didn't move.
  - "The pushed image reports the commit that built it" passed for api and worker, on both
    amd64 and arm64.
  - Checked independently by pulling and running `:edge`:
    - The api image on arm64 reports Python 3.14.8, `version 3.0.2`, `git_sha 2a560d2…`,
      `dirty False`.
    - The worker image on amd64 (under emulation, `platform.machine() == x86_64`) reports
      the same, so the amd64 image starts. That's the M10.03 amd64 gap, partly closed.
- **E2: PASS.** Run on 2026-10-19 on clean `main` at `2a560d2`, Apple Silicon.

  | Build | Stale stamp planted (2.1.0, `33f1916`) | `/api/v1/version` |
  |---|---|---|
  | `./start.sh --rebuild` | no | `3.0.2`, `2a560d2…`, `dirty false` |
  | `./start.sh --rebuild` | yes | `3.0.2`, `2a560d2…`, `dirty false`, on both the api and worker containers |
  | hand-run `docker build --target api` | yes | `unknown` in every field, `dirty true` |

  A local build reports `contract_version: unknown`, because only `release.yml` hashes the
  contract. It's honest, not stale. The planted file was removed afterwards.
- **E3: PASS.** Run on 2026-10-19 against the release manager's local database. Its runs were
  written by 3.11 images up to 2026-10-05; the stack was rebuilt on 3.14 at `2a560d2`.
  - **Migrations:** the database is at head (`0027_run_prompt_provenance`). 3.0.2 adds no
    migration, so `alembic upgrade head` on 3.14 was a no-op.
  - **Checkpoints:** there are 13 runs waiting at the report gate, created 2026-08-19 to
    2026-10-05 by 3.11 workers. On 3.14, all 13 checkpoints decode `READ` through
    `checkpoint_read.read_checkpoint`, each with its evidence and draft present. The graph
    places every one at `hitl_gate`, so they can still be resumed. This was read-only.
  - **Approval doesn't resume a checkpoint.** It records the review and freezes the artifact
    from the tables (`runs.submit_report_review`). Only a rework resumes the graph, so M19.02
    must exercise a rework as well as an approval.
  - **Approval:** run `e4c2f880` (created 2026-10-05, owned by the throwaway account
    `e2e-ee3ea2e9@example.com`) was approved by calling `runs.submit_report_review` as its
    owner inside the 3.14 api container. Review `955b3c21`, artifact `de9749e2`, status
    `COMPLETED`.
  - **Bundle:** served by `runs.get_bundle` (113,859 bytes, sha256 `41e349e0…`), it verifies
    **PASS 7/7** with `python -m research_engine.verify_bundle` on 3.14 (in the image) and on
    3.11.15 (this Mac).
  - No run belonging to the release manager was approved.
  - The 3.11 verification ran before #193. On the release tree the 3.0.2 verifier needs
    3.14, and the v3.0.1 verifier on 3.11 verifies this bundle too (Finding 8).

**After the tag (stage B), on the published artifacts — rows that are no longer `N/A`:**

- **M19.02:** server upgrade from the published 3.0.1 images (3.11) to 3.0.2 (3.14), on a
  populated database: a project, a completed run, a run waiting at each gate, a session, a
  stored BYOK key, preferences and custom agent instructions.
  - The waiting runs' checkpoints were written by a 3.11 worker and must resume on a 3.14 one.
  - The BYOK key must still decrypt.
  - Old research must re-export, and its bundle must verify.
- **M19.03:** desktop upgrade from an installed 3.0.1 (3.11 engine) to 3.0.2 (3.14 engine), with
  the same data. `scripts/make_upgrade_fixture.py` only knows v2.1.0, so this is the manual
  procedure, on macOS at least. Record which platforms ran it.
- **M19.04:** record whether 3.0.1's images may run against a database 3.0.2 has touched. There
  is no migration, so the expected answer is yes; check it, don't assume it.
- **M19.05:** a bundle exported by 3.0.1 must verify with 3.0.2's verifier, which now runs on
  3.14.
- **M6.02, M7.06, M8.05, M9.01–M9.02:** run the packaged-engine checker with `--journey` on the
  installed copy on each OS.
  - It must report version `3.0.2` and the tag's SHA. This is the first published engine
    stamped through #188's spec check.
  - Compare the engine tree with 3.0.1's 138 MB. A 3.14 freeze is a different set of
    libraries, and an undersized tree is a STOP.
- **M7.03–M7.05:** re-check the macOS signature, the Gatekeeper verdict and the engine's flags,
  on a bundle whose interpreter and dylibs all changed.
- **M8.04, M8.08:** Windows launch and quit, with no orphaned `research-sidecar.exe` left
  behind. The watchdog sits in the code where two Windows-only crashes once lived (#113), and
  it now runs on a new interpreter.
- **M18.03:** the secret scan over the new engine tree. Read every hit with `grep -ao`.
- **M4.02, A10.05:** the published api **and** worker images must report the tag's commit.
  This is the first tag through `BUILD_STAMP=context`.
- **M10.03:** arm64 on this Mac, as before. With no amd64 host available, at least start
  amd64 under emulation (`docker run --platform linux/amd64`).

## Known issues shipped with this release

Everything in `frontend/lib/releases.ts` v3.0.2 `known` (22 items): 3.0.1's sixteen, carried;
evidence duplicated by a rework before this release; the spend limit doing nothing on
`openrouter` and `custom` routes; the verifier's Python 3.14 floor (Finding 8); and, accepted
at sign-off review, the sign-in limit counting successes (Finding 11) and the Appearance
page's hydration error (Finding 12), and the desktop refusing keyless research (Finding 14).
The size note (Findings 5 and 13) is corrected by the flip PR, not shipped as known.

## Incidents found during this release, and the check each became (M22.06)

| Incident | Check added |
|---|---|
| A2.01 counted only merge commits; squash-merged PRs escaped the scope check | `merged_prs` (A2.01); `test_a_squash_merged_pr_is_in_scope_as_surely_as_a_merge_commit` |
| A2.03 read the template's waiver placeholder as a waiver | `records_eval_waiver` (A2.03); `test_the_templates_waiver_placeholder_is_not_a_waiver` |
| A dependency bump changed the server images' Python with nothing building the image | A10.06 (#187, #189): every workflow's Python equals the image's |
| A3.02 failed a record-only release commit, which the path filter rightly gave no Pages run | A3.02 judges the last site-changing commit's Pages run; `test_the_push_path_filter_is_read_and_nothing_else` |
| The frontend image's Node (25, then 26) differs from CI's (22), and nothing builds the image before a tag | A10.07 (#196): every workflow's Node and every stated floor equal the image's |
| A local image carried a stale build stamp and reported another version and commit | `test_local_build_stamp.py` (#188); the sidecar spec refuses a stale stamp |

## Release approval

```text
Version:            v3.0.2
Commit:             0a9de70ee90485531120856fce7f5dde4041c0aa
Tag:                v3.0.2 (annotated, 2026-10-19)
Release manager:    Aditya Mhaske — signed by Claude Code on their instruction, 2026-10-19

Automated checks    [x] pre-tag PASS   [x] published PASS   [x] post-release PASS
Desktop             [x] macOS PASS     [ ] Windows PASS     [ ] Linux PASS
Web                 [x] Landing PASS   [x] Download PASS    [x] Releases PASS   [x] Docs PASS
Distribution        [x] GitHub Release PASS   [x] Docker PASS   [x] Checksums PASS
Security            [x] PASS
Upgrade/migration   [x] PASS
Critical journey    [x] web PASS   [x] desktop PASS
Known issues        [x] documented everywhere they belong
```

- pre-tag and published: no FAIL; every WARN has its disposition above (M21.01).
- macOS: every M7 row PASS, except M7.08 ACCEPTED with Finding 14. The desktop journey box
  is ticked on the same terms.
- Windows and Linux: not run, because there is no machine here. CI installed and drove both
  engines (A6.02).
- Web and post-release: ticked after the flip deployed (M14–M17, M22). The post-release
  audit has no FAIL (`post-release.json`). Still open: M22.05's 48-hour watch, which ends
  2026-10-22T00:47Z.

- [x] **Release approved**
