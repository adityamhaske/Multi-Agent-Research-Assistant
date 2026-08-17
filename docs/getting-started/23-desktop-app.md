# Desktop app

The desktop build runs the whole product on your machine: a Tauri shell around the same
web UI, a bundled Python engine, and SQLite. No Docker, no Postgres, no Redis, no login.

**Builds are unsigned.** macOS and Windows will both warn on first launch, and clearing
that warning is a step you have to take deliberately. That is the honest state of it, and
the unblock steps for each platform are below.

## Supported platforms

| Platform | Installer | First-launch friction |
|---|---|---|
| **macOS** (Apple Silicon) | `.dmg` | Real. Gatekeeper blocks it; see below. |
| **Windows** | `.msi` | SmartScreen → *More info* → *Run anyway*. Two clicks. |
| **Linux** | `.AppImage`, `.deb` | AppImage needs `chmod +x`. The `.deb` needs nothing. |

## Download

Installers are attached to each tagged release:
**[Releases](https://github.com/adityamhaske/Multi-Agent-Research-Assistant/releases/latest)**,
or the [download page](https://adityamhaske.github.io/Multi-Agent-Research-Assistant/download/),
which detects your OS and shows that platform's steps inline.

Every release also ships a `SHA256SUMS` file. Unsigned software that cannot be verified is
worse than unsigned software that can, so check the download before running it:

```bash
sha256sum -c SHA256SUMS --ignore-missing
```

The macOS `.dmg` is around 81 MB and installs to roughly 182 MB. Most of that is the
bundled Python engine, which carries no PyTorch and no `sentence-transformers` — its
heaviest dependency is numpy — so the app runs on modest hardware provided the reasoning
happens through an API key or an Ollama you supply.

## Install

**macOS.** Open the `.dmg` and drag the app to Applications. On first launch macOS refuses
to open it. Either right-click the app → **Open** → **Open**, or go to *System Settings →
Privacy & Security* and choose **Open Anyway**.

**Windows.** Run the `.msi`. SmartScreen shows an unrecognised-publisher warning; choose
**More info** → **Run anyway**.

**Linux.** For the AppImage, `chmod +x` it and run it. For the `.deb`, install it with your
package manager.

## First run

The app opens into a **completed demo session** — a real report produced by scripted models
and fixture sources, with citations that resolve — so you can see what the product produces
before configuring anything.

Demo mode is a first-class runtime state, not an environment variable: it is selectable in
the UI, it is the default when no key is configured, and it shows a persistent banner while
active. Demo runs are marked in the database and every export path stamps the artifact, so
a demo report cannot be mistaken for real research.

**Only one thing is mandatory: a way to reach a model.** Everything else has a free path.

| Need | Required? | Free path | If absent |
|---|---|---|---|
| Reasoning model | **Yes** | Ollama, or a provider free tier | Nothing runs |
| Web search | For web research | DuckDuckGo, no key | Falls back automatically |
| Embeddings | Only for corpus search | Ollama `nomic-embed-text` | Web research still works; corpus upload fails loudly |
| Database | Yes | SQLite, bundled | — |

## Configure a model

From the demo banner, or Settings:

- **Ollama** is detected live if reachable and offered first, listing the tags you actually
  have installed. See [Local LLM setup](22-local-llm.md).
- **A provider key** is validated against the provider *before* it is stored. A key is never
  written to the keychain until it has answered a real request — storing an unvalidated key
  just relocates the failure into the middle of your first run.

Keys are stored in the **operating system keychain**, not in a file and not in a database
column. That is the desktop's substitute for the server's encrypted-at-rest column.

Search and embedding keys are presented as optional, because they are.

## What differs from the server build

The desktop and server are two hosts over one engine. The pipeline, both human gates,
citation resolution, and the exports are identical. These differ:

| | Desktop | Server |
|---|---|---|
| Storage | SQLite | PostgreSQL + Redis |
| Auth | None — it is your machine | Cookie sessions |
| Keys | OS keychain | Encrypted column |
| Corpus | One `corpus.sqlite` for the app | One file per project |
| PDF export | The WebView's print-to-PDF | Server-side WeasyPrint |
| Durable event log | Absent — the bundle records `trace_available: false` rather than an empty trace | `agent_logs` rows |
| Project chat and project memory | **Absent by design** — project memory is pgvector-only | Available |

Follow-up chat over a report works on both.

## Updates

There is no auto-updater. Download the newer installer from
[Releases](https://github.com/adityamhaske/Multi-Agent-Research-Assistant/releases/latest)
and install over the top; your data lives in the app's data directory and is not touched.

Auto-update is [planned](../project/10-roadmap.md) rather than dismissed. The open question
is whether Gatekeeper re-blocks an unsigned app after an in-place replacement, and that
deserves its own cycle.

## Uninstall

**macOS** — drag the app out of Applications. **Windows** — uninstall through *Apps &
features*. **Linux** — delete the AppImage, or remove the package.

The app's data directory (sessions, corpus, settings) is not removed by the installer.
Delete it separately if you want the data gone; keys live in the OS keychain and are
removed from the app's Settings.
