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
5. **Prove the Apple Silicon ad-hoc signature.** An arm64 binary will not execute without
   at least an ad-hoc signature. Tauri is believed to emit one; this must be **confirmed on
   a clean Mac**, not assumed. If it does not, Phase 1 does not ship arm64.

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

## 9. Risks

| Risk | Handling |
|---|---|
| Apple Silicon ad-hoc signature absent | Prove on a clean Mac in Phase 1; blocks arm64 release if untrue |
| macOS Gatekeeper friction deters users | Screenshotted walkthrough; measure, and revisit signing if it bites |
| Live key validation adds a first-run failure mode | Validation failures must surface the provider's own error, never a generic "invalid key" |
| Demo artifacts escaping as real reports | §6.2 — persisted flag, stamped at every export, surfaced by the verifier |
| Sidecar size (138 MB) on slow connections | Stated on the download page up front; no fix attempted |
