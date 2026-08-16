# Connecting a Local LLM (Ollama)

Run the research assistant against a model on your own machine: **no API key, no cost,
and no prompt or document ever leaves your computer.**

> **Read this first — the honest version.** Local models are excellent for *chat* and
> weaker for *research runs*. The research pipeline asks the model to call tools and
> return evidence in a strict JSON schema; small models (7B and under) reliably fail that
> step even though they search correctly. **Use a 14B+ model for research, or use a local
> model for chat and a hosted one for research.** Measurements are in §6.

---

## 0. The one-click path (desktop build)

On the **desktop app**, Settings → Local models (Ollama) can do steps 1–2 for you:

- **Ollama already installed but not running** → a **Start local models** button
  appears; click it and the card flips to Connected once the server is up.
- **Nothing installed** → the card explains that and links the installer; there is
  nothing to click yet because there is no process to start.
- Once connected with no models pulled, a **Pull `qwen2.5:14b`** button appears with
  live download progress — no terminal required.

**Honest boundary:** this only exists on desktop. The **web build** cannot start a
process on your machine — it can only guide you. If you are on the web build, Settings
shows the install command for your OS (detected automatically) with a copy button, and
polls every couple of seconds so the card updates itself the moment you start Ollama
yourself. The rest of this section is that manual path, spelled out.

## 1. Install Ollama

| Platform | Command |
|---|---|
| macOS | `brew install ollama` (or download from [ollama.com](https://ollama.com/download)) |
| Linux | `curl -fsSL https://ollama.com/install.sh \| sh` |
| Windows | Installer at [ollama.com/download](https://ollama.com/download) |

Start the server (macOS/Linux; the Windows app starts it for you):

```bash
ollama serve
```

Leave it running. Verify it answers:

```bash
curl http://localhost:11434/api/tags
```

## 2. Pull a model

Settings → Local models (Ollama) can do this with a one-click **Pull** button and a
live progress readout once a server is connected (desktop and web both — pulling is
one HTTP call to an already-running Ollama, not a new process, so the web build can do
it too). Or from a terminal:

```bash
ollama pull qwen2.5:14b
```

Other good choices — see §6 before picking:

```bash
ollama pull llama3.3
```

## 3. Point the app at it

Add to your `.env`:

```bash
MODEL_PLANNER=ollama:qwen2.5
MODEL_EXECUTOR=ollama:qwen2.5
MODEL_CRITIC=ollama:qwen2.5
MODEL_SYNTHESIZER=ollama:qwen2.5
MODEL_CHAT=ollama:qwen2.5
```

Then set the endpoint — **this is the step people get wrong**:

```bash
# Running the app natively (make backend-dev):
OLLAMA_BASE_URL=http://localhost:11434/v1

# Running the app in Docker (docker compose):
OLLAMA_BASE_URL=http://host.docker.internal:11434/v1
```

**Why the difference:** inside a container, `localhost` is the *container itself*, not
your machine. `host.docker.internal` is the escape hatch back to the host. The compose
files already declare `extra_hosts: host.docker.internal:host-gateway` so this resolves
on Linux too.

Restart the services that talk to models:

```bash
docker compose -f docker-compose.full.yml up -d api worker
```

## 4. Confirm it worked

Open **Settings → Local models (Ollama)**. You should see:

- **Connected** with your installed models listed
- each model tagged **research ready** or **chat only**
- **Test connection** to re-probe after starting Ollama or pulling a model

If it says **Not detected**, work through §7 — and note the desktop build now tells
you *which* kind of not-detected it is (installed but not running, vs. not installed
at all), since those need different fixes and used to look identical.

## 5. Per-role routing (recommended)

You do not have to use one model everywhere. In **Settings → Model routing**, mix them —
this is usually the best local setup:

| Role | Suggested | Why |
|---|---|---|
| Planner | hosted *or* 14B+ | Decomposes the question; needs structured output |
| Executor | **14B+** | Tool-calling + strict evidence schema — the hardest step |
| Critic | 14B+ | Judges evidence; must return a valid verdict object |
| Synthesizer | 14B+ | Long-form writing with citation markers |
| **Chat** | **any local model** | Free-form text, no schema — 7B is genuinely fine here |

**The pragmatic hybrid:** hosted model for research, local model for chat. Your research
is cited and reliable; your day-to-day questions about it stay on your machine and cost
nothing.

## 6. Which models actually work

Measured against this pipeline on 2026-08-06:

| Model | Research runs | Chat | Notes |
|---|---|---|---|
| `qwen2.5:7b` | ❌ | ✅ | Plans and calls search correctly, then fails the structured-evidence step (`no_parsable_evidence`) → empty reports |
| `qwen2.5:14b` | ✅ | ✅ | Recommended starting point |
| `qwen2.5-coder:14b` | ✅ | ✅ | Unusually strong at exact JSON |
| `llama3.3` (70B) | ✅ | ✅ | Best quality; needs substantial RAM |
| `deepseek-r1:1.5b` | ❌ | ⚠️ | Too small |

**Rule of thumb: 14B is the floor for research; anything runs chat.** The app labels this
for you — models it expects to struggle are tagged **chat only**.

Speed: local runs are much slower than hosted APIs (minutes, not seconds, on CPU). The
app's wall-clock budget is raised for local use:

```bash
MAX_WALLCLOCK_SECONDS=1200
CELERY_TASK_TIMEOUT_SECONDS=1320
```

## 7. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Settings shows **Not detected** | Server not running | `ollama serve`, then **Test connection** |
| Not detected, but `curl localhost:11434` works | App is in Docker using `localhost` | Set `OLLAMA_BASE_URL=http://host.docker.internal:11434/v1`, restart `api` + `worker` |
| **No models** | Server up, nothing pulled | `ollama pull qwen2.5:14b` |
| Reports come out empty / "Fixture"-thin | Model too small for the evidence schema, **or** app is in `LLM_MODE=fake` | Use a 14B+ model; confirm `LLM_MODE=real` |
| Runs time out | Local inference is slow | Raise `MAX_WALLCLOCK_SECONDS`; use `depth=fast` |
| `No price for routed model(s)` at startup | Model not in the catalog | Use a catalog route (`ollama:qwen2.5`), or add a `ModelSpec` in `research_engine/catalog.py` |

## 8. What stays private

With every role routed to Ollama, **model inference is fully local** — prompts, reports,
and chat never reach a third-party model provider.

**One caveat, stated plainly:** research still performs **web searches** (Tavily/Brave/
DuckDuckGo) and fetches pages, so your *search queries* leave your machine even though
your *reasoning* does not. Fully offline research over a private corpus is a separate,
planned capability ([12_Launch_Plan.md](../product/12_Launch_Plan.md) M10).

---

*Related: [03_Tech_Stack.md](../architecture/03_Tech_Stack.md) ·
[04_Agent_Design.md](../architecture/04_Agent_Design.md) §7 (model routing) ·
[13_Local_First_Architecture.md](../architecture/13_Local_First_Architecture.md)*
