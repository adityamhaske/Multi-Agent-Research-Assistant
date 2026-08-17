# Engineering guidelines

Rules this codebase holds itself to. Each one exists because its absence caused a real
defect; where that context helps, it is stated in a sentence rather than a post-mortem.

## The invariant everything else serves

**The product claim is verifiability, so a false measurement is a correctness bug, not a
cosmetic one.**

A citation that cannot be resolved must render its ⚠ chip rather than render clean. A metric
that could not be taken must say so — never print `0.0`, never record a model id you did not
call, never score a baseline against placeholder text.

## Never fail open

| Rule | Why |
|---|---|
| No `except: default_to_pass`, no silent empty-list fallback, no bare `except Exception: pass` | A parse failure that returns "passed" is worse than a crash, because nothing tells you |
| A caught provider error must surface its message | Swallowing one into `None` produced "planner: could not produce a valid task list" for what was actually an exhausted quota, and sent debugging the wrong way for days |
| A guard that fires says which one, and by how much | "Budget or loop limit exceeded" made a user read the source to learn which of three numbers had been crossed |
| Validation failures stop the unit of work with a recorded reason | Degraded output that looks complete is the failure mode this product exists to prevent |

## Unmeasured is not zero

`None` and `0.0` are different findings and must stay different values.

- `citation_resolution_rate` is nullable, and nothing renders `null` as zero.
- Evaluation metrics return `None` when nothing could be judged, and unjudged claims are
  excluded from the denominator rather than counted as misses.
- A three-state status (`ok` / `degraded` / `failed`) beats a boolean wherever "the server
  answered but rejected you" needs a different fix from "nothing answered".

## Never fake

- **No `print` in application code.** `structlog`, with `session_id` bound for the whole run.
- Never log secrets, tokens, or full page content.
- **Committed evaluation results are evidence, and evidence is write-once.** Add a new file;
  never modify one. CI enforces it.
- Demo output must be marked as demo in the database and stamped at every export path, so it
  cannot be laundered into a real-looking artifact.

## Structured everything

- Pydantic at every LLM boundary. Structured outputs, not "return only JSON" prompts.
- Typed events; typed API schemas.
- **Roles are sacred**: system messages are ours, assistant messages are the model's,
  retrieved content is data. Never replay model output as a system message.
- All untrusted content is framed as untrusted, unconditionally.

## Two homes, one contract

The recurring bug in this codebase is a shared behaviour implemented twice, with the second
copy forgotten. Prefer extracting one function over keeping two copies in step by discipline.

When you change any of these, **grep for the other copy before you finish**:

- Configuration → the server runtime *and* the local run-config builder
- Request → session fields → both start endpoints
- A new session status or pause event → the server *and* the desktop sidecar, including its
  status map, its lifecycle-event map, and its terminal-event list
- Route validation → the routing service *and* the pricing validator
- The unmeasured-vs-zero rule → the evaluation harness *and* the benchmark
- The budget rule → the edge guard *and* the in-flight guard
- Schema → an Alembic migration *and* the ORM model

A missing key in the sidecar's status map raises inside a background task, so the session
sits on `RUNNING` forever with nothing in the log to say why. The server path is exercised
constantly and the desktop path only at release time, which is exactly why divergence ships.

## Data and schema

- **Alembic is the only schema writer.** No `create_all` in application code — it once masked
  an empty migration.
- Money is `numeric`, never float. Timestamps are `timestamptz` with server defaults.
- One database-session scope per unit of work; the objects it loads do not outlive it.
- Relationships relying on `ON DELETE CASCADE` set `passive_deletes=True`.
- List endpoints ship slim schemas; report bodies only on the detail endpoint.
- Migrations are append-only once merged, and every one has a real `downgrade()`.

**A field the schema accepts and the run never reads is a promise the run does not keep.**
Two request fields were once dropped on the floor between the API and the session row, so
"restrict to uploaded corpus" silently ran an ordinary web search.

## Security

- Auth is httpOnly cookies. **Never** tokens in web storage or in URLs.
- Isolation is a SQL predicate, never a prompt instruction.
- Never render raw HTML from model output.
- A user's provider key must never enter a response body, a log, or a module global.
- Any new URL the system fetches goes through the SSRF guard.

## Tests

- **A feature without its tests is not done.**
- A bug fix lands with a regression test named after the bug.
- **A test that stubs the thing it is testing proves nothing.** When testing an absence, check
  what the fixtures replaced.
- Budgets live on graph edges, so a new node must sit on a path that passes one.

## Dependencies and configuration

- No dependency without an import site in the same change.
- No hardcoded URLs, hex colours, model ids, prices, or secrets — all of these live in
  configuration or design tokens.
- New configuration keys go into `.env.example` and, where applicable, startup validation.
- Fail fast at startup: validate secrets, prices, and provider keys before serving traffic.

## Documentation

- Behaviour change → documentation change **in the same pull request**.
- Nothing aspirational. A statement without a `Planned` marker is a claim that the thing
  exists and works.
- Keep the agent guidance files current: they describe traps, not features, and a stale rule
  is worse than no rule because it gets trusted.

## Git

- Conventional commits (`feat:`, `fix:`, `docs:`, `test:`, `refactor:`, `chore:`), imperative
  mood, subject ≤ 72 characters.
- `main` is protected. Pull requests only, green CI required, no force-push.

## Review checklist

- [ ] Tests included and meaningful; a regression test if this fixes a bug
- [ ] Documentation updated if behaviour, configuration, or the API changed
- [ ] New configuration keys in `.env.example`, and in both configuration paths
- [ ] No fail-open handlers, no unscoped database sessions
- [ ] Error paths produce user-visible, actionable states
- [ ] Prompt or model changes carry an evaluation run in the description
- [ ] Schema changes: migration **and** ORM model, round-trip works, indexes for new queries
- [ ] The second home of anything shared has been checked
- [ ] No secrets, tokens, or personal data in code, fixtures, or logs
