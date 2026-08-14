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

All colors are bound to CSS variables defined in `globals.css` with dark mode support (`next-themes` class strategy):

| Token | Light Theme | Dark Theme | Purpose & Element Binding |
| :--- | :--- | :--- | :--- |
| `--bg-base` (Paper) | `#FBFBFA` | `#121214` | Root viewport canvas / document paper background |
| `--bg-surface` (Card) | `#FFFFFF` | `#1A1A1E` | Card surfaces, modal surfaces, table backgrounds |
| `--bg-elevated` | `#F2F2EE` | `#222226` | Interactive hover states, secondary backgrounds |
| `--border` (Strict Rule) | `#D1D1CD` | `#2E2E34` | Hairline borders (1px) for all structural dividers |
| `--text-primary` (Ink) | `#111111` | `#F4F4F6` | Academic titles, primary text, active states |
| `--text-secondary` | `#444440` | `#B0B0B8` | Body paragraphs, form labels |
| `--text-muted` (Muted Ink) | `#666662` | `#8E8E93` | Metadata, helper hints, timestamps |
| `--accent` (Academic Accent) | `#3F5E4D` | `#527A65` | Forest academic accent for active items, focus rings |
| `--accent-muted` | `#E8EFEA` | `#1C2E24` | Active row tints, user chat bubbles |
| `--success` (Status OK) | `#10B981` | `#10B981` | Completed states, healthy nodes |
| `--warning` (Status Warn) | `#F59E0B` | `#F59E0B` | Awaiting review, missing API keys |
| `--danger` (Status Fail) | `#EF4444` | `#EF4444` | Exceptions, failed stages, destructive actions |
| `--badge-block-bg` | `#EAEAE6` | `#242428` | Technical tag frames, code chips |

---

### 📐 Geometry & Element Rules

1. **Strict 0px Border-Radius**:
   - `*, *::before, *::after { border-radius: 0 !important; }` enforced globally.
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
/corpus          → local document upload & chunk telemetry for airgapped research
/history         → full session history (filter by status, active / archived view, pagination)
/chat            → project memory chat (cross-session search over approved reports)
/session/[id]    → live research session lifecycle (5 distinct states below)
/profile         → display name, user ID, avatar initials
/settings        → monthly token usage, spending limits, BYOK keys, local Ollama models, role model routing
```

**Sidebar Shell**: Collapsible sidebar with square brand logo (`§`), active project selector dropdown (`ProjectSwitcher`), primary navigation tabs, and user account popup (`AccountMenu`).

---

## 3. Session Page — Core Lifecycle

One page, five states driven by the LangGraph session status:

### 1. PENDING / RUNNING — "Brain Monitor"
- **Pipeline Rail**: Planner → Executor → Critic → Synthesizer with square 7×7 numbered nodes and hairline connectors.
- **Live Feed**: Monospace log stream with fixed timestamp/agent columns, auto-scroll with pause-on-scroll.
- **Status Bar**: Monospace tabular elapsed time, running cost, and task progress count.
- **SSE Stream**: Connect on mount, replay history first, auto-reconnect with `Last-Event-ID`, and fallback polling.

### 2. AWAITING_APPROVAL — The Review Gate
- **Split View**: Draft report (rendered academic prose with citations) beside the review decision panel.
- **Decision Panel**: Monospace metrics, source count, rework round budget (`2 of 3 used`), Approve button, and rework feedback textarea.
- **Skeleton Fallback**: Square skeleton placeholder if draft is still streaming.

### 3. COMPLETED — Report & Grounded Follow-up
- **Report View**: Academic typography (`font-serif` title), booktabs tables, source citation popovers, metrics row (duration, cost, tokens, sources), and export actions (Copy, `.md`, `.pdf`, `.bundle.json`).
- **Follow-up Chat**: Square chat card with grounded assistant replies streaming via buffered SSE.

### 4. FAILED — Research Exception
- Square crimson error block, error message reason, partial sources gathered before failure, and "Start new research from this query" restart action.

---

## 4. Accessibility & Quality Bar

- **Semantic Landmarks**: Strict `<main>`, `<nav>`, `<header>`, `<aside>`, `<section>` hierarchy with unique IDs and `aria-labelledby`.
- **Keyboard Navigation**: Full keyboard focus visibility with high-contrast `--accent` outline ring.
- **Live Regions**: `aria-live="polite"` on streaming activity feeds and chat messages.
- **Contrast**: WCAG AA compliance across both light (`#FBFBFA`) and dark (`#121214`) palettes.
- **Strict Testing**: Zero TypeScript compilation errors (`tsc --noEmit`), Vitest suite clean across all formatting, citation, SSE, and pipeline tests.
