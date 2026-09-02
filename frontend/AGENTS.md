<!-- BEGIN:nextjs-agent-rules -->

# This is NOT the Next.js you know

This version has breaking changes — APIs, conventions, and file structure may all differ from your training data. Read the relevant guide in `node_modules/next/dist/docs/` (resolved from this file's directory; in monorepos the `next` package may not be visible from the repo root) before writing any code. Heed deprecation notices.

This block is written and re-added by `next dev` — verify at `node_modules/next/dist/server/lib/generate-agent-files.js`. Removing it from a diff only re-creates the uncommitted change; committing it with your work keeps the tree clean.

<!-- END:nextjs-agent-rules -->

---

# Agent guidance — frontend

Repo-wide rules are in [`../AGENTS.md`](../AGENTS.md). Everything below is specific to
this package. Keep it current: update a rule in the same commit that invalidates it.

## Four greps can fail your build

CI runs these against `app/ components/ lib/ hooks/` (`.github/workflows/ci.yml`). They
are not lint rules and `npm run lint` will not catch them:

1. **No `dangerouslySetInnerHTML`, no `rehype-raw`.** Reports are model-generated Markdown
   rendered in the user's browser; raw HTML there is an XSS sink (docs/06 §5).
2. **No hardcoded hex colors.** Every color comes from a token in `app/globals.css`
   (docs/07 §1). This is what makes both themes switchable and contrast-auditable.
3. **No hardcoded backend URLs** (`localhost:8000`, `NEXT_PUBLIC_API_URL`,
   `127.0.0.1:8000`). The browser talks to the same-origin `/api` proxy, which is why
   there is no CORS preflight in normal operation (docs/06 §6).
4. **No `localStorage`/`sessionStorage`** without an inline `ci-allow-web-storage:
   <reason>` marker on the same line. Auth is httpOnly cookies only (docs/03); the marker
   exists so a genuine non-auth UI preference is reviewable rather than invisible.

## The E2E suite registers more accounts than the limiter allows

`REGISTER_IP` is 5 per hour per IP (`app/services/rate_limit.py`), and it is deliberately
not configurable — it is brute-force protection, not a throughput knob, and the comment
beside it says so. The Playwright suite registers **one account per journey**, and there are
more journeys than that, so running the whole suite against one backend in one hour ends in
`429` on the last ones.

This is not caused by whichever spec happens to fail; `golden.spec.ts` alone already exceeds
it. Each spec passes when run on its own.

To run the suite locally, clear the counter between files — the E2E stack owns its Redis
database, so this touches nothing else:

```bash
docker exec research_redis redis-cli -n 5 FLUSHDB
```

Do not raise or bypass the limit to make the suite green. A registration cap that a test
suite can turn off is not a cap.

## Theming: tokens, and both themes are real

`next-themes` uses the **class** strategy — `.dark` on `<html>`, with Tailwind's `dark:`
variant redefined in `globals.css` to follow it rather than `prefers-color-scheme`.

Define a color once as a token in `:root` and again in `.dark`. Never introduce a color
whose only definition lives in one of the two blocks, and never inline a hex — the grep
above will catch it, but the reason is that half-themed components look correct to whoever
wrote them and broken to everyone on the other theme.

The one exception is a token defined *entirely* as a `color-mix` of tokens that are
themselves redefined under `.dark` — `--warning-soft` and friends. Both operands re-resolve
per theme, so the mix does too, and restating the expression in `.dark` could only ever
drift from the original. Do not "fix" those by duplicating them.

**A utility naming a token that does not exist renders nothing, and nothing warns.**
Tailwind v4 generates color utilities from the `@theme inline` block, so `bg-warning-soft`
works and `bg-status-warning-bg` — a name no token ever produced — is silently dropped.
It is not a lint error, not a type error, and not a build failure: it is a chip with no
background. The entire run workspace shipped that way, along with `border-border-subtle`,
`bg-accent-subtle`, a `.prose-report` that was never written and an `.input` class that
does not exist, which is why the whole surface read as unstyled. When you reach for a
utility, check the token is in `@theme inline`; `class="btn-primary"` needs `btn` too,
because the base class is where the padding lives.

Values are contrast-audited against **both** the page ground and the card surface. If you
change a token, check it clears WCAG AA (4.5:1) on both, in both themes. Ink on an
accent fill is `--accent-contrast`, never `#fff`: the dark accent is a light mint, and
white on it measures about 1.5:1.

## Agent colors carry meaning

`--agent-planner|executor|critic|synthesizer|hitl` are one distinct hue per pipeline stage,
consumed through `AGENT_TOKEN` in `lib/pipeline.ts` (`PipelineRail`, `LiveFeed`). They were
once three-of-five identical, which made different stages look like the same stage. Keep
them distinct, and keep hue as *reinforcement* — the rail also numbers and positions each
node, so meaning never rests on color alone.

`--info` is deliberately not `--accent`: when they matched, a "Running" badge was
indistinguishable from ordinary accented chrome.

## State patterns this codebase commits to

- **No `setState` in an effect** to derive state. Remount with a `key` instead — see
  `ChatPage`'s `ProjectThreads key={projectId}`, and `ActiveProject`, which reaches for
  `useSyncExternalStore` for the same reason.
- Project scoping comes from the **`ActiveProject` context**, not a route param. Every
  surface under the switcher is project-scoped; putting the id in the URL as well would be
  two sources of truth for one choice.

## Session routes are generated

`app/(app)/session/` is **generated and gitignored**. `scripts/prepare-session-routes.mjs`
copies from `app-routes/session/{web,desktop}/` before `dev`, `build`, and `e2e`, because
the web build needs a dynamic `[sessionId]` route and the desktop build needs a static
export. Edit `app-routes/`, never the generated directory.

## Looking at it

`node e2e/uiqa.mjs` screenshots every run surface in both themes at three widths, and
`node e2e/uiqa-interactions.mjs` presses the workspace's controls — arrow keys, the URL,
Back, refresh, a double-clicked submit. Both drive fixtures with no backend
(`e2e/uiqa.fixture.mjs`), so states that are awkward to reach on demand — a failed run, an
unresolved citation marker, a conflicting pair — are one command away. Neither is run by
CI and neither is a test; they exist because "it compiles" is not "it looks right", and
because the unstyled-workspace bug above passed lint, typecheck, `npm test` and all three
builds. They need a built app on `$UIQA_BASE`:

```bash
npm run build && cp -r .next/static .next/standalone/.next/static && cp -r public .next/standalone/public
PORT=3040 node .next/standalone/server.js &
UIQA_BASE=http://127.0.0.1:3040 node e2e/uiqa.mjs
```

`next start` does not serve an `output: standalone` build — it will happily serve a *stale*
`.next` from an earlier `build:desktop` instead, which costs an hour the first time.

## Running it

Dev server is port **3031** (`next dev -p 3031`). In Docker the frontend is a **static
`next build` image**, not a bind mount — source changes need
`docker compose -f docker-compose.full.yml build frontend`, and a browser reload will
show you stale UI and waste your time.
