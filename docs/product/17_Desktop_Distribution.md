# 17. Desktop Distribution and First Run

> **Status:** specification, not yet built. Nothing here is claimed as shipped.
> **Scope:** turn the existing desktop build into something a stranger can download and
> succeed with, on macOS, Windows and Linux.
> **Decision:** Option B — release pipeline + first-run experience. Auto-update is
> designed for and deliberately deferred (§8).

## 1. Why this exists

The desktop app is built. The on-ramp is not.

A stranger who somehow obtained the `.dmg` today would clear a Gatekeeper warning, land in
an application with no API key, no guidance, and no way to see the product work. Demo mode
exists but is reachable only by setting `LLM_MODE=fake` in an environment variable, which
is not a thing a non-technical user does.

This document specifies the smallest scope that closes that gap.

## 2. What is already built

Verified against the tree on 2026-08-14, not carried over from prior claims.

| Capability | State | Evidence |
|---|---|---|
| Tauri shell, sidecar spawn, loopback token auth | Built | `desktop/src/`, `backend/desktop/sidecar.py` |
| Per-provider BYOK in the OS keychain | Built | `frontend/components/account/DesktopKeysCard.tsx` |
| Server-side BYOK, Fernet-encrypted per user | Built | `app/services/crypto.py`, `users.api_key_encrypted` |
| PyInstaller sidecar bundle | Built, **138 MB** | `backend/desktop/research-sidecar.spec`, measured `backend/dist/` |
| CI builds `.dmg` / `.msi` / AppImage on 3 OSes | Built | `.github/workflows/desktop.yml` |
| Demo mode (scripted models, fixture retrievers) | Built, **not reachable from the UI** | `research_engine/fakes.py`; no `LLM_MODE` reference anywhere in `frontend/` |
| Publishing bundles to GitHub Releases | **Missing** | `desktop.yml` uses `upload-artifact` with `retention-days: 14`, and has no tag trigger |
| First-run / onboarding UI | **Missing** | zero matches for onboarding/welcome/first-run/wizard under `frontend/` |
| Code signing / notarization | **Missing** | no signing secrets in `desktop.yml`, no certificate config in `tauri.conf.json` |
| Auto-update | **Missing** | no updater plugin in `desktop/Cargo.toml`, no `updater` key in `tauri.conf.json` |

The sidecar carries **no PyTorch and no sentence-transformers** — its heaviest dependency
is numpy. "Runs on modest hardware" is therefore already true, provided the reasoning
happens through an API key rather than a local model.

## 3. Corrections required before anything ships

[`12_Launch_Plan.md`](12_Launch_Plan.md) marks three things ✅ under M9 that do not exist:

- **line 479** — "Signed and notarized for macOS and Windows"
- **line 480** — "Auto-update against GitHub Releases"
- **line 483** — a DoD asserting a fresh machine installs "from a released artifact", and
  **line 486** — "auto-update moves n−1 → n successfully"

[`AGENTS.md`](../../AGENTS.md) requires that docs contradicting shipped code be fixed in the
same PR that changed the behaviour. These predate this work, so they are corrected as
**step zero of Phase 1**, independent of which phases follow. A launch plan that overstates
readiness is the same class of defect as a benchmark reporting numbers it never measured.

## 4. What a stranger actually needs

The product has four external dependencies. Only one is mandatory, and that distinction is
the entire basis of the first-run design.

| Need | Required? | Free path | Consequence if absent |
|---|---|---|---|
| **Reasoning model** | **Yes** | Ollama (local, free) or a provider free tier | Nothing runs |
| **Web search** | For web research | **DuckDuckGo — no key** (`Tavily → Brave → DDG` chain) | Falls back automatically; corpus mode unaffected |
| **Embeddings** | Only for corpus mode and project memory | Ollama `nomic-embed-text` | Web research still works; corpus upload fails loudly |
| **Database** | Yes | SQLite, bundled | — |

The headline for onboarding copy: **a model key is the only thing a user must obtain.**
Search works keyless. The database is not their problem. This must be stated plainly on
first run, because the default assumption about a research tool is a wall of required keys.

## 5. Phase 1 — Release pipeline

**Goal:** a permanent, public download link.

1. **Fix the three false claims** in `12_Launch_Plan.md` (§3).
2. **Add a tag trigger** (`v*`) to `desktop.yml` alongside the existing branch/PR runs.
3. **Publish on tag:** attach `.dmg`, `.msi`, `.AppImage` and `.deb` to a GitHub Release.
   The existing 14-day artifacts stay for PR debugging; releases are permanent.
4. **Emit `SHA256SUMS`** alongside the bundles. Unsigned software that also cannot be
   verified is worse than unsigned software that can.
5. **Apple Silicon ad-hoc signature — ✅ resolved 2026-08-14, measured.** An arm64 binary
   will not execute without at least an ad-hoc signature. Both halves of the bundle were
   checked on an arm64 Mac rather than assumed:

   | Artifact | `codesign -dv` | Executes |
   |---|---|---|
   | PyInstaller sidecar (`backend/dist/research-sidecar`) | `Signature=adhoc`, `flags=0x2(adhoc)` | ✅ |
   | `rustc -O` arm64 binary (Tauri's toolchain) | `Signature=adhoc`, `flags=0x20002(adhoc,linker-signed)` | ✅ |

   The Rust linker applies the signature automatically, which is the mechanism Tauri's
   build relies on, and PyInstaller does the same for the sidecar. **arm64 can ship.** A
   full `.app` check on a clean machine remains the ideal final confirmation, but the
   mechanism is verified and there is no longer reason to expect a failure.

**DoD:** a tag produces a Release with four artifacts and a checksum file; each is
downloaded on a clean machine of its OS and launches to the app window.

## 6. Phase 2 — First run

**Goal:** a stranger reaches a working research report without reading anything.

### 6.1 Demo first, key second

On first launch the app opens **directly into a completed demo session** — a real report
produced by the scripted models, with citations that resolve — so the product's core claim
is visible in the first ten seconds rather than described.

Demo mode becomes a **first-class runtime state**, not an environment variable:

- Selectable in the UI, and the default when no key is configured.
- A persistent, unmissable banner while active.
- Leaving demo mode is a single action from that banner.

**Demo content lives in `research_engine/demo_fixtures.py`, not `fakes.py`.** The first
seed shipped the *test* fixtures — "A citable fact [1]" citing "Fixture Source 1" at
`example.com` — because a demo run is just `llm_mode="fake"`. A stranger's first ten
seconds were placeholder data making the product's headline claim.

Two rules hold that module honest:

- **Snippets are verbatim, fetched from the URL they are attributed to.** The UI presents
  a snippet as the quote supporting a claim, so an invented snippet under a real DOI is a
  fabricated citation — the precise failure this product exists to prevent. Re-fetch when
  editing; never paraphrase.
- **Every claim is grounded in the snippet it cites**, carrying no number absent from it,
  so the graph's own citation-fidelity pass leaves the draft untouched.
  `tests/test_demo_fixtures.py` enforces both.

Selection is `RunConfig.demo`, a separate flag from `llm_mode`, which stays `"fake"`.
A third `llm_mode` value would fail *open*: every `llm_mode == "fake"` comparison in the
engine gates a no-network guard, and one missed comparison would send a demo run to a
real provider. As a flag, the worst case is a demo showing test filler.

### 6.2 Demo output must never be mistakable for research

This is the **P0 constraint**, and it follows from the project's own invariant: the product
claims verifiable output, so a demo artifact that could pass as a real one is a correctness
bug, not a cosmetic one.

- Demo sessions are marked **in the database**, not merely in component state.
- Every export path — `.md`, `.pdf`, `.bundle.json` — carries the stamp.
- `verify_bundle` reports demo provenance as a **first-class field**, not a footnote.
- The stamp derives from the persisted flag, so a demo report cannot be laundered into a
  real-looking artifact by any route that bypasses the UI.

### 6.3 Connect a model

A wizard reachable from the demo banner:

- **Ollama** — detected live if reachable, offered first, labelled free. Lists the tags
  actually installed (`app/services/local_llm.py` already probes them).
- **Provider key** — pasted, then **validated against the provider** before storage. A key
  is never written to the keychain until it has answered a real request; storing an
  unvalidated key just relocates the failure into the middle of the user's first run.
- **Free-tier links** per provider, so "now go buy an API key" is never the dead end.

Search and embedding keys are presented as **optional**, with their consequences stated
(§4). They must not render as required fields.

**DoD:** on a clean machine with no keys, a non-technical user launches the app, reads a
demo report with resolving citations, connects a model, and completes a real research run —
without a terminal, and without documentation.

## 7. Phase 3 — Install page and docs

- A download page that detects the visitor's OS and shows **that OS's** unblock steps
  inline, with screenshots. macOS is the one that genuinely needs it:
  System Settings → Privacy & Security → Open Anyway.
- Per-OS friction, stated honestly rather than glossed:

| OS | What the user hits | Severity |
|---|---|---|
| Windows | SmartScreen → More info → Run anyway | 2 clicks |
| Linux | AppImage: `chmod +x`. `.deb`: nothing | Trivial |
| **macOS** | Blocked; System Settings → Open Anyway | **Real friction** |

- The in-app docs site (`/docs`) renders `docs/**/*.md` automatically, so this document and
  the install guide appear there with no extra wiring.

## 8. Non-goals

- **Auto-update.** Tauri's updater signs with minisign, which is free and unrelated to
  Apple's $99, so cost is not the blocker. The unknown is whether Gatekeeper re-blocks an
  unsigned `.app` after an in-place replacement. That question deserves its own cycle
  rather than holding up the first download link. Nothing in Phases 1–3 may preclude it.
- **Code signing.** The $99/yr Apple Developer Program is the only real fix for macOS
  friction. Deferred, not dismissed; revisit if Mac friction measurably blocks adoption.
- **OAuth sign-in.** Anthropic and OpenAI do not offer OAuth for third parties to obtain
  API access on a user's behalf, and Google's OAuth path is Vertex AI rather than the AI
  Studio key used here. **OpenRouter's PKCE flow is the only genuinely feasible option** —
  and since OpenRouter proxies the others, it is the sensible one-click path if pursued.
  Its current spec must be verified before any design depends on it.

## 8a. Design notes for the remaining Phase 2 work

Written before implementation, because both decisions are the kind where the wrong choice
means rework. Measured 2026-08-14.

### The seeded demo session — generate on first launch

Three options were considered: freeze a pre-built session into the bundle, generate one at
release time as a build artifact, or generate it live on first launch. The first two were
attempts to avoid a first-launch latency cost that **does not exist**:

| Measurement | Result |
|---|---|
| Pipeline alone, fake mode (`cli --fake`) | **0.04 s** |
| Full API start → approval gate, via Celery and Postgres | **0.67 s** |

An earlier estimate of ~40 s was wrong. It came from a session whose recorded
`elapsed_seconds` of 42.6 was almost entirely the *human gate wait* — the operator polling
and then approving — not work. The figure was quoted twice before anyone measured it.

**Decision: generate on first launch.** At sub-second cost it beats both alternatives on
every axis that matters:

- Always matches the shipped pipeline, prompts and citation format, because it *is* the
  shipped pipeline. A frozen bundle rots silently and nobody regenerates it before a
  release.
- No release-pipeline step, so no new build failure mode and no stale demo baked into a
  bad build.
- **No ID rewriting.** A pre-baked session would carry a `user_id` and `project_id` that do
  not exist until first boot. Creating it through the normal path gets correct IDs for
  free — this was the fiddliest part of the build-artifact option and it disappears.

What still needs care:

- **Seeding must not resurrect a deleted demo.** "No sessions exist" is the obvious trigger
  and it is wrong: it re-creates the demo on every launch after the user deletes it. Needs
  a persisted marker, shared with the first-run dismissal below.
- Generation failure must be non-fatal. A demo that cannot be created is a worse first run
  than no demo, but it is not a reason to refuse to start the app.

### First run — route into Settings, do not build a wizard

A separate key-entry wizard would duplicate the model picker in Settings, and this codebase
has already paid for that pattern once: `map_local_host` existed in three copies and two
were wrong. A second key surface diverges the first time a provider is added or a
validation rule changes.

**Decision: reuse Settings.** But routing a first-time user to Settings as it stands is its
own wall — the page opens with token usage, spending limits and appearance before it
reaches the thing they need. So Settings gains a **first-run layout** (key section pinned,
the rest collapsed) rather than a wizard being born. One component, one validation path.

**The trigger is computed, not stored.** First-run guidance shows when the user has *no
usable model source*: no provider key **and** no reachable local server. That condition is
self-healing — it stops the moment a model exists, it never fires for someone who only ever
uses Ollama, and it cannot desynchronise from reality the way a stored
"has-completed-onboarding" flag would.

**One thing is stored:** an explicit dismissal, so someone who wants to explore first is not
nagged. That same marker is what stops the demo seed from returning after deletion — one
flag, two uses.

## 9. Risks

| Risk | Handling |
|---|---|
| ~~Apple Silicon ad-hoc signature absent~~ | **Closed 2026-08-14** — measured on arm64: both the sidecar and a rustc binary are ad-hoc signed and execute (§5.5) |
| macOS Gatekeeper friction deters users | Screenshotted walkthrough; measure, and revisit signing if it bites |
| Live key validation adds a first-run failure mode | Validation failures must surface the provider's own error, never a generic "invalid key" |
| Demo artifacts escaping as real reports | §6.2 — persisted flag, stamped at every export, surfaced by the verifier |
| Sidecar size (138 MB) on slow connections | Stated on the download page up front; no fix attempted |
