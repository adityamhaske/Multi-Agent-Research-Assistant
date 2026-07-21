# 07. UI/UX Guidelines

> Design system and page-level specs for the Next.js frontend. The bar: a reviewer
> should think "this is a real product", and a user should never wonder what the app is
> doing right now.

## 1. Design system

### Tokens (CSS variables, defined once in `globals.css`)

- Colors: `--bg-base`, `--bg-surface`, `--bg-elevated`, `--border`, `--text-primary`,
  `--text-secondary`, `--text-muted`, `--accent`, `--accent-muted`, plus semantic
  `--success`, `--warning`, `--danger`, `--info`.
- **Rule: components never hardcode hex values.** All color usage goes through tokens
  so dark/light themes both work. (The previous iteration hardcoded dark-theme hex
  in JSX, which silently broke light mode.)
- Both themes are first-class: `next-themes` class strategy; every token has a value in
  `:root` (light) and `.dark`.
- Typography: Inter (UI), JetBrains Mono (log feed, code) via `next/font` — no external
  CSS imports.
- Spacing/radius: Tailwind defaults; radius `rounded-xl` for cards, `rounded-lg` for
  controls.
- Report/chat prose uses `@tailwindcss/typography` (`prose dark:prose-invert`) — the
  plugin is a hard dependency; a missing-plugin state (unstyled reports) is a bug.

### Interaction states

Every interactive element defines: default, hover, focus-visible (visible ring using
`--accent`), disabled, and loading. Every async action shows progress inline (button
spinner + disabled) and resolves to a toast (react-hot-toast) on failure.

## 2. Information architecture

```
/            → redirects: authed → /dashboard, else → /login
/login       → login + register (tabbed)
/dashboard   → new research form + recent sessions
/history     → full session list (filter by status, paginated)
/session/[id]→ the session lifecycle page (states below)
```

Shared shell: top nav (logo, Dashboard, History, theme toggle, user menu with logout).
Auth guard is a server-side layout concern (cookie check + redirect), not a
per-page `useEffect`.

## 3. Session page — the core surface

One page, five states driven by session status. Every state must render something
meaningful; blank panels are bugs (the previous iteration rendered an empty void when
a status arrived before its report body).

### PENDING / RUNNING — "the brain monitor"
- Pipeline rail: Planner → Executor → Critic → Synthesizer with live states
  (pending / active-pulsing / done). Driven by `agent_log` events.
- Live feed: monospace log stream, auto-scroll with a "jump to latest" affordance when
  the user scrolls up (never fight the user's scroll).
- Status bar: elapsed time (computed from the session's server-side `created_at`, not
  page-load time), running cost, task progress (`2/4 tasks`).
- SSE lifecycle: connect on mount, **replay history first** (server sends persisted
  logs), reconnect with `Last-Event-ID` on drop, show a subtle "reconnecting…" pill
  when the stream is down and fall back to 5 s status polling.

### AWAITING_APPROVAL — the review gate
- Split view: draft report (rendered markdown w/ citations, §5) beside the decision
  panel.
- Decision panel: source count, cost so far, rework count (`2 of 3 rework rounds
  used`), Approve button, and a rework textarea with helper text + validation.
- Both actions optimistic-update the status and re-subscribe to the stream
  (through the same connect function as mount — reconnects must carry all handlers).
- If the draft body hasn't loaded yet: skeleton loader, never blank.

### COMPLETED — report + chat
- Report pane: rendered markdown with the citations UX (§5), metrics row (duration,
  cost, tokens, sources), export buttons (Copy, `.md`, `.pdf`).
- Chat pane: grounded follow-up chat (§6).

### FAILED
- Human-readable reason (from `error_message`), whatever partial evidence exists
  ("12 sources were gathered before failure" with the sources list), and a
  "Start new research from this query" action. Never a dead end.

## 4. Dashboard

- New research form: query textarea (10–2000 chars, live counter), depth selector
  (fast / balanced / comprehensive with plain-language descriptions + cost hints),
  submit → optimistic redirect to the session page.
- Recent sessions (last 5): status badge, query preview, relative time, cost; click
  through to session page. Empty state with a sample-query suggestion.

## 5. Citations UX — the differentiator

- Inline `[n]` markers rendered as small superscript chips.
- Hover/tap a chip → popover: source title, domain, **the verbatim supporting
  snippet**, and an "open source" link (`noopener noreferrer`).
- Sources panel at the report foot: numbered list with title, domain, snippet,
  retrieval timestamp.
- A claim whose marker doesn't resolve renders a visible ⚠ "unverified" chip — surfacing
  pipeline bugs instead of hiding them.

## 6. Chat panel

- Streamed assistant responses (fetch + reader with UTF-8-safe, boundary-safe SSE
  parsing: `decode(value, {stream: true})`, buffer carry-over between reads —
  the previous iteration corrupted emoji and dropped events at chunk boundaries).
- State updates are immutable (replace-by-id, never mutate the last array element).
- Message list: user right-aligned, assistant left with rendered markdown; input
  disabled while streaming with a stop affordance; errors restore the input text.

## 7. Quality bar

- **Accessibility**: semantic landmarks, labels on all inputs, focus-visible
  everywhere, `aria-live="polite"` on the log feed and chat stream, WCAG AA contrast
  in both themes, full keyboard operability (approve/rework reachable by tab).
- **Responsive**: desktop-first two-pane layouts collapse to stacked/tabbed panes
  < 1024 px; the log feed and report remain readable at 375 px.
- **Empty/loading/error triad**: every data surface defines all three states.
- **No hand-rolled state machines for server data**: TanStack Query owns fetching,
  caching, and invalidation; SSE handlers write into the query cache.
