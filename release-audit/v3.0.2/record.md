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
| M2.02 | PENDING | For every feature on both hosts, confirm the desktop really has it: the route exists and behaves… — Source evidence so far: #181's rework journey passes on both the server and desktop drivers; #180 is server-only by design (project memory is pgvector-only). The packaged-desktop and published-image exercise is stage B (Phases 7, 10) |
| M2.03 | PASS | Read the `releases.ts` entry and the changelog entry against the matrix: `improved` states user-visible… — Read against the matrix: `improved` is user-visible effects only and includes the measured result; `known` carries 3.0.1's list plus the two new gaps; each summary compresses its list and adds nothing (A1.05 PASS; `releases.test.ts` bounds) |
| M2.04 | PASS | If A2.03 fails: run the release evaluation (`docs/developers/08-testing-and-evaluation.md`, "The release… — A2.03 required it (graph.py, prompts.py, tools.py changed). Release run under an independent judge: completion 1.0, citation support 0.9693 over 190 judged claims — both above threshold. `eval-2026-10-19-custom.json`; details under Scope → Evaluation |
| **Phase 3 — Automated Testing** | | |
| M3.01 | PENDING | Explain every re-run: any required job on the release commit that passed only on a retry is recorded with… — evidence: |
| M3.02 | PENDING | Read the non-blocking dependency-audit output of the release commit's CI run — evidence: |
| **Phase 4 — Backend / API Verification** | | |
| M4.01 | PASS | If `backend/app/api/` changed since the previous release, `docs/reference/34-api.md` and `35-sse.md`… — `backend/app/api` changed in `runs.py` only: #180 (no shape change) and #181's additive `cited_indices` on each revision, documented in docs/34; the sidecar serves the same projection. Contract hash re-checked on the stage B stack |
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
| M12.01 | PASS | For each scope row, the docs describe what shipped — on both hosts, with desktop differences stated… — docs/04 §4 (results-page refusal), docs/19 (citation number ≠ cited, corrected), docs/34 (`cited_indices`), docs/20 (start.sh's real-or-demo rule), deploy/README.md (`latest`); desktop differences: none for these rows |
| M12.02 | N/A | Configuration: every environment variable added, renamed or removed since the previous release (`git diff… — `git diff --stat v3.0.1..a887720 -- backend/app/config.py backend/research_engine/local.py .env.example` is empty |
| M12.03 | PASS | Search the docs for removed or renamed features, commands and routes named in the diff (`git diff --stat… — Nothing removed or renamed; `start.sh`'s mode rule widened (docs/20 updated), the Oracle default changed (deploy/README.md updated) |
| M12.04 | N/A | Architecture docs (`docs/architecture/02`, `04`) match the graph's nodes and gates — Graph nodes and gates unchanged — graph.py's diff is the fan-out primitive and a url type guard |
| M12.05 | PENDING | Known limitations agree across `releases.ts` `known`, the changelog **Known**, the Release body and the… — evidence: |
| **Phase 13 — README Verification** | | |
| M13.01 | PASS | Read the README top to bottom against the release: the feature list (nothing unreleased, nothing removed),… — README diff since 3.0.1: one sentence linking RELEASE.md and release-audit/. Features, platforms, commands and the measured claim (A1.14 PASS) still current |
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
| M18.01 | PASS | Review `git diff vPREV..HEAD` for debug flags, test accounts, credentials, private URLs, and anything that… — Added lines searched for prints, debuggers, test accounts, credentials and private URLs: every `print` is in a CLI script (`scripts/`) or a workflow step, every loopback URL in a test fixture or the packaged-engine checker; no credentials |
| M18.02 | N/A | If `backend/app/config.py`, the security middleware, auth, or the SSRF guard changed: re-check CORS… — No change to app/config.py, auth, middleware or the SSRF guard since 3.0.1 |
| M18.03 | PENDING | No secret or env file ships in an artifact — evidence: |
| M18.04 | PENDING | Public surface: `/api/v1/version` is unauthenticated on the server by design; nothing else new is — evidence: |
| **Phase 19 — Upgrade / Migration Verification** | | |
| M19.01 | PENDING | Fresh install: an empty database migrates to head (CI), and a fresh desktop data directory starts (M6.02… — evidence: |
| M19.02 | PENDING | Server upgrade from the previous release: run the previous release's images (`RELEASE_TAG=PREV` with the… — Required since the server images move from Python 3.11 to 3.14 (#173): upgrade from the published 3.0.1 images on a populated database, waiting runs resumed on 3.14 — Extra checks |
| M19.03 | PENDING | Desktop upgrade from the previous release: install the previous release, create the same data, install… — Required since the desktop engine moves to 3.14 (#189): an installed 3.0.1 upgraded to 3.0.2 with the same data, manual procedure — Extra checks |
| M19.04 | PENDING | Downgrade: CI's round-trip proves the schema reverses; record whether running the previous images against… — Record whether 3.0.1's images run against a database 3.0.2 has touched (no migration; check, do not assume) — Extra checks |
| M19.05 | PENDING | A bundle exported by the previous release verifies with this release's verifier, unchanged (`python -m… — A 3.0.1 bundle verified by 3.0.2's verifier, now on 3.14 — Extra checks |
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

Everything in `frontend/lib/releases.ts` v3.0.2 `known` (18 items): 3.0.1's sixteen, carried,
plus evidence duplicated by a rework before this release, and the spend limit doing nothing
on `openrouter` and `custom` routes. And the size note in Finding 5.

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
