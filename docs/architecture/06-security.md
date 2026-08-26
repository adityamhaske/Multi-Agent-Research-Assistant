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

The guard is relaxable via `RunConfig.enforce_ssrf_guards` for the desktop build, which has
to reach a local model server on loopback. It is strict on the server.

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
