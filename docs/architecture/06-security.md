# Security

What is implemented, what it prevents, and where the limits are. Every item here is
testable, and most have a named test behind them.

To report a vulnerability responsibly, contact the maintainers directly through private disclosure rather than filing a public issue.

## 1. Threat model

The system fetches attacker-controlled content and feeds it to a model that then chooses
what to fetch next. That single property drives most of what follows.

| Adversary | Capability | Primary defence |
|---|---|---|
| A malicious web page | Text the executor reads and the model acts on | Untrusted-content framing (§6), SSRF guard (§5), structured-output validation (§7) |
| A hostile visitor | Unauthenticated requests, credential stuffing | Cookie auth (§2), brute-force limits (§4) |
| Another user of a shared deployment | Their own account | Per-user key isolation (§9), SQL-level project isolation, per-user token ceilings |
| Someone with a stolen session cookie | Authenticated requests | Short access-token lifetime, current-password requirement on password change |
| A curious operator | Database access | Provider keys encrypted at rest (§9) |

Explicitly **not** in the threat model: a hostile operator of your own self-hosted
deployment, and a compromised model provider.

Letting an account replace an agent's system prompt adds no adversary to this table. The
account can change only the instructions its own runs and chat follow, and the attacker is
still the web page. What a replaced prompt can and cannot reach is set out in §6.

## 2. Authentication and sessions

**Design: httpOnly cookies through the same-origin proxy.** This prevents token theft via
XSS from web storage, broken `EventSource` auth, and tokens in URLs.

- **Access cookie** — a JWT, HS256, 15 minutes, `httpOnly`, `Secure` in production,
  `SameSite=Lax`, path `/`.
- **Refresh cookie** — an opaque 256-bit random token, 14 days, `httpOnly`, path
  `/api/v1/auth`. Stored server-side only as a SHA-256 hash. **Rotated on every use**, and
  reuse of an already-rotated token revokes the whole family.
- **Logout** revokes the refresh token server-side and clears both cookies.
- **Password change** requires the current password — a stolen session cookie alone must not
  be enough to lock the owner out — and revokes every refresh token for the account, then
  immediately re-issues for the caller.
- **Startup hard-fails** if `JWT_SECRET_KEY` is missing, under 32 characters, or matches a
  known placeholder.

A `Bearer` header is also accepted, for non-browser API clients.

### Where this differs from a common design

There is **no CSRF token and no custom-header check**. The protection is `SameSite=Lax`
plus the fact that every state-changing endpoint is JSON-only over `fetch` on the same
origin. That is adequate for the current shape, and it is worth knowing it is the whole of
it: if you front this with something that changes the origin model, re-examine it.

## 3. Passwords

- Minimum 12 characters; over 72 **bytes** is rejected explicitly rather than letting bcrypt
  truncate silently.
- Checked against a small embedded set of the most common breached passwords. This is a
  floor, not a breach-corpus check — a deployment that wants a real one should extend it.
- bcrypt directly at cost 12. `passlib` is unmaintained and conflicts with modern bcrypt.
- Registration returns a **neutral response** either way, so the endpoint cannot be used to
  enumerate accounts.
- Email verification is available via `REQUIRE_EMAIL_VERIFICATION`, **off by default** for
  self-host simplicity and documented as required for any public deployment.

## 4. Rate limiting

Implemented as one atomic Lua script doing INCR and conditional EXPIRE together, so a
counter can never exist without a TTL. Keys are per-operation, so research and chat never
share a budget.

| Operation | Key | Limit | Configurable |
|---|---|---|---|
| Login | `rl:login:ip:{ip}` + `rl:login:email:{email}` | 20/min per IP; 5 failures per 15 min per account | **No** |
| Register | `rl:register:ip:{ip}` | 5/hour | **No** |
| Password change | reuses the login IP limiter | 20/min | **No** |
| Research start | `rl:research:{user_id}` | **0 = unlimited (default)** | `RESEARCH_RATE_LIMIT_PER_HOUR` |
| Chat message | `rl:chat:{user_id}` | **0 = unlimited (default)** | `CHAT_RATE_LIMIT_PER_HOUR` |

The split is deliberate. Auth limits are brute-force protection and are **not** configurable
— an operator must not be able to disable credential-stuffing defence while raising a usage
cap. Research and chat limits are abuse guards for a multi-tenant host, not safety limits,
so they default to unlimited: this ships as a single-tenant self-hosted app where the
operator is the only user and pays their own bill.

**A public deployment should set both**, along with `DEFAULT_MONTHLY_TOKEN_LIMIT`. When a
limit is disabled, no Redis counter is written at all, so re-enabling it later starts from a
clean window.

429 responses state the limit that was hit and when to retry.

## 5. SSRF defence

The URL passed to `read_webpage` is chosen by a model steered by untrusted web content, so
it is treated as hostile. The guard runs **per hop**:

1. Scheme must be `http` or `https`; no userinfo in the URL; port must be 80, 443, 8080, or
   8443.
2. A literal IP is checked directly. A hostname is resolved and **every** returned address
   is checked. Rejected ranges: loopback, private (RFC 1918 and RFC 4193), link-local
   (including `169.254.0.0/16`, which is where cloud metadata lives), CGNAT `100.64.0.0/10`,
   multicast, reserved, and unspecified.
3. Redirects are **not** auto-followed. Each `Location` re-enters step 1, to a maximum of 3
   hops.
4. Response caps: 2 MB body, 10-second timeout, and `Content-Type` must be `text/html` or
   `text/plain`.

A blocked fetch returns an error the executor must surface, rather than raising — so the
run finishes with what it has instead of looping on a dead tool.

**Known limit:** the connection is not pinned to the validated IP, so a sufficiently precise
DNS-rebinding race between the check and the fetch is not fully closed by this
implementation. The address-range checks and the per-hop redirect re-validation are what
carry the weight.

This guard applies to every live page fetch, on every hop, in every deployment — the desktop
app included — and no setting turns it off. `RunConfig.enforce_ssrf_guards` is a separate
control over **custom model endpoints**: when it is on, a custom endpoint's base URL is
checked against the same address ranges before it is called or probed. It is on when
`ENVIRONMENT=production` and off otherwise, and always off on the desktop app, which has to
reach a local model server on loopback.

## 6. Prompt injection and untrusted content

- All retrieved text — web pages, and retrieved memory excerpts, which originated as web
  pages — is wrapped in `<untrusted_web_content>` tags with a standing instruction that
  content inside them is **data**, that instructions found there must never be followed, and
  that they should be reported as suspicious.
- **Project isolation is a SQL predicate**, never a prompt instruction. Retrieval is filtered
  by `project_id` after an ownership check, before anything reaches a model. A prompt-level
  "only use project X" is not a security control and is not treated as one.
- **Assistant history is replayed as assistant messages**, never as system messages. Model
  output must not gain system authority.
- Memory persists attacker-influenced text indefinitely, so an injection captured months ago
  can resurface long after the run that ingested it. Retrieved chunks inherit the framing
  unconditionally for exactly that reason.

### User-authored system prompts

An account may replace the system prompt of the five agent roles — planner, executor,
critic, synthesizer, and chat — from its own settings. That changes who writes a system
prompt, not who the attacker is:

| | Shipped prompts | A replaced prompt |
|---|---|---|
| Who writes the system prompt | The project | The account, for its own runs and chat |
| Untrusted-content framing | Part of the shipped text | Added by the system around the replacement; not part of the editable text |
| Attacker | A web page, or a memory excerpt that was once one | Unchanged |
| Blast radius | The account's own run | The account's own runs and chat |

**Composition, not validation.** Where a shipped prompt carries the instruction to treat
`<untrusted_web_content>` as data, the system adds that instruction before and after the
replacement text. The replacement is never checked for it: a check that a prompt "contains
the instruction" is satisfied by text that then contradicts it — the same reason a
prompt-level "only use project X" is not treated as isolation. What holds the boundary is
which prompts a replacement may reach, and the fact that the framing is added rather than
asked for.

Replacements are validated identically on both hosts — one of the five roles, non-empty text,
at most 2,500 characters each — and checked again when a run starts. A stored set that fails
that check is not partly applied: the run uses its shipped prompts and records that it did.

#### What a replacement can and cannot reach

Five roles share nine prompts, and whether a prompt may be replaced is decided per prompt,
not per role — so a replacement for the critic reaches its per-task grading and nothing else
it does. The mechanics are in [agent architecture](04-agent-architecture.md).

| Control | Can a replaced prompt affect it? | Why |
|---|---|---|
| Planner behaviour | **Yes**, by design | Its output is still schema-validated |
| Executor strategy | **Yes**, by design | Evidence snippets must still be text the tools actually fetched (§7) |
| Critic grading of each task's evidence | **Yes**, by design — including more lenient grading | The critic still fails closed on invalid output (§7) |
| Report drafting | **Yes**, by design | Citation markers are still validated against the evidence (§7) |
| Report chat | **Yes**, by design | General report chat only |
| Citation verification | **No** | A protected prompt. It decides whether a citation is supported, so replacing it would let an account grade its own citations |
| Contradiction detection | **No** | A protected prompt. A replacement could be told to report no conflicts |
| Citation repair | **No** | A protected prompt. It rewrites citations on a draft, so a replacement could make fabricated citations look repaired |
| Project chat | **No** | A protected prompt. Its refusal line is what keeps grounded answers grounded |
| Page-fetch SSRF guard | **No** | Code, on every hop (§5) |
| Custom-endpoint SSRF check | **No** | `enforce_ssrf_guards`, set by the deployment (§5) |
| Corpus-only egress | **No** | `corpus_mode` comes from the run's own request; retrieval and page reads branch on it in code |
| Budgets, and whether a run is recorded as a demo | **No** | Deployment configuration and the run's own request |
| Artifact authorization | **No** | Database constraints, the authorization module, the bundle assembler, and the verifier |
| Project isolation | **No** | A SQL predicate applied before retrieval (above) |
| Bundle integrity | **No** | SHA-256 over the manifest ([bundle format](../reference/15-bundle-format.md)) |
| Output validation | **No** | A Pydantic model at every model boundary; a parse failure is a node failure (§7) |
| The evaluation judge | **No** | Literal judge prompts, and a candidate prompt removed before judging ([testing and evaluation](../developers/08-testing-and-evaluation.md)) |

The **No** rows hold for structural reasons, not because of anything a prompt says. A stored
replacement is read in exactly one place, the function that selects a system prompt, and for a
protected prompt that function returns the shipped text before it reads any replacement at
all. What it returns is used as system-message text and, inside a run, recorded as that
run's prompt provenance; no guard or limit reads it. None of the controls above is a user
preference, so the one surface an account edits cannot carry them.
`backend/tests/security/test_prompt_override_reach.py` and
`backend/tests/security/test_protected_prompt_purposes.py` pin those facts.

#### One account's prompt, one account's work

Replacements are a per-account preference. A research run uses its owner's replacements,
copied onto the run when it starts and read from there on every resume, so editing them while
a run waits at a gate cannot change it. Report chat uses the replacements of the account
asking. The earlier session pipeline does not apply replacements at all: a session whose owner
had them configured records that they were not applied, and the session API returns that
record. The evaluation harness never reads an account's preferences.

Nothing lets one account share, import, or apply another account's prompt, and that absence is
load-bearing. Shared prompts, shared workspaces, or links that carry a run's configuration to
someone else would make a prompt input from another party, and this section would no longer
hold.

#### A custom prompt is not a secret

It is stored as plain text in the account's preferences, copied onto every run started while
it is set, and included in full in the version 2 bundle of any run whose prompt it replaced
([bundle format](../reference/15-bundle-format.md)); the verification endpoint returns hashes
only. Do not put a key, a password, or anything confidential in one. Saving a prompt never logs
its text — the server records which settings changed, the desktop app records nothing — and no
metric label carries prompt content.

#### Limits, and what is not a threat

Composition guarantees the untrusted-content instruction is present, not that the model obeys
it. A replacement that tells the model to ignore it weakens only its author's own runs.

A poorly written prompt is a quality problem, not a security one; the custom-spec evaluation
measures a replacement against the shipped prompts
([testing and evaluation](../developers/08-testing-and-evaluation.md)).

## 7. Structured-output validation

Every LLM boundary is a Pydantic model, and a parse failure is a node failure.

- The **critic fails closed**: invalid output becomes `passed=False` with the reason. It
  never defaults to pass.
- The **synthesizer may only cite evidence in state**, and markers are validated against the
  evidence list before a draft is accepted.
- **Evidence snippets must be text that was actually fetched.** Each snippet is checked
  against what the tools really returned for that URL; one that does not occur there is
  **blanked and flagged**, not trusted. The citation keeps its source and loses its quote,
  rather than displaying an invented one. A quote cannot be reconstructed from a model's
  memory of a page.
- Contradiction pairs whose source URL was not in the evidence are dropped, so a fabricated
  or injected source cannot reach the report.

## 8. Frontend output safety

- `react-markdown` with default sanitisation. **`rehype-raw`, `skipHtml={false}`, and
  `dangerouslySetInnerHTML` are banned**, enforced by a CI grep over `app/`, `components/`,
  `lib/`, and `hooks/`.
- Citation chips are produced by a dependency-free Markdown plugin rather than by injecting
  HTML.
- **Remote images in report Markdown are not rendered** — the component override turns them
  into links — so injected content cannot exfiltrate a reader's IP through a tracking pixel.
- External links carry `rel="noopener noreferrer nofollow"`.
- No auth token ever touches web storage; a CI grep enforces that too, and a genuine
  non-auth UI preference must carry an inline justification marker to pass.

### Uploaded document preview

One narrow exception to "an uploaded document never renders in this origin":
`application/pdf` is served `inline` so the browser's own sandboxed viewer can display it,
with `nosniff`, `frame-ancestors 'self'`, and an explicit `X-Frame-Options: SAMEORIGIN` on
that route. In-place PDF preview cannot work any other way.

Every other kind is served `attachment` and previewed by the client fetching the bytes and
rendering them itself — `fetch` ignores `Content-Disposition`, so this costs the preview
nothing. Uploaded HTML renders inside a fully sandboxed frame. Accepted kinds are `pdf`,
`html`, `md`, and `txt`.

## 9. Bring-your-own-key protection

A key a *user* pastes is their secret, not the operator's:

- **Encrypted at rest** with Fernet (AES-128-CBC + HMAC). The encryption key is derived via
  HKDF-SHA256 from `ENCRYPTION_KEY`, falling back to `JWT_SECRET_KEY` under a distinct
  domain-separation label. Set `ENCRYPTION_KEY` explicitly in production so rotating JWTs
  does not invalidate every stored key.
- **Never returned.** No endpoint echoes it; responses carry the provider and a last-four
  hint. Set and remove events log the provider, never the key.
- **Scoped at use.** Decrypted only inside the worker, for the duration of that user's own
  run, and held in a `ContextVar` — so concurrent runs in one worker process cannot read
  each other's key, and a Google key is never handed to an Anthropic-routed role.
- **Degrades rather than crashing.** An undecryptable key (a rotated secret) is treated as
  absent: the run continues on the server key with a warning logged, and the user re-enters
  it.
- **A custom base URL is SSRF-validated** before it is stored, in production.
- **Limits still apply.** `DEFAULT_MONTHLY_TOKEN_LIMIT` caps new accounts so one signup
  cannot drain a shared server key.

On the desktop build the equivalent store is the **OS keychain**.

## 10. Transport and headers

The API sets, on every response:

```
X-Content-Type-Options: nosniff
X-Frame-Options: DENY
Referrer-Policy: no-referrer
Permissions-Policy: geolocation=(), microphone=(), camera=()
Content-Security-Policy: default-src 'none'; frame-ancestors 'none'; base-uri 'none'
```

Plus `Strict-Transport-Security` when `ENVIRONMENT=production`. The API serves JSON only, so
its CSP locks scripting and framing down completely.

The frontend sets its own, including a CSP of `default-src 'self'` with no external script or
style origins — fonts are self-hosted — and `frame-ancestors 'none'`. `unsafe-eval` appears
in development only, for React's error overlay.

**CORS is not used in production.** The browser talks to the same-origin `/api` proxy, so
there is no cross-origin browser access to permit. In development the API allows exactly the
configured `FRONTEND_URL` and nothing else.

FastAPI's `/docs` and `/redoc` are disabled when `ENVIRONMENT=production`.

Server-sent events carry `Cache-Control: no-cache, no-transform` and `X-Accel-Buffering: no`.
That is a correctness control as much as a performance one: a compressing intermediary
buffers an event stream while filling a compression window, and the symptom is a healthy
connection that never delivers anything.

## 11. Secrets and configuration

- `.env.example` is committed and annotated; `.env` is gitignored.
- **No default secrets.** Startup refuses placeholder or short values.
- Provider keys are used server-side only, never logged, never echoed in errors.
- Deleting a user cascades to sessions, logs, messages, audit rows, and memory chunks at the
  database level.

**Not implemented:** there is currently no automated secret scanner in CI. If you fork this
for a public deployment, adding one is a reasonable first change.

## 12. Production hardening checklist

Before exposing this to anyone but yourself:

- [ ] `JWT_SECRET_KEY` is unique and ≥ 32 random bytes
- [ ] `ENCRYPTION_KEY` is set explicitly, not derived
- [ ] `ENVIRONMENT=production` — secure cookies, HSTS, `/docs` disabled
- [ ] TLS terminated in front of the frontend; the backend is not publicly reachable
- [ ] `REQUIRE_EMAIL_VERIFICATION=true`
- [ ] `RESEARCH_RATE_LIMIT_PER_HOUR`, `CHAT_RATE_LIMIT_PER_HOUR`, and
      `DEFAULT_MONTHLY_TOKEN_LIMIT` all set to non-zero values
- [ ] Spend capped **at the provider**, not only in this app — the in-app cap cannot fire on
      OpenRouter or custom endpoints
- [ ] Database backups configured and a restore actually tested
- [ ] Dependency audit clean (`pip-audit`, `npm audit`)

See [Production deployment](../deployment/30-production.md) for the mechanics.
