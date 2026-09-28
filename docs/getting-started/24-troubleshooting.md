# Troubleshooting

The failures people actually hit, and what each one means.

## Startup

**`JWT_SECRET_KEY must be >= 32 chars of real randomness`**
The app refuses to boot on a short or placeholder secret. Generate one:

```bash
openssl rand -hex 32
```

**`No price for routed model(s): [...]`**
A routed model has no entry in the catalog. An unpriced model is refused rather than
assumed free, because a silent `0.0` would turn the per-session cost cap into a no-op.
Either route to a model the catalog knows, or add a `ModelSpec` in
`backend/research_engine/catalog.py` with the provider's published prices.
`ollama`, `openrouter` and `custom` routes are exempt.

**`Model routing uses provider 'X' but no API key is configured for it`**
Only raised when `ENVIRONMENT=production` and `LLM_MODE=real`. Set the key, or change the
`MODEL_*` routing. `ollama` and `custom` are exempt because they need no key.

**`alembic upgrade head` fails on `CREATE EXTENSION vector`**
The database is stock Postgres. Migration 0006 enables pgvector and 0007 creates a vector
column, so the image must be `pgvector/pgvector:pgNN`. Every compose file pins one.

**The API starts but the browser gets CORS errors in development**
`FRONTEND_URL` is the dev-only CORS allow-list and must match where the frontend actually
runs — **port 3031**, not 3000. In a real deployment there is no CORS at all; the browser
talks to the same-origin `/api` proxy.

## Running research

**A run sits on `PENDING` forever**
The worker is not consuming. Check it is running and can reach the broker:

```bash
docker compose -f docker-compose.full.yml logs worker
docker compose -f docker-compose.full.yml exec worker \
  celery -A app.workers.celery_app.celery_app inspect ping
```

A worker that answers a ping may still be importing LangGraph and the provider clients,
which takes noticeably longer on the first task than on the second.

**A run sits on `RUNNING` and nothing changes**
The worker crashed mid-run. The Redis lock on the run has a TTL longer than the task timeout,
so it expires and the run becomes resumable from its last checkpoint. If a budget or
wall-clock limit was crossed, it self-fails with the reason instead.

**The live feed stays on "Waiting for the pipeline to start…"**
Almost always a proxy buffering the event stream rather than a broken pipeline. Any
compressing intermediary — nginx's gzip, a CDN, Next's own compression — will buffer a
`text/event-stream` while it fills a compression window; the connection looks healthy and
no events arrive.

The API sets `Cache-Control: no-cache, no-transform` and `X-Accel-Buffering: no`, which
both nginx and the compression middleware honour. If you have another proxy in front,
disable buffering and transformation for `text/event-stream` there too. The client also
falls back to polling every 5 seconds, so a run still converges.

**Every search fails**
Check which retrievers errored in the worker logs. With no Tavily or Brave key the chain
falls back to DuckDuckGo, which rate-limits aggressively. Add a key, or expect slow and
patchy retrieval.

**A run dies with `input-token ceiling reached` / `cost ceiling reached` / `time limit reached`**
A guard fired and says which one and by how much. All three default to unlimited, so
whichever one tripped is set in your environment. See
[Configuration](21-configuration.md#run-limits).

**Reports come out empty, or full of obviously fake sources**
Either the app is in `LLM_MODE=fake` — check for the demo banner and the `⚠ DEMO` stamp on
exports — or the model is too small for the structured-evidence step. See
[Local LLM setup](22-local-llm.md#6-which-models-actually-work).

**The first call to a Gemini model is refused**
The default routing is Google's Gemini 2.5 models, and Google now serves each 2.5 model only to
accounts that have used it before. On a key from an account that has not, the first call to that
model is refused — the key is fine, the model is not available to it. Route the agents to other
models in Settings → Models.

**A run ignored the agent instructions I just saved**
A run keeps the instructions it started with, so saving while it waits at a gate changes your
next run, not that one. Research recorded as a session never applies them. The run's Artifact
tab, and its bundle, record which instructions it actually ran on. See
[Agent instructions](../user-guide/38-agent-instructions.md).

**Saving an agent's instructions is refused**
Instructions must be non-empty and at most 2,500 characters. An empty box is not a reset —
use **Reset to default** on the agent's card to go back to the shipped prompt.

**Cost shows `$0.00` on a run that definitely cost money**
The route is `openrouter` or `custom`. Their prices are not in the catalog, so estimated
cost is always zero and `MAX_COST_PER_SESSION_USD` never fires. Cap spend at the provider.

## Citations

**A claim shows a ⚠ *unverified* chip**
That is the system working. The marker does not resolve to a source in this report's
sources table, so it renders as a visible failure rather than as a clean citation. See
[Citations](../user-guide/27-citations.md).

**History shows *Not measured* for citation resolution**
The rate is measured when a report is approved, so an unapproved run has none yet. Otherwise
the report made no citable claims, or predates the column. It is deliberately not shown as
`0.0`, which would mean the opposite — that every marker failed.

**The verifier says `Unsupported bundle_version 2`**
The bundle is from 3.0.0 or later and the verifier is older. Version 2 bundles record the
prompts each agent ran on, and a verifier from before 3.0.0 cannot read them. Run the verifier
from 3.0.0 or later; it verifies version 1 bundles unchanged.

**`[3, 11, 18]` renders as plain text rather than as chips**
Only single `[n]` markers become interactive chips today. Grouped markers still resolve in
the report's sources table; they are just not hoverable. Listed under known limits in the
[Overview](01-overview.md#known-limits-stated-plainly).

## Local models

Covered in full in [Local LLM setup §7](22-local-llm.md#7-troubleshooting). The two most
common:

- **Not detected, but `curl localhost:11434` works** — the app is in Docker and `localhost`
  there is the container. Use `OLLAMA_BASE_URL=http://host.docker.internal:11434/v1`.
- **A different model answers than the one you selected** — you routed to a family
  (`ollama:qwen2.5`) rather than the installed tag (`ollama:qwen2.5:14b`), and the family
  resolved to `:latest`.

## Corpus and project chat

**Corpus upload fails, or project chat returns 503**
No embeddings provider is reachable. `EMBEDDINGS_PROVIDER=auto` prefers a local Ollama with
an embedding model installed (`ollama pull nomic-embed-text`) and falls back to a hosted
provider with a key. The absent case fails closed with an error rather than writing empty
vectors, because a silent no-op surfaces weeks later as "memory doesn't work" with nothing
in any log.

**Corpus-scoped chat returns 400**
The configured embedder is remote. Corpus scope promises the question is never embedded off
your machine, so it refuses rather than quietly sending it. Route embeddings to a local
Ollama.

**Project memory has fewer chunks than reports**
`GET /projects/{id}/memory/status` reports `pending_reports` (approved but not indexed) and
`stale_models` (chunks written by an embedding model that is no longer configured). Those
are the two ways memory goes quietly incomplete, and both are surfaced rather than inferred.

## Desktop app

**The demo report fails on first launch**
A known issue on a fresh install: the demo is created as corpus-only research against a corpus
that is still empty, so it finds no evidence and ends as failed. Your own research is
unaffected. See [Desktop app](23-desktop-app.md#first-run).

**macOS says "“Research Assistant.app” is damaged and can't be opened"**
The app is not damaged. Every macOS build from 1.0.1 to 3.0.0 was signed only by the linker,
so a copy downloaded by a browser fails signature verification, and macOS reports that as
damage — with no *Open Anyway* to click. Move the app to Applications and run, once:

```bash
xattr -dr com.apple.quarantine "/Applications/Research Assistant.app"
```

That clears the download flag from the app and from the engine inside it, and the app opens.
Reinstalling does not help: every fresh download carries the flag again. Builds from 3.0.1 are
signed as a whole bundle and are never reported as damaged; the same command opens them.

**macOS blocks the app, or Windows shows SmartScreen**
The builds are not signed with a publisher certificate. The unblock steps are in
[Desktop app](23-desktop-app.md), and on the download page beside each installer.

## Development

**Frontend changes do not appear in Docker**
The frontend container is a static `next build` image, not a bind-mounted dev server. A
reload shows you stale UI:

```bash
docker compose -f docker-compose.full.yml build frontend
```

**CI fails a grep that passes locally**
The frontend job runs four bespoke greps that `npm run lint` does not. They are GNU grep;
if your shell's `grep` is `ugrep` or a Homebrew shim it can report no match where CI finds
one. Verify with `/usr/bin/grep`, running the commands from `.github/workflows/ci.yml`
verbatim. Note they cannot tell a use from a mention: a comment naming a banned token fails
the build as surely as calling one.

**`docs/` renders as "Documentation is unavailable"**
The build could not find the docs tree. `frontend/lib/docs.ts` looks at `$DOCS_DIR`, then
`../docs`, then `./project-docs`. The Docker build copies `docs/` to `project-docs/` and
must be built from the **repository root**, not from `frontend/`.
