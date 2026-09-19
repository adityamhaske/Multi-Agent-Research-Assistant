# Design: Download Page Enhancements

Date: 2026-09-19
Status: Approved

## Overview
Enhance the `/download` page (`frontend/app/(site)/download/page.tsx`) to support:
1. Version selection across all published desktop releases.
2. Direct download buttons at the bottom of each platform box (macOS, Windows, Linux).
3. Subtle, academic-minimalist styling for buttons and controls with no loud/extra colors.
4. A 4th card explaining how to download and run the localhost Docker stack.

## Context & Constraints
- **Design Tokens**: Follow the repository's academic paper design system in `frontend/app/globals.css`. Buttons must use `btn btn-secondary text-xs font-mono` to be subtle, neutral, and adapt cleanly to light/dark themes (`--surface`, `--line`, `--ink`).
- **Asset URLs**: GitHub release naming convention for desktop assets:
  - macOS: `Research.Assistant_${version}_aarch64.dmg`
  - Windows: `Research.Assistant_${version}_x64_en-US.msi`
  - Linux: `Research.Assistant_${version}_amd64.AppImage` and `Research.Assistant_${version}_amd64.deb`
  - Docker / Source archive: `${REPO}/archive/refs/tags/v${version}.zip` (or fallback to `${REPO}/archive/refs/heads/main.zip`)
- **Published Versions**: Versions with verified desktop installer assets in GitHub releases: `v2.0.2`, `v2.0.1`, `v2.0.0`, `v1.0.2`, `v1.0.1`.
- **Three Frontend Build Targets**: Changes must build cleanly across `npm run build`, `npm run build:desktop`, and `npm run build:pages`.

## Component & UI Details

### 1. Version Selector
- Dropdown placed near the top header of `/download`.
- Options populated from `RELEASES` in `frontend/lib/releases.ts` that have desktop assets.
- Default state: latest release (`v2.0.2`).
- Controlled client-side state: changing the selected version updates the download links across all cards immediately.

### 2. Platform Cards (`PlatformCard`)
- Each card receives the active version and displays the corresponding download button(s) at the bottom:
  - **macOS**: `Download .dmg · v{version}`
  - **Windows**: `Download .msi · v{version}`
  - **Linux**: Two subtle buttons side by side: `Download .AppImage · v{version}` and `Download .deb · v{version}`
  - **Docker / Localhost**: `Download Source (.zip)` and `Docker Deployment Guide →`
- All buttons use `btn btn-secondary text-xs` with subtle hover states and no vibrant accent colors.

### 3. Docker / Localhost Platform Card
- Rendered in the same container card grid/stack matching macOS, Windows, and Linux.
- **Title**: `Docker / Localhost` &nbsp;`port 3031`
- **Badge**: `CONTAINERIZED` (`severity: "none"`)
- **Steps**:
  1. Clone the repository (`git clone https://github.com/adityamhaske/Multi-Agent-Research-Assistant.git`) or download the source `.zip`.
  2. Run `./start.sh` (or `docker compose -f docker-compose.full.yml up --build`).
  3. Open `http://localhost:3031` in your browser.
- **Note**: "Runs the complete stack (API, worker, Next.js frontend, Postgres with pgvector, and Redis) isolated in Docker."
- **Buttons**:
  - `Download Source (.zip)` (downloads archive for selected version)
  - `Docker Guide →` (links to `/docs/deployment/docker`)

## Verification Plan
1. `npm test` in `frontend` (ensure unit tests pass).
2. `npm run build` in `frontend` (standalone server build).
3. `npm run build:pages` in `frontend` (static export build).
4. `npm run build:desktop` in `frontend` (desktop static export build).
5. Visual check via local dev server to ensure subtle button styling, version switching, and Docker box look crisp in both light and dark mode.
