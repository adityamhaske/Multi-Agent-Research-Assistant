# Frontend guidelines

Conventions for working on `frontend/`. This is a contributor page, not a design
specification — the source of truth for every colour and type scale is `app/globals.css`.

## Non-negotiables

Four rules are enforced by greps in CI, over `app/ components/ lib/ hooks/`. They are not
lint rules, and `npm run lint` will not catch them.

1. **No `dangerouslySetInnerHTML`, no `rehype-raw`.** Reports are model-generated Markdown
   rendered in the user's browser; raw HTML there is an injection sink.
2. **No hardcoded hex colours.** Every colour is a token. This is what makes both themes
   switchable and contrast-auditable.
3. **No hardcoded backend URLs.** The browser talks to the same-origin `/api` proxy, which is
   why there is no CORS preflight in normal operation.
4. **No web storage** without an inline `ci-allow-web-storage: <reason>` marker on the same
   line. Auth is httpOnly cookies only; the marker exists so a genuine non-auth UI preference
   is reviewable rather than invisible.

They are GNU greps that cannot tell a use from a mention: a *comment* naming a banned token
fails the build as surely as calling one. Describe the rule without writing the names.

## Theming

`next-themes` with the **class** strategy — `.dark` on `<html>`, and Tailwind's `dark:`
variant redefined to follow it rather than `prefers-color-scheme`.

Define a colour **once in `:root` and again in `.dark`**. Never introduce a colour whose only
definition lives in one of the two blocks: a half-themed component looks correct to whoever
wrote it and broken to everyone on the other theme.

Values are contrast-audited against both the page ground and the card surface. If you change
a token, check it clears WCAG AA (4.5:1) on both surfaces, in both themes.

**Agent colours carry meaning.** One distinct hue per pipeline stage, consumed through a
shared map rather than inline. They were once three-of-five identical, which made different
stages look like the same stage. Keep them distinct — and keep hue as *reinforcement*: the
pipeline rail also numbers and positions each node, so meaning never rests on colour alone.

## Components

- **Server components by default.** `"use client"` only where interaction demands it.
- All server state goes through TanStack Query and the shared API client. Components never
  call `fetch` directly, and there is no hand-rolled fetch-in-effect.
- **No `setState` in an effect to derive state.** Remount with a `key` instead.
- Project scoping comes from the active-project context, not from a route parameter. Putting
  the id in the URL as well would be two sources of truth for one choice.
- Immutable state updates; keys are stable ids, never array indices for dynamic lists.
- Extract a component before writing its third copy. Every drift bug this repository has
  catalogued started as a second copy of something.

## Streaming

SSE parsing is a pure string state machine so it can be unit-tested with no network. Two
things are load-bearing and easy to undo by accident:

- decode with `{ stream: true }`, so a multi-byte character split across two network chunks
  survives;
- carry an incomplete event across feeds, emitting only on a complete `\n\n`-terminated
  block.

Both had real regressions — corrupted characters and dropped events at chunk boundaries — and
both have named tests.

## Accessibility

- Both themes pass WCAG AA on core pages; that is a merge criterion, not an aspiration.
- Every interactive control is reachable and operable by keyboard, with a visible focus
  state.
- Status is never conveyed by colour alone.
- Live regions for streaming content are announced without being chatty.
- Icon-only controls carry an accessible name.

## Build targets

Three, not two: the standalone server image, the Tauri desktop static export, and the GitHub
Pages static export. A flag read at build time collapses to dead code in the other two, which
keeps them isolated — and means a branch is only exercised by the target that builds it.

```bash
npm run build           # server
npm run build:desktop   # desktop
npm run build:pages     # public site
```

CI runs the first two. Anything touching `app/(site)/` or `app/layout.tsx` needs all three
run locally.

`app/(app)/session/` is **generated and gitignored**. Edit `app-routes/session/{web,desktop}/`
instead.

## Tests

Vitest plus Testing Library, behaviour-focused and accessibility-first — query by role and
label rather than by class name. Pure logic (the SSE parser, citation rendering, pipeline
derivations, formatters) is unit-tested; whole journeys are Playwright's job.

```bash
npm test
npm run e2e
```

## The public site

`app/(site)/` is generated from the app: the documentation it renders is the repository's
`docs/` tree, and the comparison table is a module the app itself imports. That is
deliberate — its predecessor was one hand-maintained HTML file that described a product
which no longer existed, and nobody noticed.

Three things next to it are still hand-written and go stale silently, because nothing fails
when they do: the release list, the README download badge, and the pipeline diagram. Update
them when you tag a release.
