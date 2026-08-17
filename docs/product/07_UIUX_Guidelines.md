# 07. UI/UX Guidelines

> Design system and page-level specs for the Next.js frontend. The aesthetic is a formal,
> crisp **Academic Research-Paper Design System**: high-contrast typography, strict square
> geometry, muted paper surfaces, hairline rules, and tabular monospace telemetry.

---

## 1. Design System & Tokens

### 🏛️ Typography Architecture

Typography is split strictly into three distinct duties: editorial structure, narrative reading, and data telemetry:

| Role | Font Family | Usage Areas |
| :--- | :--- | :--- |
| **Headers & High-Level Titles** | `font-serif` (`"Times New Roman"`, `Times`, `Georgia`, `Cambria`, `serif`) | Page titles (`h1`), section headings (`h2`, `h3`), primary category tags, report headings, modal titles. |
| **Body & Descriptions** | `font-sans` (`Inter`, system-ui, sans-serif) | Body narratives, descriptions, form field labels, assistant chat paragraphs. |
| **System Telemetry, Logs & Code** | `font-mono` (`"JetBrains Mono"`, `SFMono-Regular`, `Consolas`, `monospace`) | Agent IDs, timestamps, cost numbers, token usage, model routes, citation chips, status badges, and data tables. |

---

### 🎨 Structural & Status Color Matrix

All colors are bound to CSS variables defined in `globals.css` with dark mode support (`next-themes` class strategy). Values below are read from the token source, not restated from memory — check `globals.css` `:root` / `.dark` directly before trusting a color number in a review:

| Token | Light Theme | Dark Theme | Purpose & Element Binding |
| :--- | :--- | :--- | :--- |
| `--bg-base` (Paper) | `#FBFBFA` | `#121214` | Root viewport canvas / document paper background |
| `--bg-surface` (Card) | `#FFFFFF` | `#1A1A1E` | Card surfaces, modal surfaces, table backgrounds |
| `--bg-elevated` | `#F2F2EF` | `#242428` | Interactive hover states, secondary backgrounds |
| `--border` (Strict Rule) | `#D1D1CD` | `#2E2E34` | Hairline borders (1px) for all structural dividers |
| `--text-primary` (Ink) | `#111111` | `#F4F4F6` | Academic titles, primary text, active states |
| `--text-secondary` | `#666662` | `#8E8E93` | Body paragraphs, form labels |
| `--text-muted` | `#8C8C88` | `#707075` | Metadata, helper hints, timestamps |
| `--accent` (Academic Accent) | `#15654A` | `#5FD3A6` | Forest academic accent for active items, focus rings — deepened/brightened from an earlier `#3F5E4D`/`#527A65` that only cleared ~3.9:1 |
| `--accent-muted` | `#E8EFE9` | `#1B2E27` | Active row tints, user chat bubbles |
| `--success` (Status OK) | `#15803D` | `#4ADE80` | Completed states, healthy nodes |
| `--warning` (Status Warn) | `#B45309` | `#FBBF24` | Awaiting review, missing API keys |
| `--danger` (Status Fail) | `#DC2626` | `#F87171` | Exceptions, failed stages, destructive actions |
| `--info` | `#2F52C8` | `#8AA6FF` | "Running"-type badges — deliberately **not** `--accent`, so an in-progress state never reads as ordinary accented chrome |
| `--agent-planner\|executor\|critic\|synthesizer\|hitl` | see `globals.css` | see `globals.css` | One hue per pipeline stage on `PipelineRail`/`LiveFeed`, spread around the wheel so adjacent stages never collide — hue reinforces the rail's numbering, never carries meaning alone |

Every pair above clears WCAG AA (4.5:1) against **both** `--bg-base` and `--bg-surface`, in both themes. Re-audit any pair that moves ground when it changes.

---

### 📏 Spacing, Type & Density Scale

Added in Phase 0 of the researcher-workspace overhaul (`.claude/plans/researcher-workspace-overhaul.plan.md`) once the same "card with a title and a body" turned up with four different padding values across four files. Declared once in `globals.css` `:root` — theme-independent, so (unlike color) they are **not** repeated in `.dark`. Components consume them as CSS custom properties (`style={{ padding: "var(--space-lg)" }}`) or via Tailwind's arbitrary-value syntax (`text-[length:var(--text-micro)]`); they are not registered under `@theme`, so bare Tailwind utilities like `text-sm` still mean Tailwind's own scale, not this one.

| Step | Value | Use |
| :--- | :--- | :--- |
| `--space-3xs` | 2px | Optical nudge between icon and text |
| `--space-2xs` | 4px | Inside a chip |
| `--space-xs` | 8px | Between siblings in a row |
| `--space-sm` | 12px | Dense list padding |
| `--space-md` | 16px | Default gap between controls |
| `--space-lg` | 24px | Card padding, gap between cards |
| `--space-xl` | 40px | Gap between page sections |
| `--space-2xl` | 64px | Page top/bottom breathing room |

| Step | Value | Use |
| :--- | :--- | :--- |
| `--text-micro` | 11px | Mono eyebrows, badges, timestamps |
| `--text-xs` | 12px | Hints, secondary metadata |
| `--text-sm` | 13px | Labels, controls, dense body |
| `--text-base` | 14px | Body |
| `--text-lg` | 18px | Section headings |
| `--text-xl` | 24px | Page title |

Six steps, no more — an arbitrary size that doesn't match one of the above (`text-[0.625rem]` was a recurring offender) should round up to the nearest named step rather than adding a seventh.

`--radius: 0` states the square identity once instead of leaving it implied by scattered `border-radius: 0` declarations. `--density-pad-y`/`--density-pad-x`/`--density-row-gap` default to comfortable and switch to a tighter set under `[data-density="compact"]` on an ancestor — the activity feed and long document lists are the intended compact consumers.

---

### 🧩 Shared Primitives

`components/icons.tsx` is the one icon vocabulary: 24×24 viewBox, 1.75 stroke, square caps and miter joins — no rounded strokes, matching `--radius: 0`. It replaced the SVGs that used to live only inside `SideNav.tsx`, plus the nine emoji section headers `LiveFeed.tsx` used for its expanded detail blocks (💭🎯🔍📋📖🌐📄📚⚖️⚠️📝). The `⚠` chip used for an unresolved citation (`lib/citations.tsx`, `lib/memoryCitations.tsx`) is a separate, deliberately-literal character load-bearing to its own tests — it is not part of this icon set and Phase 0 leaves it untouched.

`components/ui/` holds the primitives that replace the ad-hoc `border border-border bg-bg-surface`, `.badge`, and hand-rolled label patterns found across the app:

| Primitive | Replaces | Notes |
| :--- | :--- | :--- |
| `Card` | `border border-border bg-bg-surface p-*` boxes; the titled-card shape `account/Section.tsx` established | `padding` is `"sm" \| "md" \| "lg"` off the scale above, not a raw Tailwind step |
| `StatusDot` | Hand-assembled `.badge` + `.status-marker` combinations | Color is reinforcement — the label text is always present, never dot-alone |
| `Field` | The label/control/hint block from `account/Section.tsx` | Canonical home outside `account/` for Phase 3's settings IA and later forms |
| `Disclosure` | The dashboard run form's "Options" toggle | Closed state always names its own non-default summary rather than hiding behind a bare arrow |
| `EmptyState` | The `◇` glyph used in the corpus and dashboard empty states | No icon by default — a glyph that carries no meaning is decoration, not replaced by a different one |
| `Toolbar` | `LiveFeed`'s title/meta/actions header row | title (+ meta) left, actions right |

---

### 📐 Geometry & Element Rules

1. **Strict 0px Border-Radius**:
   - `*, *::before, *::after { border-radius: 0; }` enforced globally in `@layer base` — not `!important`, so a component that reaches for Tailwind's `rounded` utility can still defeat it. `LiveFeed.tsx` did exactly that before Phase 0; there is no lint rule catching a stray `rounded` class, only review.
   - Zero rounded corners on buttons, cards, inputs, avatars, badges, chips, progress bars, or modal surfaces.
2. **Status Markers**:
   - Replaced all round dots with uniform **8px × 8px square `.status-marker` blocks**.
   - Card backgrounds remain neutral; saturated color is isolated strictly to the marker.
3. **Operational Logs & Data Tables**:
   - Academic booktabs table style: horizontal top/bottom dividing lines and header rule; zero vertical column dividers.
   - Fixed-width monospace columns for timestamps (`w-16`) and uppercase agent tags (`w-24`).
4. **Citations UX**:
   - Inline superscript badges (`[1]`, `[M1]`, `[?]`) with square borders and monospace font. Hover/tap triggers popovers displaying verbatim supporting snippets.

---

## 2. Information Architecture

```
/                → redirects: authed → /dashboard, else → /login
/login           → login + register (academic segmented switcher)
/dashboard       → new research query, depth selector, airgapped corpus mode, recent sessions
/corpus          → local document upload & corpus stats for airgapped research
/history         → full session history (filter by status, active / archived view, pagination)
/chat            → project memory chat (cross-session search over approved reports)
/session/[id]    → live research session lifecycle (5 distinct states below)
/profile         → display name, user ID, avatar initials
/settings        → redirects to /settings/models; sectioned IA, not one scroll (docs/07 §2 Phase 3):
                   /settings/models       Ollama status + per-role model routing
                   /settings/connections  BYOK key (web) / keychain keys (desktop) + live probe
                   /settings/research     retrieval_k, min_sources_per_task, snippet_max_chars
                   /settings/corpus       links to /corpus — no dedicated settings yet
                   /settings/exports      states current export behaviour — no knobs yet
                   /settings/appearance   theme + density (folded back in from Phase 0's removal)
                   /settings/advanced     token usage + monthly spending limit (web only)
```

**Sidebar Shell**: Collapsible sidebar with square brand logo, active project selector dropdown (`ProjectSwitcher`), a "New Research" button that is the *only* entry point to `/dashboard` (Phase 0 removed the redundant `/dashboard` nav item that duplicated it), unlabeled nav icons for Corpus/History/Chat, and user account popup (`AccountMenu`) — which is also where the light/dark toggle lives now that Settings' standalone Appearance section (a second, redundant place to do the same thing) is gone.

---

## 2b. Project Workspace (docs/07 §2, Phase 6; req 9)

`/project` is the active project as a *place*, not a filter: recent runs, what the corpus
holds, what memory knows, and which models this project's research dials — one view,
reachable from the sidebar's **Overview**. Nav is project-first: Overview · Corpus ·
History · Chat, all scoped to the switcher's selection.

Every panel states its own emptiness instead of rendering a zero. "0 documents" and "we
could not read the corpus" are the same number and different problems, and only one of
them is the user's to fix. The spend figure is labelled "these runs", never "project
total", because it sums the five rows shown.

**In-place document preview.** Corpus rows open a right-hand drawer rather than
downloading: "Open" used to mean "download and switch application", which is the moment a
reader stops checking sources. PDF renders through `<object>` off the download route (the
one kind served `inline`); Markdown through the same `react-markdown` + `remark-gfm`
pipeline reports use; text in a `<pre>`; **HTML in `<iframe sandbox="" srcdoc={…}>`**.

The drawer is a real modal: `aria-modal="true"` is backed by a focus trap, focus returns
to the row or citation that opened it, and Escape closes. The first version claimed
`aria-modal` without trapping — a keyboard user tabbed straight out into a page their
screen reader had been told was inert — which is why `PreviewDrawer.test.tsx` pins the
cycle rather than assuming it.

The sandbox is the boundary, not a sanitizer. `sandbox=""` withholds every capability —
no `allow-scripts`, no `allow-same-origin`, and never both, since together they let a
frame remove its own sandbox. Raw-HTML rendering stays banned in React and CI greps for
it; `components/preview/DocumentPreview.test.tsx` asserts the sandbox attribute and the
inertness of HTML embedded in an uploaded `.md`, because neither regression is visible in
a screenshot.

## 3. Session Page — Core Lifecycle

One page, six states driven by the LangGraph session status:

### 1. PENDING / RUNNING — "Brain Monitor"
- **Pipeline Rail**: Planner → **Plan review** → Executor → Critic → Synthesizer → Review, square 7×7 numbered nodes and hairline connectors. Both review nodes are presentational and derived from `status` — the gates are `interrupt()` checkpoints, not agents, so nothing emits them into the stream. They share `--agent-hitl`: it is the human's hue and both nodes are the same kind of step, with position, number and label carrying the distinction (colour is never the sole carrier).
- **Live Feed**: Monospace log stream with fixed timestamp/agent columns, auto-scroll with pause-on-scroll. An expanded row groups its detail into four sections — **Reasoning · Evidence · Verdict · Draft** — rather than the nine sibling boxes it was. Grouped, not merged: "Evaluation Reasons" and "Critic Feedback For Rework" are different things, and the noise being fixed was the missing hierarchy, not the distinct labels. A group holding nothing renders nothing. The feed carries its own density toggle, which overrides the account preference for this surface only and persists nothing — it is a reading posture for one run, not a setting.
- **Status Bar**: Monospace tabular elapsed time, running cost, and task progress count.
- **SSE Stream**: Connect on mount, replay history first, auto-reconnect with `Last-Event-ID`, and fallback polling.

### 2. AWAITING_PLAN — The Design Gate (docs/07 §2, Phase 4)
- **Split View**: the editable research plan and report structure beside the decision panel, mirroring the draft gate so the two read as one pattern rather than two features.
- **Plan editor**: add / remove / reorder / reword subtopics, and an include toggle per task. Excluding a task removes it from the request entirely, not just flags it — a review whose edits do not reach the executor is a rubber stamp.
- **Outline picker**: four templates (Literature Review, Systematic Comparison, Methods Survey, Custom) fetched from `GET /research/outline-templates`, **never** hardcoded in the component — a copy in TypeScript would silently promise a structure the report never used. Picking one replaces the section list; the sections stay editable afterwards.
- **The pitch**: "the agent picked 6 queries" becomes "these are my six subtopics, in my review's structure" — and it is the last moment before the run spends anything, which is why the panel shows spend-to-date rather than an estimate it cannot honestly make.
- **Opt-out, but only for the app**: the run form's "Review the research plan before searching" defaults to on and sends `skip_plan_gate: false` explicitly. The API's own default is the opposite, so a script that has not been updated keeps today's journey.

### 3. AWAITING_APPROVAL — The Review Gate
- **Split View**: Draft report (rendered academic prose with citations) beside the review decision panel.
- **Decision Panel**: Monospace metrics, source count, rework round budget (`2 of 3 used`), Approve button, and rework feedback textarea.
- **Skeleton Fallback**: Square skeleton placeholder if draft is still streaming.

### 4. COMPLETED — Report & Grounded Follow-up
- **Report View**: Academic typography (`font-serif` title), booktabs tables, source citation popovers, metrics row (duration, cost, tokens, sources), and export actions (Copy, `.md`, `.pdf`, `.bundle.json`).
- **Follow-up Chat**: Square chat card with grounded assistant replies streaming via buffered SSE.

### 5. FAILED — Research Exception
- Square crimson error block, error message reason, partial sources gathered before failure, and "Start new research from this query" restart action.

---

## 3b. One status vocabulary (docs/07 §2, Phase 7)

`lib/status.ts` is the single home for every status label, token and urgency flag. The
badge, the history filters and the session card all derive from it; none restates it.
`Record<SessionStatus, StatusMeta>` makes divergence a type error, which is the point —
the hand-written filter list had already fallen behind the badge (`AWAITING_PLAN` was
missing, so a run parked at the design gate could be seen and not filtered for).

Both human gates share the amber token. To someone scanning a list they are one urgency
class — "waiting on you" — and the *label* says which decision is owed. A hue per gate
would encode a difference in urgency that does not exist, and would spend a sixth
contrast-audited colour saying it.

History filters on status, depth, verified-citation rate and model — separate controls
rather than one row of tabs, since tabs would imply that choosing one clears the others.

The citation bands are `100% verified`, `Under 100%` and **`Not measured`**. The third is
its own band, never folded into the lowest: a report with no citable claims
(`citation_resolution_rate = null`) and one whose every marker is broken (`0`) are
opposite findings, and a band of "under 100%" that quietly swept up nulls would be the
unmeasured-as-zero bug wearing a filter. `SessionCard` shows the percentage only when it
was actually measured, for the same reason.

The model picker offers only routes that appear on the current page, not the whole
catalog — a filter for something that cannot match is a dead control.

## 4. Accessibility & Quality Bar

- **Semantic Landmarks**: Strict `<main>`, `<nav>`, `<header>`, `<aside>`, `<section>` hierarchy with unique IDs and `aria-labelledby`.
- **Keyboard Navigation**: Full keyboard focus visibility with high-contrast `--accent` outline ring.
- **Live Regions**: `aria-live="polite"` on streaming activity feeds and chat messages.
- **Contrast**: WCAG AA compliance across both light (`#FBFBFA`) and dark (`#121214`) palettes.
- **Strict Testing**: Zero TypeScript compilation errors (`tsc --noEmit`), Vitest suite clean across all formatting, citation, SSE, and pipeline tests.
