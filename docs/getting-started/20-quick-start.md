# Quick start

From a clean clone to an approved, cited report. The Docker path needs one command.

## Prerequisites

| | Needed for |
|---|---|
| **Docker** with Compose v2 | The one-command path. Everything runs in containers; the only host port used is the frontend's. |
| **A model** | Either a provider API key, or [Ollama](22-local-llm.md) running locally. Without one, use `--fake` below. |
| Python 3.11+ and Node 22+ | Only for the native development path. |

A search API key is **not** required — the retriever chain falls back to keyless
DuckDuckGo. See [Configuration](21-configuration.md) for what each optional key buys you.

## 1. Clone

```bash
git clone https://github.com/adityamhaske/Multi-Agent-Research-Assistant.git
cd Multi-Agent-Research-Assistant
```

## 2. Start it

```bash
./start.sh
```

`start.sh` creates `.env` if it is missing (generating a `JWT_SECRET_KEY` for you), checks
the configuration, builds and starts all five services, waits until each reports healthy,
and opens the app.

If no provider key is found in `.env`, it warns and falls back to fake mode rather than
starting something that cannot run.

Other modes:

```bash
./start.sh --fake      # keyless demo: scripted models and fixture sources, no API key
./start.sh --rebuild   # force a rebuild of the images
./start.sh --logs      # start, then follow logs
./start.sh --stop      # stop the stack; data is preserved
./start.sh --reset     # stop and delete the database volume (asks first)
```

### Or drive Compose yourself

```bash
cp .env.example .env
# In .env set JWT_SECRET_KEY to `openssl rand -hex 32`, and one provider key.
docker compose -f docker-compose.full.yml up --build
```

The `api` container runs `alembic upgrade head` before serving, and the worker and
frontend wait on its readiness, so migrations apply exactly once per deploy. **The frontend
is the only published service** — it proxies `/api/*` over the internal network, so auth
cookies stay first-party and the database is never exposed.

## 3. Open the app

<http://localhost:3031>

Register an account. On a fresh self-host this is your account; email verification is off
by default and should be turned on for anything public
([Production deployment](../deployment/30-production.md)).

## 4. Run your first research

**Research** in the sidebar starts a run and opens its workspace.

1. **Ask a question.** Ten characters minimum; a real question works better than a keyword.
2. **Pick a depth** — `fast`, `balanced`, or `comprehensive`. Depth is the main cost dial:
   it sets how much the planner decomposes the question.
3. **Submit.** You land on the run workspace and the live feed starts. Events stream over
   SSE and are also written durably; a dropped stream reconnects with `Last-Event-ID` and
   the backend replays what was missed, so a refresh or a late-joining tab loses nothing.
4. **Review the plan.** The run pauses at the design gate before anything is searched. Edit
   the subtopics, drop tasks you did not ask for, pick a report outline, then approve.
   Approving a plan spends money; it does not create an artifact.
   ([Review and approval](../user-guide/26-review-and-approval.md))
5. **Watch the pipeline.** Executor and critic work through the tasks; the critic sends weak
   evidence back within a bounded retry limit.
6. **Read the record, not just the draft.** The workspace tabs run in the order the product
   argues for — **Plan → Report → Claims → Evidence → Sources → Contradictions → Review →
   Artifact**. Claims shows what the report asserts and what each assertion resolved to;
   Sources separates cited from retrieved-only; Contradictions shows attributed quotations
   that cannot both hold.
7. **Review the draft.** The Review tab shows what you are approving *before* you approve
   it: claims with and without supporting evidence, cited versus retrieved-only sources,
   unresolved conflicts, and a citation rate that reads "unmeasured" when it was not
   measured. Approve, or send it back with feedback for a rework — a rework adds a revision
   and never overwrites the one you just read.
8. **Take the artifact.** Approving the report freezes a `ResearchArtifact`. The **Artifact**
   tab shows the verifier's own checks and offers the `.bundle.json`. Reports also export as
   `.md` and `.pdf`. ([Exports](../user-guide/29-exports.md))

## 5. Verify the artifact yourself

The bundle is the point of the whole chain: it is checkable by someone who does not trust
this application, and does not need it running.

```bash
cd backend
python -m research_engine.verify_bundle ~/Downloads/research-abc12345.bundle.json
```

Exit status is `0` when every check passes and `1` when any fails; add `--format json` for
machine-readable output. The verifier needs no network, no API key, and no model.

A pass means the artifact is internally consistent and unaltered since approval. It does
**not** mean the research is correct — see
[the V2 research model](24-v2-research-model.md#verifying-an-artifact-yourself) for exactly
what each check proves and what none of them do.

## Try it without a key first

```bash
./start.sh --fake
```

Fake mode runs the real graph with scripted models and fixture retrievers. It makes no
network calls and costs nothing, so it is the honest way to see the shape of the product —
the gates, the live feed, the citation chips, the export — before deciding whether to spend
anything.

**Demo runs are marked as demo in the database**, and every export path stamps the artifact.
The bundle carries the flag in a hash-covered field and the verifier prints it above the
verdict. A demo report cannot be laundered into a real-looking one.

## Native development

If you are going to change the code, run the services directly:

```bash
make infra-up                              # Postgres + Redis only, in Docker
make backend-setup && make migrate
make backend-dev                           # API    → :8000
make worker                                # Celery worker (new terminal)
make frontend-setup && make frontend-dev   # UI     → :3031 (new terminal)
```

Full detail, including the test and lint commands CI runs, is in the
[Development guide](../developers/32-development.md).

## If something goes wrong

[Troubleshooting](24-troubleshooting.md) covers the failures people actually hit: the app
refusing to boot on a short secret, a stuck `PENDING` session, an empty live feed, and
Ollama not being detected from inside Docker.
