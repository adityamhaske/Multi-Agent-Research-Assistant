# Download Page Enhancements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Provide version selection, subtle bottom buttons on every platform box, and a Docker localhost card on `/download`.

**Architecture:** Update `frontend/app/(site)/download/page.tsx` with controlled version state derived from `lib/releases.ts`, dynamic asset URL computation, card button rows, and Docker platform card. Verify across all three frontend build targets.

**Tech Stack:** Next.js 16, React 19, TypeScript, TailwindCSS v4, Vitest, Testing Library.

## Global Constraints
- Buttons at the bottom of platform boxes must use subtle styling (`btn btn-secondary text-xs font-mono`) with no extra/vibrant colors.
- Must preserve all existing comments, invariants, and pass all 3 frontend builds (`build`, `build:pages`, `build:desktop`).
- Asset URLs must match the GitHub release conventions:
  - macOS: `Research.Assistant_${version}_aarch64.dmg`
  - Windows: `Research.Assistant_${version}_x64_en-US.msi`
  - Linux: `Research.Assistant_${version}_amd64.AppImage` and `Research.Assistant_${version}_amd64.deb`
  - Source archive: `${REPO}/archive/refs/tags/v${version}.zip`

---

### Task 1: Add Unit Tests for Download Page Functionality
**Files:**
- Create: `frontend/app/(site)/download/page.test.tsx`

- [ ] **Step 1: Write test cases**
Verify version selector rendering, platform cards, subtle button classes, and asset URLs.

- [ ] **Step 2: Run test to observe baseline**

### Task 2: Implement Version Selector, Card Buttons, and Docker Card
**Files:**
- Modify: `frontend/app/(site)/download/page.tsx`

- [ ] **Step 1: Update `page.tsx`**
Implement state for selected version, dropdown selector, updated `PlatformCard` with subtle bottom buttons, and `docker` platform entry.

- [ ] **Step 3: Run unit tests**
Run `npm test` in `frontend` to verify all tests pass.

### Task 3: Multi-Target Build and Visual Verification
**Files:**
- Modify/Verify: `frontend`

- [ ] **Step 1: Run typecheck**
`npm run typecheck`
- [ ] **Step 2: Run server build**
`npm run build`
- [ ] **Step 3: Run pages build**
`npm run build:pages`
- [ ] **Step 4: Run desktop build**
`npm run build:desktop`
- [ ] **Step 5: Run dev server locally & verify visual presentation**
