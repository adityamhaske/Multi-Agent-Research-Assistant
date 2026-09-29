# Release process

**This is the canonical release checklist.** Every `vX.Y.Z` follows it, patch releases
included. It replaces the per-release gate tables that used to live in scope-freeze notes
(`internal/rfcs/V3.0-scope-freeze.md` §20 was the prototype).

The standard it enforces is one question, asked from outside:

> If a user downloads this release today from the public website, installs it on a
> supported platform, and follows the documented workflow — do the artifacts, the
> application, the website, the documentation, the GitHub Release, the Docker images and
> the user experience all correspond to **the same release**, and work as documented?

CI being green does not answer it. Every release this repository has cut shipped at least
one thing CI could not see — a 5 MB app with no engine inside, installers named for the
previous version, a checksum file listing names GitHub never serves, image pull commands for
a tag that did not exist, a Mac app every download reported as "damaged", a deploy guide
pulling a pre-1.0 image. Each is now a check below. **Every future release incident becomes
a check in the same PR that fixes it** — see [Maintaining this document](#maintaining-this-document).

---

## Contents

- [How to run a release](#how-to-run-a-release)
- [What a release consists of](#what-a-release-consists-of)
- [Release STOP conditions](#release-stop-conditions)
- Phases: [0 Scope](#phase-0--release-scope-freeze) ·
  [1 Versions](#phase-1--repository--version-consistency) ·
  [2 Features](#phase-2--feature-completeness) ·
  [3 Tests](#phase-3--automated-testing) ·
  [4 Backend](#phase-4--backend--api-verification) ·
  [5 Frontend](#phase-5--frontend-verification) ·
  [6 Desktop](#phase-6--desktop-application-verification) ·
  [7 macOS](#phase-7--macos-verification) ·
  [8 Windows](#phase-8--windows-verification) ·
  [9 Linux](#phase-9--linux-verification) ·
  [10 Docker](#phase-10--docker--container-verification) ·
  [11 GitHub Release](#phase-11--github-release-verification) ·
  [12 Docs](#phase-12--documentation-verification) ·
  [13 README](#phase-13--readme-verification) ·
  [14 Landing](#phase-14--landing-page-verification) ·
  [15 Download](#phase-15--download-page-verification) ·
  [16 Releases page](#phase-16--releases-page-verification) ·
  [17 Pages](#phase-17--github-pages--deployment-verification) ·
  [18 Security](#phase-18--security--configuration-verification) ·
  [19 Upgrade](#phase-19--upgrade--migration-verification) ·
  [20 E2E](#phase-20--final-end-to-end-production-smoke-test) ·
  [21 Approval](#phase-21--release-approval) ·
  [22 Post-release](#phase-22--post-release-verification)
- [Negative and failure-injection coverage](#negative-and-failure-injection-coverage)
- [Historical incidents and the checks they became](#historical-incidents-and-the-checks-they-became)
- [Release approval](#release-approval-sign-off)

---

## How to run a release

### The two-stage release

A tag publishes installers to a **public** GitHub Release immediately, but the website must
not offer a version until its installers exist and have been checked — offering it earlier
sends every visitor to a 404, which reads as a broken product. So a release lands in two
stages, and the audit runs at each boundary:

| Stage | Command | Phases | Gate to the next stage |
|---|---|---|---|
| **A. Prepare** — release PR merged to `main`, entry `unreleased: true`, not yet tagged | `scripts/release_audit.py --version X.Y.Z` | 0-5, 18, 19 | pre-tag audit exits 0; manual Phase 0-5 rows recorded |
| **B. Publish** — tag pushed, `Desktop` and `Release` workflows finished | `scripts/release_audit.py --version X.Y.Z --published --download --docker` | 6-11, 20, 21 | published audit exits 0; Phases 6-11, 20 recorded; **sign-off** |
| **C. Offer** — flip PR merged (entry downloadable), Pages deployed | `scripts/release_audit.py --version X.Y.Z --post-release --download --docker` | 12-17, 22 | post-release audit exits 0; record on `main` |

Per commit, CI runs the part that needs nothing but the checkout:
`scripts/release_audit.py --stage ci` (the `One version, everywhere` job).

### Step by step

```bash
# ── Stage A: prepare ───────────────────────────────────────────────────────────────
git switch -c release/vX.Y.Z origin/main
mkdir -p release-audit/vX.Y.Z && cp release-audit/TEMPLATE.md release-audit/vX.Y.Z/record.md
echo X.Y.Z > VERSION
# add the vX.Y.Z entry at the TOP of frontend/lib/releases.ts with `unreleased: true`
python scripts/sync_version.py --write          # derives 4 files from VERSION
(cd desktop && cargo update -p research-desktop)  # Cargo.lock — sync_version does not own it
# changelog: `## vX.Y.Z — unreleased` in docs/project/37-changelog.md
python scripts/release_audit.py --stage ci      # fix everything it reports, then:
# open the PR, get it green, merge with a merge commit (never squash)

git switch main && git pull
python scripts/release_audit.py --version X.Y.Z  # pre-tag: fix, re-run until exit 0

# ── Stage B: publish ───────────────────────────────────────────────────────────────
git tag -a vX.Y.Z -m "vX.Y.Z" && git push origin vX.Y.Z
# wait for the tag's Desktop and Release workflows to finish
python scripts/release_audit.py --version X.Y.Z --published --download --docker \
  --json release-audit/vX.Y.Z/published.json
# run the manual Phase 6-11 and 20 checks on the PUBLISHED artifacts; record each row
# sign off (Phase 21)

# ── Stage C: offer ─────────────────────────────────────────────────────────────────
# flip PR: drop `unreleased`, set `date` to the tag date, date the changelog heading,
#          commit the record and published.json
# after it merges and Pages deploys:
python scripts/release_audit.py --version X.Y.Z --post-release --download --docker \
  --json release-audit/vX.Y.Z/post-release.json
# commit post-release.json (a small follow-up PR)
```

### Reading the audit

- **Checks run concurrently**, one module per area in `scripts/release_checks/`
  (`--jobs`, default 8). A full post-release audit against the live site, GitHub and the
  registry takes under 10 seconds; `--group site,images` narrows it while iterating.
- **Five results.** `PASS`, `FAIL`, `WARN` (needs a disposition in the record), `SKIP`
  (does not apply to this release; says why), `UNAVAILABLE` (could not measure — offline,
  no token, `--download`/`--docker` not given, or not published yet). **UNAVAILABLE is never a
  pass.** Exit `0` = every applicable check passed or warned; `1` = a STOP check failed;
  `2` = nothing failed but something went unmeasured.
- **AUTOMATED vs MANUAL.** Items below marked `A…` are run by `release_audit.py` (the ID is
  the check's ID). Items marked `M…` need a person, a real machine, or judgement; each gets
  a row in the release record with `PASS`, `FAIL`, `N/A` (with the reason), `NOT RUN` (with
  the reason) or `ACCEPTED` (a known failure the sign-off explicitly accepts). A21.01 fails
  the post-release audit while any manual ID in this file has no row.
- **Evidence** goes in `release-audit/vX.Y.Z/`: `record.md` (scope, manual results, sign-off)
  and the audit's JSON output per stage. The JSON files are write-once, like eval results —
  a re-run is a new file, never an edit (CI's `eval-artifacts` job enforces it).

### Tools

| Tool | What it does |
|---|---|
| `scripts/release_audit.py` | The automated checks, by stage. `--list` prints the registry |
| `scripts/check_packaged_sidecar.py` | Launches the engine inside an installed/mounted/extracted build with an isolated data directory, checks its token gate, version and git SHA, and with `--journey` drives a run through both gates to an exported, verified bundle. CI runs it on the `.deb`, AppImage and `.msi`; people run it on the published installers |
| `scripts/sync_version.py` | Derives the version carriers from `VERSION`; `--tag` is the release workflows' guard |
| `scripts/check_packaged_upgrade.py`, `scripts/make_upgrade_fixture.py` | Upgrade a populated older desktop data directory with a packaged engine and record what happened (currently wired to the v2.1.0 fixture — see Phase 19) |
| `release-audit/compose.published-images.yml` | Runs the **published** images on the full-stack topology, on separate volumes |
| `release-audit/historical-references.json` | Every reviewed version mention in user-facing text (A1.09) |

---

## What a release consists of

### Artifacts

| Artifact | Produced by | Platforms | Name |
|---|---|---|---|
| macOS installer | `desktop.yml` on the tag | Apple Silicon (arm64) **only** — no Intel build | `Research.Assistant_X.Y.Z_aarch64.dmg` |
| Windows installer | `desktop.yml` | x64 | `Research.Assistant_X.Y.Z_x64_en-US.msi` |
| Linux AppImage | `desktop.yml` | x86-64 | `Research.Assistant_X.Y.Z_amd64.AppImage` |
| Linux package | `desktop.yml` | x86-64 (Debian/Ubuntu) | `Research.Assistant_X.Y.Z_amd64.deb` |
| Checksums | `desktop.yml` | — | `SHA256SUMS` (served names, dots not spaces) |
| API image | `release.yml` | linux/amd64, linux/arm64 | `ghcr.io/adityamhaske/multi-agent-research-assistant-api:X.Y.Z`, `:X.Y`, `:latest` |
| Worker image | `release.yml` | linux/amd64, linux/arm64 | `…-worker:X.Y.Z`, `:X.Y`, `:latest` |
| Frontend image | `release.yml` | linux/amd64, linux/arm64 | `…-frontend:X.Y.Z`, `:X.Y`, `:latest` |
| GitHub Release | both workflows, appending | — | `vX.Y.Z`; body = hand-written summary + both appended sections |
| Public site | `pages.yml` on `main` | — | <https://adityamhaske.github.io/Multi-Agent-Research-Assistant/> |

`bundle.targets: "all"` also makes an NSIS `.exe` and an `.rpm`; the release job does not
publish them, and nothing offers them. No Linux arm64 or Intel macOS build exists; nothing
may claim one.

### Version carriers

| Where | Holds | Kept in step by |
|---|---|---|
| `VERSION` | `X.Y.Z` — the only place a human edits | — |
| `backend/app/main.py` `APP_VERSION` | `/health`, OpenAPI | `sync_version.py` (A1.02) |
| `desktop/tauri.conf.json` `version` | installer file names | `sync_version.py` (A1.02) |
| `desktop/Cargo.toml` `version` | the Rust crate | `sync_version.py` (A1.02) |
| `frontend/lib/releases.ts` newest entry | releases page, download page, landing page | `sync_version.py` (A1.02), A1.04-A1.06 |
| `desktop/Cargo.lock` `research-desktop` | the lock | `cargo update -p research-desktop` (A1.03) |
| `docs/project/37-changelog.md` heading | the changelog | by hand (A1.07) |
| `backend/research_engine/_build.py` | `/api/v1/version`, Settings → About | `stamp_build.py` at build time, never committed (A6.02, A10.05) |
| git tag, GitHub Release, asset names, image tags | the release | the tag (A1.12, A1.13, A11.x, A10.x) |
| `frontend/package.json`, `desktop/package.json`, `backend/research_engine/pyproject.toml` | `0.1.0` — **not carriers**: private, published nowhere, read by nothing | A1.08 fails the day something reads one |

### Workflows

| Workflow | Trigger | Publishes |
|---|---|---|
| `ci.yml` | push to `main`, PRs | nothing; `backend`, `frontend`, `golden-e2e`, `One version, everywhere`, `Eval results are write-once` are required |
| `desktop.yml` | push to `main`, PRs, `v*` tags | on a tag: installers + `SHA256SUMS` to the Release; `Sidecar ×3`, `Shell ×3` required |
| `release.yml` | `v*.*.*` tags; manual dispatch (images only, never `latest`) | images; creates the Release |
| `pages.yml` | push to `main` touching `frontend/`, `docs/` | the public site |

---

## Release STOP conditions

The release **stops** — no tag, no flip PR, or a patch release — if any of these holds.
Every one is either an automated STOP check (exit code 1) or a manual row marked `FAIL`.

**Build and tests**
- A required CI job failed, was skipped, or passed only on a re-run nobody explained (A3.01, A3.02, M3.01).
- `main` no longer requires one of the eleven release-critical checks (A3.03).
- A committed eval result was modified, or a quality-affecting change ships with no new eval and no waiver (A2.03).

**Versions**
- Any version carrier disagrees with `VERSION`, including `Cargo.lock` (A1.01-A1.03).
- The tag does not name `VERSION`, is not on `main`, or its tree disagrees with itself (A1.12, A1.13; `sync_version.py --tag` also refuses it in both workflows).
- User-facing text names an unreviewed version, or a version newer than this release (A1.09, A1.10).
- The releases entry is downloadable before its installers exist, or still unreleased after the flip (A1.06).

**Artifacts**
- Any of the four installers or `SHA256SUMS` is missing, extra, misnamed, has a space in its name, or is under its size floor (A11.03).
- A checksum does not match GitHub's digest or the downloaded bytes (A11.05, A11.06).
- An asset was not uploaded by the tag's own Desktop run (A11.04).
- An image is missing, lacks an architecture, `latest` is not this release, or was built from another commit (A10.01-A10.03).
- A running image or packaged engine reports the wrong version or git SHA (A10.05, A6.02, M7.06, M8.05, M9.01).

**Platforms**
- A macOS download is reported as "damaged", fails `codesign --verify --deep --strict`, or Gatekeeper gives anything but a policy verdict (A6.02, M7.03, M7.04).
- Any installer fails to install, launch, start its engine, or complete the critical journey on its platform (Phases 7-9, 20).
- The packaged engine is missing, undersized, or crashes (A6.02, M6.02).

**Website and docs**
- The live site offers a stale release, a download link that does not answer 200, or a file name the release does not have (A14.01, A15.01-A15.03).
- The releases page and GitHub disagree about which releases exist (A16.02).
- GitHub Pages is not serving `main` (A17.01, A17.02).
- Documentation or the README describes behaviour that does not ship, or omits a known limitation (M12.x, M13.01, M21.02).
- A published measurement is not backed by a committed result (A1.14).

**Security and upgrade**
- A secret-shaped string is tracked, an env file is tracked, or an artifact carries one (A18.01, A18.02, M18.03).
- An open code-scanning alert or open high/critical dependency alert (A18.05).
- A migration fails, the chain has more than one head, or an upgrade loses data (A19.01, M19.02, M19.03).
- A previous release's bundles stop verifying (M19.05).

**Process**
- The release record does not account for every merged PR or every manual check, or is not signed off (A2.01, A21.01).

---

## Phase 0 — Release Scope Freeze

**Why.** A release is a set of changes someone decided to ship. Without a written scope,
"what is in vX.Y.Z" is answered by whatever happened to merge — which is how features ship
undocumented and fixes ship unannounced.

| ID | Automated check | Stages |
|---|---|---|
| A0.01 | `release-audit/vX.Y.Z/record.md` exists, its title names the version, it has a Scope section | pre-tag → post-release |

- [ ] **M0.01** Create the release record.
  - Verify: `cp release-audit/TEMPLATE.md release-audit/vX.Y.Z/record.md`; fill version, previous release, release manager, target date.
  - Expected: A0.01 passes.
  - Evidence: the record itself.
  - STOP if: work starts on the release without a record.
- [ ] **M0.02** Freeze the scope: list every feature and fix in the record's Scope table, each with its PR numbers.
  - Verify: `git log --first-parent --oneline vPREV..origin/main` — every merge is either in scope or explicitly deferred.
  - Expected: A2.01 passes once the release commit exists.
  - Evidence: the Scope table.
  - STOP if: anything merged that nobody can place in or out of scope.
- [ ] **M0.03** Choose the version number and record why: major for a breaking change (API contract, bundle format a previous verifier refuses, removed feature, data migration that cannot be downgraded), minor for a feature, patch for fixes only.
  - Evidence: one line in the record.
  - STOP if: a breaking change ships in a patch or minor release.
- [ ] **M0.04** Carry forward known limitations: start this release's `known` from the previous release's, and remove an item only with evidence it is fixed.
  - Evidence: the record's Known issues section, with the removed items and their evidence.
  - STOP if: a known limitation disappears from the notes without a fix.

## Phase 1 — Repository / Version Consistency

**Why.** Nine carriers repeat the version, three ship to users under it, and they have
drifted: `/health` said 1.0.0 through the whole 1.0.x line; `Cargo.lock` sat one release
behind for a whole patch line; a tag pushed ahead of its bump would have published
`2.1.0` installers under `v3.0.0`.

| ID | Automated check | Stages |
|---|---|---|
| A1.01 | `VERSION` holds a semantic version and it is the one being released | all |
| A1.02 | The four derived carriers agree with `VERSION` (`sync_version.py`) | all |
| A1.03 | `desktop/Cargo.lock` pins `research-desktop` at `VERSION` | all |
| A1.04 | `releases.ts` is newest-first, one entry per version, v-prefixed, ISO-dated | all |
| A1.05 | This release's entry has a headline, `improved`, `improvedSummary`, and `known` + `knownSummary` (empty `known` is a WARN to confirm) | all |
| A1.06 | Pre-tag: entry is `unreleased: true`. Post-release: it is not, and its date is the tag's | pre-tag → post-release |
| A1.07 | The changelog has `## vX.Y.Z — unreleased` (pre-tag) / `— <date>` matching `releases.ts` (post-release), with a **Known** block | pre-tag → post-release |
| A1.08 | The private package manifests stay non-carriers: nothing reads a package version | all |
| A1.09 | Every line of user-facing text that names a version is in `release-audit/historical-references.json` with a reason; no stale entries | all |
| A1.10 | No user-facing text names a version newer than this release | all |
| A1.11 | Pre-tag: the working tree is clean and `HEAD` is `origin/main` | pre-tag |
| A1.12 | Pre-tag: the tag does not exist. After: it exists on origin, annotated, same commit locally | pre-tag → post-release |
| A1.13 | The tagged tree is on `main`, every carrier in it says `X.Y.Z`, and its entry was `unreleased: true` at tag time | published → post-release |
| A1.14 | Every "NN.N% citation support" claim in the README, docs and site data equals a committed eval result | all |

"User-facing text" (A1.09) is the README, `deploy/README.md`, every published doc except the
changelog, the frontend's TypeScript (site and app, not tests), and the two workflows that
write release notes. `releases.ts` and the changelog are version histories by design.

- [ ] **M1.01** Bump and derive, in this order: `VERSION`; the new `releases.ts` entry at the top with `unreleased: true` (`--write` matches by position); `python scripts/sync_version.py --write`; `cargo update -p research-desktop`; changelog heading `— unreleased`.
  - Expected: `python scripts/sync_version.py` reports "consistent across 4 files"; A1.01-A1.07 pass.
  - Evidence: the release PR.
  - STOP if: any carrier was edited by hand instead of derived.
- [ ] **M1.02** Search for stale references the scanner cannot see: images and screenshots with text in them, the OpenGraph image, hard-coded download or release URLs, image tags in docs.
  - Verify: `git grep -nE "vPREV|PREV_VERSION" -- ':!docs/project/37-changelog.md' ':!frontend/lib/releases.ts' ':!release-audit'`; `git grep -n "releases/download/"`; `git grep -nE "ghcr.io/[^ ]+:[0-9v]"`; open `frontend/app/(site)/opengraph-image.tsx`.
  - Expected: every hit is intentional history or derived at build time.
  - Evidence: the commands and a one-line disposition per hit.
  - STOP if: a user-facing surface presents an old version, URL or tag as current.
- [ ] **M1.03** Review every line A1.09 flags, one by one. Add each to `release-audit/historical-references.json` with a reason that says why it is still true, or fix the line.
  - Expected: no bulk acceptance — a reason like "reviewed" is not a reason.
  - STOP if: a reference is accepted that presents a superseded version as current.

## Phase 2 — Feature Completeness

**Why.** Code existing is not a feature shipping. A feature is shipped only when
implementation, tests, UI/API integration, desktop integration (where applicable), docs,
the public site (where applicable) and the release notes all agree. The desktop has twice
shipped controls that 404'd because the second host was forgotten (AGENTS.md, "two hosts,
one contract").

| ID | Automated check | Stages |
|---|---|---|
| A2.01 | Every PR merged to `main` since the previous tag appears (`#N`) in the record | pre-tag → post-release |
| A2.02 | Every `since:` in `frontend/lib/features.ts` names a released version ≤ this one | all |
| A2.03 | If a quality-affecting path changed since the previous tag (prompts, graph, routing, retrieval, tools, claims), a new committed eval result exists or the record carries an `Eval waiver:` line | pre-tag → post-release |

- [ ] **M2.01** Fill the feature matrix in the record for every scope row: Implementation · Tests · UI · API · Desktop · Docs · Website · Release notes · Known limitations · Status. Status is `Shipped` only when every applicable column is ✓; otherwise `Partial` (with what is missing) or `Deferred`.
  - Evidence: the matrix.
  - STOP if: a row is presented as shipped in the notes while `Partial`.
- [ ] **M2.02** For every feature on both hosts, confirm the desktop really has it: the route exists and behaves (`backend/tests/workflow/test_host_parity.py` covers registration only), or the docs say it is server-only by design.
  - Verify: exercise the feature on the packaged desktop build (Phase 7) and on the published images (Phase 10).
  - STOP if: a control ships on the desktop that 404s, 500s or does nothing.
- [ ] **M2.03** Read the `releases.ts` entry and the changelog entry against the matrix: `improved` states user-visible effects only; `known` lists every Partial row and every carried-forward limitation; each summary compresses its list and adds or softens nothing (`releases.ts` header rules).
  - STOP if: a known limitation is missing or softened.
- [ ] **M2.04** If A2.03 fails: run the release evaluation (`docs/developers/08-testing-and-evaluation.md`, "The release run") with an independent judge and commit the new result write-once — or write `Eval waiver: <reason>` in the record if the change provably cannot alter output.
  - STOP if: citation support < 0.95 or completion < 0.90 under an independent judge on a release that changed prompts or models.

## Phase 3 — Automated Testing

**Why.** CI is the floor, not the gate: the release needs proof that the *release commit*
passed, that the checks are still required, and that nothing passed only by luck.

| ID | Automated check | Stages |
|---|---|---|
| A3.01 | The `CI` run on the release commit (push to `main`) passed `backend`, `frontend`, `golden-e2e`, `One version, everywhere`, `Eval results are write-once`; the migration round-trip and test steps ran and passed (not skipped) | pre-tag → post-release |
| A3.02 | The `Desktop` run on the release commit passed all six build jobs; the `Pages` run passed | pre-tag → post-release |
| A3.03 | The `main` ruleset still requires all eleven release-critical checks | pre-tag → post-release |

### Test matrix

| Suite | Command | Purpose | In CI | Required before release |
|---|---|---|---|---|
| Backend lint/format | `cd backend && ruff check app/ research_engine/ tests/ evals/ && ruff format --check …` | style, bugbear | `backend` | yes (A3.01) |
| Backend unit/integration | `cd backend && python -m pytest` (task/, dataflow/, workflow/, security/, parity/) | behaviour, host parity, layer boundaries, security | `backend` | yes (A3.01) |
| Migration gate | `pytest tests/workflow/test_migration_round_trip.py tests/task/test_migration_downgrade_policy.py tests/workflow/test_desktop_column_sync.py` against pgvector | upgrade **and** downgrade on a populated DB; fails on any skip | `backend` | yes (A3.01) |
| v2.1.0 → current desktop upgrade | `pytest tests/workflow/test_v2_1_0_desktop_upgrade.py` | a real older install opens and keeps its data | `backend` | yes |
| Frontend lint/types/unit | `cd frontend && npm run lint && npm run typecheck && npm test` | components, site data, download page rules | `frontend` | yes (A3.01) |
| Four CI greps | `ci.yml` "Markdown safety" and "Token hygiene" steps, with GNU grep | banned HTML escape hatches, hex colours, backend URLs, web storage | `frontend` | yes |
| Three builds | `npm run build`, `npm run build:desktop`, pages-copy `build:pages` | each target compiles its own branch of `next.config.ts` | `frontend` | yes |
| Golden E2E | `cd frontend && npm run e2e` (Playwright: `golden`, `gates`, `run-journey`) | real browser through both gates, rework, dropped connection | `golden-e2e` | yes (A3.01) |
| Packaged sidecar ×3 OS | `desktop.yml` sidecar smoke steps | the frozen engine: token gate, git SHA, journey, verifier, V3 invariants | `Sidecar (…)` | yes (A3.02, A6.02) |
| Packaged installers | `desktop.yml` shell steps + `scripts/check_packaged_sidecar.py` | engine inside the `.app`, `.deb`, AppImage, `.msi`; DMG signature | `Shell (…)` | yes (A6.02) |
| Image identity | `release.yml` "The pushed image reports the commit that built it" | stamped images, both arches | tag only | yes (A11.09, A10.05) |
| Release audit (offline) | `python scripts/release_audit.py --stage ci` | this document's per-commit invariants | `One version, everywhere` | yes |
| Release audit tests | `pytest tests/workflow/test_release_audit.py` | every historical failure planted and caught | `backend` | yes |
| Dependency audit | `pip-audit`, `npm audit --audit-level=critical` | known CVEs | non-blocking steps | reviewed (M3.02) |
| Code scanning | CodeQL | static analysis | on push/PR | yes (A18.05) |
| Real-model release eval | `python -m evals.harness --judge <independent>` | citation support ≥ 0.95, completion ≥ 0.90 | no | when A2.03 requires |
| Packaged upgrade | `scripts/check_packaged_upgrade.py` | a populated older install, upgraded by the frozen engine | no | when A19.02 warns |
| UI QA | `frontend/e2e/uiqa.mjs` | offline screenshots, no backend | no | no |

- [ ] **M3.01** Explain every re-run: any required job on the release commit that passed only on a retry is recorded with its cause (a flake, an environment race per AGENTS.md "Not every red `main` is a red commit", or a real defect).
  - STOP if: a failure was re-run away without a cause.
- [ ] **M3.02** Read the non-blocking dependency-audit output of the release commit's CI run.
  - Verify: the `Dependency audit` steps of the `backend` and `frontend` jobs.
  - Expected: no critical finding in a dependency the release actually ships; anything else noted.
  - STOP if: a critical, exploitable vulnerability ships unacknowledged.

## Phase 4 — Backend / API Verification

**Why.** The API is a contract two clients (web, desktop) and third parties depend on.

- [ ] **M4.01** If `backend/app/api/` changed since the previous release, `docs/reference/34-api.md` and `35-sse.md` describe the new behaviour, and the contract hash changed only when the surface did.
  - Verify: `git diff --stat vPREV..HEAD -- backend/app/api backend/desktop/sidecar.py`; on the running stack, `GET /api/v1/version` → `contract_version`.
  - STOP if: a route changed shape with no doc change, or a desktop route diverged from the server's contract.
- [ ] **M4.02** On the published images (Phase 10 stack), probe the boundaries: an unauthenticated `GET /api/v1/projects` answers 401; a wrong password answers 401 without saying whether the account exists; `GET /health` reports `X.Y.Z`; `GET /health/ready` is 200; `GET /api/v1/version` reports the tag's commit (A10.05).
  - Evidence: the four responses.
  - STOP if: any differs.

## Phase 5 — Frontend Verification

**Why.** Three build targets share one codebase and each compiles out the others' branches;
CI proves they compile, not that they render.

- [ ] **M5.01** On the Phase 10 stack, open dashboard, a project, a finished run (report, evidence, citations), Settings (Models, Agents, About) in light and dark mode with the browser console open.
  - Expected: no uncaught errors, no failed `/api` requests other than deliberate ones, Settings → About shows `X.Y.Z` and the short commit.
  - STOP if: a page errors, or About reports `unknown` on a published image.
- [ ] **M5.02** Keyboard-only pass over the two gates: plan approval and report approval are reachable and operable without a mouse.
  - STOP if: a gate cannot be approved from the keyboard.

## Phase 6 — Desktop Application Verification

**The desktop is a separate product.** A source checkout has every package the PyInstaller
spec excludes, so a green source suite says nothing about the bundle — and this repository
has shipped a 5 MB app with no engine, every V2 route 500ing in the packaged app, and seven
releases of a "damaged" Mac app, all with CI green. **A desktop row is satisfied only by a
test of the packaged artifact**; source-checkout evidence is recorded separately and never
counts.

| ID | Automated check | Stages |
|---|---|---|
| A6.01 | The tag's `Desktop` run passed every job, `Publish release` included | published → post-release |
| A6.02 | Every packaged-app guard step ran and passed on the tag's run: the tag guard and stamp on all three OSes; frozen-engine SHA, journey and verifier on all three; the engine inside the `.app` reports the commit; the DMG's app is validly signed and Gatekeeper gives a policy verdict; the installed `.deb`, the AppImage and the installed `.msi` each run a journey and report the commit. A guard absent from the tag's workflow is a WARN the record must note | published → post-release |
| A6.03 | Every workflow guard a past incident added is still in the workflows (the list is in `scripts/release_checks/workflows.py`) | all |
| A6.04 | `tauri.conf.json` bundles the engine as `sidecar/`, signs the whole macOS bundle (`signingIdentity: "-"`), builds all targets | all |

- [ ] **M6.01** Record the artifact table in the record for all four installers: file name · SHA-256 · OS · architecture · version (from the installed app) · git SHA (from the engine) · install result · launch result · journey result.
  - Evidence: the table; SHA-256 values match `SHA256SUMS`.
  - STOP if: any cell is blank without a `NOT RUN` reason.
- [ ] **M6.02** On every platform, run the packaged-engine checker against the **installed** copy of the **published** installer:
  - Verify: `python scripts/check_packaged_sidecar.py --search <install dir> --expect-sha <tag commit> --expect-version X.Y.Z --journey`
  - Expected: `"result": "PASS"`, `tree_mb` well above 60, `git_sha` the tag's commit.
  - Evidence: the JSON output (`--json`).
  - STOP if: FAIL on any platform.
- [ ] **M6.03** Mark every desktop row in the record as *packaged* or *source*. A row satisfied only by source evidence is `NOT RUN`, not `PASS`.

## Phase 7 — macOS Verification

Apple Silicon only (`aarch64.dmg`, built on `macos-latest`). The build is ad-hoc signed as a
whole bundle but **not** Developer ID signed or notarized, so the expected first launch of a
downloaded copy is a Gatekeeper block that the documented command clears — never "damaged".

- [ ] **M7.01** Download the `.dmg` from the release in a browser (so it carries the quarantine flag) and verify it.
  - Verify: `shasum -a 256 -c SHA256SUMS --ignore-missing`; `xattr -p com.apple.quarantine Research.Assistant_X.Y.Z_aarch64.dmg`.
  - Expected: `OK`; a quarantine value present.
  - STOP if: checksum mismatch.
- [ ] **M7.02** The DMG opens and holds the app at the right version.
  - Verify: `hdiutil attach -nobrowse -readonly <dmg>`; `defaults read "/Volumes/Research Assistant/Research Assistant.app/Contents/Info.plist" CFBundleShortVersionString`; `du -sh` the app.
  - Expected: the app and an Applications link; version `X.Y.Z`; ~180 MB, not ~5 MB.
  - STOP if: missing app, wrong version, or undersized.
- [ ] **M7.03** The signature is whole and valid.
  - Verify: `codesign -dv --verbose=2 <app>`; `codesign --verify --deep --strict --verbose=2 <app>`.
  - Expected: flags `adhoc` without `linker-signed`, `Sealed Resources` present; "valid on disk" and "satisfies its Designated Requirement".
  - STOP if: `linker-signed`, or verification fails — this is the "damaged" defect.
- [ ] **M7.04** Gatekeeper judges a quarantined copy as policy, not damage.
  - Verify: `ditto <app> /tmp/q.app && xattr -w com.apple.quarantine "0081;$(printf %x $(date +%s));Safari;" /tmp/q.app && spctl --assess --type execute -vv /tmp/q.app`.
  - Expected: `rejected` (not notarized) — a policy verdict.
  - STOP if: anything else.
- [ ] **M7.05** The bundled engine is present, native, and unmodified by hardened runtime.
  - Verify: `file "<app>/Contents/Resources/sidecar/research-sidecar"`; `codesign -dv` on it.
  - Expected: `Mach-O 64-bit executable arm64`; plain `flags=adhoc` (hardened runtime on the engine breaks library validation — AGENTS/memory trap).
  - STOP if: missing, wrong architecture, or `runtime` flag set.
- [ ] **M7.06** The packaged engine identifies itself and completes the journey.
  - Verify: `python3 scripts/check_packaged_sidecar.py --search <mounted app> --expect-sha <tag commit> --expect-version X.Y.Z --journey`.
  - Expected: PASS.
  - STOP if: FAIL.
- [ ] **M7.07** First launch as a user: drag to Applications; open it *without* the command and confirm the block is the unidentified-developer kind; run `xattr -dr com.apple.quarantine "/Applications/Research Assistant.app"`; open it.
  - Expected: the window opens; no "damaged" dialog at any point; the demo banner or onboarding appears; Settings → About shows `X.Y.Z` and the tag's short commit.
  - STOP if: "damaged", a crash, or a blank window.
- [ ] **M7.08** The Phase 20 desktop journey on macOS (M20.02).
- [ ] **M7.09** Quit the app; no engine is left running.
  - Verify: `pgrep -fl research-sidecar` after quitting.
  - Expected: nothing.
  - STOP if: an orphaned engine (it holds the data directory and a port).

## Phase 8 — Windows Verification

x64 `.msi` only; unsigned, so SmartScreen warns. **A compiled MSI is not a tested MSI**: CI
now installs it silently and drives the engine it installed (A6.02), but the GUI, SmartScreen
and a real user profile are only seen on a real machine.

- [ ] **M8.01** Download the `.msi` in a browser; verify it.
  - Verify: PowerShell `Get-FileHash .\Research.Assistant_X.Y.Z_x64_en-US.msi -Algorithm SHA256` against `SHA256SUMS`.
  - STOP if: mismatch.
- [ ] **M8.02** SmartScreen shows the unknown-publisher warning; **More info → Run anyway** proceeds, exactly as the download page says.
  - STOP if: any other block, or the documented steps do not work.
- [ ] **M8.03** Install completes; Start-menu entry exists; Settings → Apps shows version `X.Y.Z`; files under `C:\Program Files\Research Assistant\` including `sidecar\research-sidecar.exe`.
  - STOP if: install fails or the version is wrong.
- [ ] **M8.04** Launch: the window opens without a crash; Task Manager shows `research-sidecar.exe`; no firewall prompt (the engine binds 127.0.0.1 only).
  - STOP if: crash, blank window, or an inbound-firewall prompt.
- [ ] **M8.05** `python scripts\check_packaged_sidecar.py --search "C:\Program Files\Research Assistant" --expect-sha <tag commit> --expect-version X.Y.Z --journey` passes.
  - STOP if: FAIL.
- [ ] **M8.06** The Phase 20 desktop journey on Windows (M20.02), from a user whose profile path has a space; exports save where the dialog says.
- [ ] **M8.07** Local storage: data under `%USERPROFILE%\.research-engine`; provider keys in Windows Credential Manager, not in a file.
  - STOP if: a key is written to disk in plain text.
- [ ] **M8.08** Quit: `research-sidecar.exe` exits (the watchdog — two Windows-only crashes lived here, #113).
  - STOP if: an orphaned engine.
- [ ] **M8.09** Uninstall from Settings → Apps: the Program Files directory is removed; user data remains (as documented).
  - STOP if: uninstall fails or leaves the engine behind.

## Phase 9 — Linux Verification

x86-64 AppImage and `.deb` (Debian/Ubuntu). CI installs the `.deb`, unpacks the AppImage and
drives each engine (A6.02); the GUI is seen only on a desktop session.

- [ ] **M9.01** AppImage: download, verify (`sha256sum -c SHA256SUMS --ignore-missing`), `chmod +x`, launch from a desktop session.
  - Expected: window opens; engine starts; Settings → About shows `X.Y.Z` and the commit; the M20.02 journey completes.
  - STOP if: it does not start (note FUSE requirements if the host lacks `libfuse2`, and whether the docs say so).
- [ ] **M9.02** `.deb`: `sudo apt install ./Research.Assistant_X.Y.Z_amd64.deb` on a clean supported Ubuntu LTS resolves its dependencies and installs; the app launches from the menu; the M20.02 journey completes.
  - STOP if: unresolvable dependencies or launch failure.
- [ ] **M9.03** Key storage uses the Secret Service keyring; on a session without one, the app says so rather than storing keys in a file.
  - STOP if: plain-text key storage.
- [ ] **M9.04** `sudo apt remove research-assistant` removes the application; user data remains; no engine left running.
  - STOP if: removal fails or leaves the engine running.

## Phase 10 — Docker / Container Verification

Three images, two architectures each, pushed by digest and stitched into multi-arch tags.
**`latest` moves only on a version tag.** Verify the published images, not a local build.

| ID | Automated check | Stages |
|---|---|---|
| A10.01 | `api`, `worker`, `frontend` exist at `X.Y.Z` and `X.Y`, each with `linux/amd64` and `linux/arm64` | published → post-release |
| A10.02 | `latest` has the same digest as `X.Y.Z` (skipped when a newer release exists) | published → post-release |
| A10.03 | Every image's provenance attestation records `vcs:revision` = the tag's commit, per architecture | published → post-release |
| A10.04 | The documented deploy path (`deploy/oracle-bootstrap.sh`, `deploy/docker-compose.demo.yml`) defaults to `latest` or this version — never a moving tag like `edge` | all |
| A10.05 | With `--docker`: the pulled `api` image reports `APP_VERSION` = `X.Y.Z` and `git_sha` = the tag's commit (the image is stamped) | published → post-release |

- [ ] **M10.01** Run the published images on the full-stack topology, on their own volumes:
  - Verify: `RELEASE_TAG=X.Y.Z FRONTEND_PORT=3041 LLM_MODE=fake docker compose -p release-check -f docker-compose.full.yml -f release-audit/compose.published-images.yml up -d --no-build`
  - Expected: all five services healthy; the api log shows `alembic upgrade head` completing; `curl localhost:3041/api/v1/version` via the frontend proxy reports the tag's commit.
  - Evidence: `docker compose ps`, the version response.
  - STOP if: a service is unhealthy or migrations fail.
- [ ] **M10.02** On that stack: register, log in, create a project, run a fake-mode research through both gates, export `.md`, `.pdf` (WeasyPrint is in the server image — must be 200) and `.bundle.json`; verify the bundle.
  - STOP if: any step fails.
- [ ] **M10.03** On an arm64 host (Apple Silicon Docker or the Ampere target), the same stack starts from the same tags.
  - STOP if: `exec format error` or any service fails.
- [ ] **M10.04** Tear down with `down -v` using the same flags; the developer's own `mara_full_*` volumes are untouched.

## Phase 11 — GitHub Release Verification

| ID | Automated check | Stages |
|---|---|---|
| A11.01 | The Release exists, is not a draft, is a prerelease exactly when the version has a suffix, and its title names the version | published → post-release |
| A11.02 | GitHub's `releases/latest` is this tag (Settings → About's update check reads it) | published → post-release |
| A11.03 | Exactly the four installers and `SHA256SUMS`, served names (no spaces), each above its size floor | published → post-release |
| A11.04 | Every asset was uploaded by `github-actions[bot]` during the tag's own Desktop run | published → post-release |
| A11.05 | `SHA256SUMS` lists exactly the installers and every hash equals GitHub's stored digest | published → post-release |
| A11.06 | With `--download`: every installer, downloaded, hashes to its `SHA256SUMS` line | published → post-release |
| A11.07 | The body carries both appended sections, `:X.Y.Z` (never `:vX.Y.Z`) pull lines for all three images, the macOS command, and the checksum instruction | published → post-release |
| A11.08 | The tag's source archive downloads | published → post-release |
| A11.09 | The tag's `Release` run passed every job: six builds, three manifests, the release (and, from the release after 3.0.1, the stamp job) | published → post-release |

- [ ] **M11.01** Add the hand-written summary at the top of the Release body (what changed for users, the macOS first-launch line, a link to the changelog's Known section) and read the whole body as a user would.
  - STOP if: the body claims something Phases 6-10 did not verify, or omits the known limitations link.

## Phase 12 — Documentation Verification

**Why.** `docs/` is the build contract and is published verbatim; a doc describing
behaviour that does not ship is a false claim on the public site.

| ID | Automated check | Stages |
|---|---|---|
| A12.01 | Every relative link in `docs/` and the README resolves to a file; every site-absolute link is a real route | all |
| A12.02 | The download page, both desktop guides and the release body give the identical macOS first-launch command | all |

- [ ] **M12.01** For each scope row, the docs describe what shipped — on both hosts, with desktop differences stated (`docs/getting-started/23-desktop-app.md`).
  - STOP if: a doc describes unshipped or removed behaviour.
- [ ] **M12.02** Configuration: every environment variable added, renamed or removed since the previous release (`git diff vPREV..HEAD -- backend/app/config.py backend/research_engine/local.py .env.example`) is reflected in `.env.example`, `docs/reference/36-configuration.md` and `docs/getting-started/21-configuration.md` — and in **both** config paths (AGENTS.md).
  - STOP if: a documented variable does nothing or an undocumented one is required.
- [ ] **M12.03** Search the docs for removed or renamed features, commands and routes named in the diff (`git diff --stat vPREV..HEAD`) and for old commands (`git grep -n "<old name>" docs README.md`).
- [ ] **M12.04** Architecture docs (`docs/architecture/02`, `04`) match the graph's nodes and gates.
- [ ] **M12.05** Known limitations agree across `releases.ts` `known`, the changelog **Known**, the Release body and the docs that describe the affected feature.
  - STOP if: a limitation appears in one and not the others.

## Phase 13 — README Verification

| ID | Automated check | Stages |
|---|---|---|
| A13.01 | The pipeline diagram names both human gates when the graph has both | all |
| A13.02 | Every absolute link in the README answers (post-release) | post-release |

The README's download badge points at `/download`, which resolves the latest release itself,
so it carries no version (`scripts/sync_version.py` docstring). Relative links are A12.01;
measured numbers are A1.14.

- [ ] **M13.01** Read the README top to bottom against the release: the feature list (nothing unreleased, nothing removed), platforms (Apple Silicon macOS, x64 Windows, x86-64 Linux — nothing broader), install commands (`./start.sh`, compose — run in Phase 10/20), the configuration table against `docs/reference/36`, Makefile targets that exist, known-limitation wording on measurements.
  - STOP if: the README promises something the release does not do.

## Phase 14 — Landing Page Verification

Check the **deployed** site, never only the source.

| ID | Automated check | Stages |
|---|---|---|
| A14.01 | Live `/` says "New in vX.Y.Z" and its structured data says `softwareVersion: vX.Y.Z` | post-release |
| A14.02 | Every internal link and asset on `/`, `/why/`, `/docs/`, `/download/`, `/releases/` answers; a `_next/` asset (the `.nojekyll` incident) and the favicon (the `basePath` incident) are among them | post-release |
| A14.03 | `robots.txt` allows crawling; `sitemap.xml` names the site URL | post-release |

- [ ] **M14.01** View `/` at desktop width and at 375 px, light and dark: hero, download call-to-action, "New in" link to `/releases#vX.Y.Z`, feature cards, navigation, footer.
  - STOP if: a stale version, a broken layout, or a feature presented that does not ship.
- [ ] **M14.02** `/why`: every comparison claim (`frontend/lib/comparison.ts`) still holds for this release.

## Phase 15 — Download Page Verification

**Release-critical.** It built its URLs from a naming convention, and once pointed every
button at the site's own `/releases` page for weeks.

| ID | Automated check | Stages |
|---|---|---|
| A15.01 | Live `/download` pre-selects `X.Y.Z` and links exactly this release's four installer URLs | post-release |
| A15.02 | Every version in the selector has all four installers and its source archive answering 200 (older versions too) | post-release |
| A15.03 | The file names the page builds (`download/page.tsx`) are exactly the names the release publishes | all |

- [ ] **M15.01** On each OS (or with a UA override), the detected-OS card leads; the big button and every card button point at the `X.Y.Z` asset for that platform; the macOS card's command copies exactly; each platform's steps match what Phases 7-9 saw; the size note ("~80 MB download, ~180 MB installed") is within 15% of the published sizes.
  - STOP if: any button leads to an old version, a wrong architecture or a 404.
- [ ] **M15.02** Download one installer by clicking the page's button in a real browser; the file name and checksum are right.

## Phase 16 — Releases Page Verification

| ID | Automated check | Stages |
|---|---|---|
| A16.01 | Live `/releases` leads with `vX.Y.Z` and links its GitHub Release | post-release |
| A16.02 | The set of versions on the site equals the set of GitHub Releases | published → post-release |
| A16.03 | Each entry's date is its tag's date (WARN for history; FAIL for this release) | published → post-release |

- [ ] **M16.01** View `/releases`: the new entry is first with the tag's date; its summaries are shown and the lists fold open; the version index jumps to each entry; earlier releases are intact.

## Phase 17 — GitHub Pages / Deployment Verification

`main` being correct has never meant Pages is: the deploy is path-filtered, cancellable and
retried separately (`pages.yml`).

| ID | Automated check | Stages |
|---|---|---|
| A17.01 | The latest `github-pages` deployment succeeded and its commit is `origin/main` | post-release |
| A17.02 | The live `/build.json` names that commit and version `X.Y.Z` (sites built before `pages.yml` wrote it: WARN) | post-release |

- [ ] **M17.01** If A17.01 fails because `main` moved after the flip, wait for the newer deploy and re-run; if the deploy itself failed, re-run the **workflow** (never only the deploy job — "Artifact count is 2").

## Phase 18 — Security / Configuration Verification

| ID | Automated check | Stages |
|---|---|---|
| A18.01 | No secret-shaped string (AWS, GitHub, OpenAI/Anthropic-style, Google, Tavily, Slack, private keys) in any tracked file; placeholders that say so are ignored | all |
| A18.02 | No env file but `.env.example` is tracked | all |
| A18.03 | The desktop WebView's `connect-src` reaches only its own engine | all |
| A18.04 | In the full stack only the frontend publishes a port | all |
| A18.05 | No open code-scanning alert; no open high/critical Dependabot alert | pre-tag → post-release |

- [ ] **M18.01** Review `git diff vPREV..HEAD` for debug flags, test accounts, credentials, private URLs, and anything that widens a boundary.
- [ ] **M18.02** If `backend/app/config.py`, the security middleware, auth, or the SSRF guard changed: re-check CORS (`FRONTEND_URL`), CSP, cookie flags, JWT lifetimes and refresh rotation, rate-limit defaults, BYOK encryption (`ENCRYPTION_KEY`), `ENVIRONMENT=production` disabling `/docs`, and `enforce_ssrf_guards` on the server path.
  - STOP if: a default got less safe without a documented reason.
- [ ] **M18.03** No secret or env file ships in an artifact.
  - Verify: `grep -rEal 'sk-[A-Za-z0-9]{20}|AIza[0-9A-Za-z_-]{35}|tvly-[A-Za-z0-9]{20}' <engine dir>`; `find <engine dir> -name '.env*'`; `docker run --rm --entrypoint sh <api image> -c 'ls -a /app; test ! -e /app/.env'`.
  - Read every hit with `grep -aoE '<pattern>' <file>` before judging it: compiled string
    tables produce look-alikes (3.0.1's engine matched `sk-typemathbackground…` inside
    `primp.abi3.so`, a run-together keyword table, not a key).
  - STOP if: any hit is a real credential, or an env file ships.
- [ ] **M18.04** Public surface: `/api/v1/version` is unauthenticated on the server by design; nothing else new is.

## Phase 19 — Upgrade / Migration Verification

| ID | Automated check | Stages |
|---|---|---|
| A19.01 | The Alembic chain has exactly one head | all |
| A19.02 | Declares new migrations, ORM model changes and bundle-format changes since the previous tag (WARN when any: the manual checks below become required) | pre-tag → post-release |

Alembic reporting success is not evidence that data survived. When A19.02 warns:

- [ ] **M19.01** Fresh install: an empty database migrates to head (CI), and a fresh desktop data directory starts (M6.02 does it).
- [ ] **M19.02** Server upgrade from the previous release: run the previous release's images (`RELEASE_TAG=PREV` with the compose override) with a populated database — a project, completed and gate-waiting runs, a session, a stored BYOK key, preferences, custom agent instructions — then switch to `X.Y.Z` and restart.
  - Expected: migrations apply once; everything is present; the waiting run can be approved; old research re-exports and its bundle verifies; login still works (or the forced re-login is documented).
  - STOP if: data is lost or a waiting run cannot complete.
- [ ] **M19.03** Desktop upgrade from the previous release: install the previous release, create the same data, install `X.Y.Z` over it; same expectations. `scripts/check_packaged_upgrade.py` automates this for a v2.1.0 fixture; for another previous version, generate its fixture with `scripts/make_upgrade_fixture.py` (currently hard-wired to v2.1.0 — see Remaining gaps in the v3.0.1 record).
- [ ] **M19.04** Downgrade: CI's round-trip proves the schema reverses; record whether running the previous images against the upgraded database is supported for this release.
- [ ] **M19.05** A bundle exported by the previous release verifies with this release's verifier, unchanged (`python -m research_engine.verify_bundle <old bundle>`), and a new bundle states its format version.
  - STOP if: an old bundle stops verifying.

## Phase 20 — Final End-to-End Production Smoke Test

Run the product the way a user does, on the **published** artifacts, once per host.

The journey: install → launch → configure a provider → authenticate (web) → create a project
→ ask a research question → planner → design (plan) gate → approve → research → evidence →
critic → synthesis → review gate → approve → final report → inspect citations → export
(`.md`, `.pdf` on the server, `.bundle.json`) → verify the bundle offline → follow-up chat
where supported (project chat on the server; per-report chat on research recorded as
sessions).

- [ ] **M20.01** The web/self-hosted journey on the Phase 10 stack, **with a real provider at least once** (fake mode proves the mechanism, not the product). Record the model routing used.
  - STOP if: any step fails.
- [ ] **M20.02** The desktop journey on each platform (M7.08, M8.06, M9.01/M9.02), with a real provider or Ollama.
  - STOP if: any step fails on any platform.
- [ ] **M20.03** Negative paths on the published build: an invalid provider key is refused before it is stored; a run cancelled mid-flight stays cancelled; a report sent back for rework resumes at the synthesizer and is approvable on the second pass; refreshing the browser mid-run resumes the live feed; restarting the worker while a run waits at a gate still lets it be approved; a bundle edited by one byte fails `verify_bundle`.
  - STOP if: any behaves otherwise.
- [ ] **M20.04** Every `[n]` in the final report resolves on hover to a source and its snippet; an unresolved one renders the ⚠ chip, never a clean citation.
  - STOP if: a citation renders clean without resolving — the product's P0 class.

## Phase 21 — Release Approval

| ID | Automated check | Stages |
|---|---|---|
| A21.01 | The record has a row for every `M…` ID in this file, none `FAIL` or `PENDING`, and the sign-off is checked (WARN at `published`, FAIL at `post-release`) | published → post-release |

- [ ] **M21.01** Every WARN and UNAVAILABLE in the published audit has a written disposition in the record.
- [ ] **M21.02** Known issues are documented everywhere they belong (M12.05), including anything this audit found and the release accepted.
- [ ] **M21.03** The release manager signs the approval block in the record. Only then is the flip PR opened.

## Phase 22 — Post-Release Verification

| ID | Automated check | Stages |
|---|---|---|
| A22.01 | The release record is on `origin/main` | post-release |

Every `post-release` check in Phases 13-17 runs here, and the Phase 1, 10 and 11 checks run
again against what is now public.

- [ ] **M22.01** The flip PR: drop `unreleased`, set the entry's `date` to the tag's date, date the changelog heading, commit `record.md` and `published.json`. Merge with a merge commit.
- [ ] **M22.02** After Pages deploys: run the post-release audit with `--download --docker`, commit its JSON (write-once) in a small follow-up PR.
- [ ] **M22.03** Load `/`, `/why`, `/docs`, `/download`, `/releases` on a phone and a desktop browser with the cache disabled.
- [ ] **M22.04** In an installed copy of the **previous** desktop release, Settings → About → *Check for updates* reports `X.Y.Z` available.
  - STOP (patch release) if: it does not.
- [ ] **M22.05** For 48 hours, watch issues and discussions for install or launch reports; any release-blocking report starts a patch release through this same process.
- [ ] **M22.06** Every incident found during this release becomes a check: an `A…` check (preferred) or an `M…` item, plus a row in the incident table below, in the PR that fixes it.

---

## Negative and failure-injection coverage

The release does not only test happy paths. Where each release-critical failure is exercised:

| Failure | Where it is exercised |
|---|---|
| Invalid / missing authentication | `tests/security/test_auth_rate_limit.py`, `test_artifact_authorization.py`; desktop token gate in `desktop.yml` and `check_packaged_sidecar.py` (401 without the token) |
| Expired / reused refresh token | `tests/security/test_refresh_token_reuse.py` — rotation, family revocation on reuse, expiry; added with this process, because the README advertised reuse detection and nothing tested it |
| Invalid provider key | `tests/security/test_provider_health.py`; M20.03 |
| Provider failure, quota, timeout | `graph.py` surfaces the provider's message (AGENTS.md); `tests/dataflow/test_citation_verification.py` and neighbours; eval judge excludes unjudged claims (`tests/task/test_eval_judge.py`) |
| Malformed model response | `tests/dataflow/test_prompt_override_snapshot.py`, the critic's fail-closed tests (`test_evidence_snippet_verification.py`) |
| Missing evidence, invalid or broken citation | `tests/dataflow/test_evidence_snippet_verification.py`, `test_citation_verification.py`; M20.04 |
| Conflicting evidence | `tests/dataflow/test_contradictions.py` |
| Cancellation, including the late-outcome race | `tests/workflow/test_cancellation_is_authoritative.py` |
| Approval rejection and rework | `frontend/e2e/gates.spec.ts` ("a rejected draft is resynthesized…"); `tests/security/test_audit_log_semantics.py` |
| Dropped connection / refresh during a run | `frontend/e2e/gates.spec.ts` ("recovers from a dropped connection…"), `tests/workflow/test_desktop_stream_reconnect.py`, `test_stream_replay_rules.py` |
| Restart while waiting at a gate | `tests/workflow/test_plan_gate.py`, `test_engine_runner.py` (resume from a durable checkpoint); M20.03 (worker restart on the published stack) |
| SSRF, untrusted fetches | `tests/security/test_ssrf_guard.py` |
| Missing or undersized engine in a bundle | `desktop.yml` size floors; A11.03 installer floors; `check_packaged_sidecar.py --min-tree-mb` |
| Engine crash / missing server config in the bundle | `tests/workflow/test_desktop_runs_without_server_env.py`, `test_sidecar_startup.py`; packaged journeys (A6.02) |
| Invalid or tampered bundle | `tests/workflow/test_bundle_v2_verifier.py`, `test_bundle_export_routes.py`; M20.03 |
| Wrong checksum, space in a name, missing or extra asset | `tests/workflow/test_release_audit.py` (planted); A11.03, A11.05, A11.06 |
| Stale artifact (not from the tag's run) | A11.04; A10.03 (image provenance) |
| Wrong or unstamped git SHA | `desktop.yml` SHA steps; `release.yml` image step; A10.05; `check_packaged_sidecar.py` negative control |
| Invalid migration, multiple heads, downgrade | `tests/workflow/test_migration_round_trip.py`, `tests/task/test_migration_downgrade_policy.py`; A19.01 |
| Stale version text, future version, stale reviewed reference | `tests/workflow/test_release_audit.py` (planted); A1.09, A1.10 |

---

## Historical incidents and the checks they became

| Release | What shipped broken (CI green) | Now caught by |
|---|---|---|
| 1.0.x | `/health` and OpenAPI said 1.0.0 through the whole 1.0.x line | `sync_version.py`, A1.02 |
| 1.0.1 | The desktop crate was about to publish `…_0.1.0_aarch64.dmg` under a 1.0.1 tag | `sync_version.py --tag` in both workflows, A1.13, A6.03 |
| 1.0.1 | `SHA256SUMS` listed names with a space; GitHub serves them with a dot; verification said "no file was verified" | rename step (A6.03), A11.03, A11.05 |
| 1.0.x | The Pages site 404'd its favicon at the domain root (`basePath` does not cover `metadata.icons`) | A14.02 |
| 1.0.x | A Pages retry after an outage failed with "Artifact count is 2" | split build/deploy (A6.03), M17.01 |
| 1.0.x | Jekyll dropped `_next/` — every stylesheet and script | `.nojekyll` (A6.03), A14.02 |
| 2.0.0 | The two workflows overwrote each other's release body; notes never mentioned the images | `append_body` (A6.03), A11.07 |
| 2.0.0 | Every run route on the packaged app answered 500; excluded packages imported at request time | packaged journeys in `desktop.yml`, A6.02 |
| 2.0.0 | A duplicate project name threw 500 on desktop, 409 on server | host parity tests; M2.02 |
| ≤2.0.1 | Release notes told people to `docker pull …:v2.0.1`, a tag that never existed | `IMAGE_TAG=${GITHUB_REF_NAME#v}` (A6.03), A11.07 |
| 1.x-2.0 | `deploy` bootstrap defaulted to `latest` before any release; the fix defaulted to `edge` and left it there, deploying a 5 August pre-1.0 build after 3.0.1 shipped | A10.04 (fixed in the release-process change) |
| early | The shell job raced the sidecar job: a 5 MB bundle with no engine passed CI | `needs: sidecar`, size floors (A6.03, A11.03) |
| 2.0.2 | `Cargo.lock` sat at 2.0.1 through the 2.0.2 line | A1.03 |
| 2.0.2 | The download button pointed at the site's own `/releases`, not an installer | A15.01 |
| 2.0.2 | The download card said "macOS" for an Apple Silicon-only build, and claimed "any laptop" | M15.01, "What a release consists of" |
| 2.x | The README diagram showed one human gate for weeks after the design gate shipped | A13.01 |
| 2.x | The README advertised a citation-support figure its linked result did not contain | A1.14 |
| #113 | Two Windows-only engine crashes (watchdog, logging) invisible to Ubuntu-only CI | installed-`.msi` journey (A6.02), M8.04, M8.08 |
| 3.0.0 | The site could offer a version before its installers existed | two-stage release, `unreleased` (A1.06, A1.13) |
| 1.0.1-3.0.0 | Every macOS build was only linker-signed; every download was "damaged", and the documented Open Anyway steps never worked | `signingIdentity: "-"` (A6.04), DMG signature step (A6.02), M7.03, M7.04, A12.02 |
| ≤3.0.1 | The `.deb`, AppImage and `.msi` were never installed or launched by CI — only compiled | installer steps in `desktop.yml` (A6.02, A6.03) |
| ≤3.0.1 | Every published api/worker image answered `/api/v1/version` with `unknown` — nothing stamped them | `release.yml` stamp job + image step (A6.03, A11.09), A10.05 |
| ≤3.0.1 | Nothing on the live site said which commit it was built from | `pages.yml` `build.json` (A6.03), A17.02 |
| every | Features and fixes merged with no record of whether they were meant to ship | A0.01, A2.01, M2.01 |

---

## Maintaining this document

- **IDs are stable.** `A…` IDs are check IDs in `scripts/release_checks/`; `M…` IDs are rows
  in every release record. Never renumber; retire an ID by deleting it and its check, and add
  new ones at the end of their phase.
- **The document and the script agree.** `backend/tests/workflow/test_release_audit.py`
  fails if an automated check is missing from this file or this file names one the script
  does not have.
- **An incident becomes a check in the PR that fixes it** — an automated check where a
  machine can see it, a manual item where only a person can, and a row in the table above.
- **Keep it true.** A step that no longer matches the workflows is worse than no step,
  because it is trusted (AGENTS.md).

---

## Release approval (sign-off)

Copied into every `release-audit/vX.Y.Z/record.md` from `release-audit/TEMPLATE.md`:

```text
Version:            vX.Y.Z
Commit:             <tag commit>
Tag:                vX.Y.Z (annotated)
Release manager:    <name>

Automated checks    [ ] pre-tag PASS   [ ] published PASS   [ ] post-release PASS
Desktop             [ ] macOS PASS     [ ] Windows PASS     [ ] Linux PASS
Web                 [ ] Landing PASS   [ ] Download PASS    [ ] Releases PASS   [ ] Docs PASS
Distribution        [ ] GitHub Release PASS   [ ] Docker PASS   [ ] Checksums PASS
Security            [ ] PASS
Upgrade/migration   [ ] PASS
Critical journey    [ ] web PASS   [ ] desktop PASS
Known issues        [ ] documented everywhere they belong
- [ ] **Release approved**
```

The release is complete only when every required item is checked and A21.01 passes.
