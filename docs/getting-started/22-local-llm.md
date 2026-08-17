# Local LLM setup (Ollama)

Run the assistant against a model on your own machine: **no API key, no cost, and no
prompt, report, or document reaching a model provider.**

> **Read this first.** Local models are excellent for *chat* and weaker for *research runs*.
> The pipeline asks the model to call tools and return evidence in a strict schema, and
> small models (under 14B) reliably fail that step even though they search correctly. Use a
> 14B+ model for research, or a local model for chat and a hosted one for research.
> Measurements are in [§6](#6-which-models-actually-work).

## 1. Install Ollama

| Platform | Command |
|---|---|
| macOS | `brew install ollama`, or the installer at [ollama.com/download](https://ollama.com/download) |
| Linux | `curl -fsSL https://ollama.com/install.sh \| sh` |
| Windows | Installer at [ollama.com/download](https://ollama.com/download) |

Start the server (the Windows app starts it for you):

```bash
ollama serve
```

Leave it running, and check that it answers:

```bash
curl http://localhost:11434/api/tags
```

## 2. Pull a model

```bash
ollama pull qwen2.5:14b
```

Settings → **Local models (Ollama)** can also do this with a one-click **Pull** button and
live progress, on both the desktop and web builds — pulling is one HTTP call to an
already-running server, not a new process.

On the **desktop build only**, that panel can also start Ollama for you when it is
installed but not running. The web build cannot start a process on your machine; it detects
the state, shows the install command for your OS, and polls so the card updates itself the
moment you start Ollama yourself.

## 3. Point the app at it

**Route to the exact tag you pulled**, including the size suffix:

```bash
MODEL_PLANNER=ollama:qwen2.5:14b
MODEL_EXECUTOR=ollama:qwen2.5:14b
MODEL_CRITIC=ollama:qwen2.5:14b
MODEL_SYNTHESIZER=ollama:qwen2.5:14b
MODEL_CHAT=ollama:qwen2.5:14b
```

Routing splits on the **first** colon only, so `ollama:qwen2.5:14b` is provider `ollama`,
model `qwen2.5:14b`. Naming the family alone — `ollama:qwen2.5` — resolves to
`qwen2.5:latest`, which is a *different model* from the one you pulled. Settings → Local
models always writes the exact installed tag for this reason.

Then set the endpoint. **This is the step people get wrong:**

```bash
# Running the app natively (make backend-dev):
OLLAMA_BASE_URL=http://localhost:11434/v1

# Running the app in Docker (docker compose):
OLLAMA_BASE_URL=http://host.docker.internal:11434/v1
```

Inside a container, `localhost` is the *container itself*, not your machine.
`host.docker.internal` is the way back to the host, and the compose files declare
`extra_hosts: host.docker.internal:host-gateway` so it resolves on Linux too.

Restart the services that talk to models:

```bash
docker compose -f docker-compose.full.yml up -d api worker
```

## 4. Confirm it worked

Open **Settings → Local models (Ollama)**. You should see:

- **Connected**, with your installed models listed;
- each model tagged **research ready** or **chat only**;
- a **Test connection** button to re-probe after starting Ollama or pulling a model.

If it says **Not detected**, work through [§7](#7-troubleshooting). The app distinguishes
*installed but not running* from *not installed at all*, because those need different
fixes and used to look identical.

## 5. Per-role routing

You do not have to use one model everywhere. In **Settings → Model routing**, mix them:

| Role | Suggested | Why |
|---|---|---|
| Planner | hosted, or 14B+ | Decomposes the question; needs structured output |
| Executor | **14B+** | Tool-calling plus a strict evidence schema — the hardest step |
| Critic | 14B+ | Judges evidence; must return a valid verdict object |
| Synthesizer | 14B+ | Long-form writing with citation markers |
| **Chat** | **any local model** | Free-form text, no schema — 7B is genuinely fine here |

**The pragmatic hybrid:** a hosted model for research, a local model for chat. Research
stays cited and reliable; day-to-day questions about it stay on your machine and cost
nothing.

## 6. Which models actually work

Measured against this pipeline on 2026-08-06:

| Model | Research runs | Chat | Notes |
|---|---|---|---|
| `qwen2.5:7b` | ❌ | ✅ | Plans and calls search correctly, then fails the structured-evidence step → empty reports |
| `qwen2.5:14b` | ✅ | ✅ | Recommended starting point |
| `qwen2.5-coder:14b` | ✅ | ✅ | Unusually strong at exact JSON |
| `llama3.3` (70B) | ✅ | ✅ | Best quality; needs substantial RAM |
| `deepseek-r1:1.5b` | ❌ | ⚠️ | Too small |

**14B is the floor for research; anything runs chat.** The app applies that threshold
itself — a tag stating fewer than 14B parameters is labelled **chat only**. A tag with no
size in it is not flagged, because guessing wrong in that direction would warn people off
capable models.

`deepseek-r1` is in the catalog as **not supporting tool calling**, so it cannot drive the
executor at any size.

Local inference is much slower than a hosted API — minutes rather than seconds, especially
on CPU. If you have set a wall-clock limit, raise it:

```bash
MAX_WALLCLOCK_SECONDS=1200
CELERY_TASK_TIMEOUT_SECONDS=1320
```

Both default to unlimited and 660s respectively; see [Configuration](21-configuration.md).

## 7. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Settings shows **Not detected** | Server not running | `ollama serve`, then **Test connection** |
| Not detected, but `curl localhost:11434` works | The app is in Docker and using `localhost` | Set `OLLAMA_BASE_URL=http://host.docker.internal:11434/v1`, restart `api` and `worker` |
| **No models** | Server up, nothing pulled | `ollama pull qwen2.5:14b` |
| Ollama 404s the model | Routed to a family (`ollama:qwen2.5`) with no `:latest` pulled | Route to the exact installed tag |
| A different model answers than the one you chose | Same cause — the family route resolved to `:latest` | Route to the exact installed tag |
| Reports come out empty or fixture-thin | Model too small for the evidence schema, **or** the app is in `LLM_MODE=fake` | Use a 14B+ model; confirm `LLM_MODE=real` |
| Runs time out | Local inference is slow | Raise `MAX_WALLCLOCK_SECONDS`; use `depth=fast` |

Ollama routes are **not** subject to the unpriced-model startup check — local inference is
genuinely free, so there is no spend to cap and nothing to refuse.

## 8. What stays private

With every role routed to Ollama, **model inference is fully local**: prompts, reports, and
chat never reach a model provider.

**One caveat, stated plainly.** Ordinary research still performs **web searches** and fetches
pages, so your *search queries* leave your machine even though your *reasoning* does not.

For research where nothing leaves the machine, use **corpus-only mode**: evidence comes
exclusively from documents you uploaded, `read_webpage` refuses every non-corpus URL, and
the run makes no network calls of any kind. Combined with local embeddings
(`nomic-embed-text` through the same Ollama), a fully local deployment can do private
retrieval at zero cost and zero egress. See
[Local and self-hosted architecture](../architecture/13-local-and-self-hosted.md).

---

*Related: [Configuration](21-configuration.md) ·
[Agent architecture](../architecture/04-agent-architecture.md) ·
[Local and self-hosted architecture](../architecture/13-local-and-self-hosted.md)*
