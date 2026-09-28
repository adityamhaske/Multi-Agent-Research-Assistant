# Desktop app

The desktop build runs the product on your machine: a Tauri shell around the same web UI, a
bundled Python engine, and SQLite. No Docker, no Postgres, no Redis, no login.

> **What the desktop runs, and what it does not.**
>
> | | Research runs | Project memory and project chat |
> |---|---|---|
> | Web application | Executed by a Celery worker | Supported (pgvector) |
> | Desktop application | Executed in-process by the sidecar | Absent by design |
>
> The desktop drives a run itself, as an `asyncio` task against its own SQLite checkpointer,
> because it has no broker and no worker to hand one to. Everything downstream is the same
> code as the server's: the same engine, the same shared route handlers, the same domain
> tables, the same artifact and the same bundle.
>
> Project memory is the one feature the desktop does not have. It is pgvector-backed, and
> the navigation hides Chat rather than offering a control that cannot work. Your uploaded
> corpus is local and unaffected.

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

Installers are available on the [Download page](/download) or the [Releases page](/releases),
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

**macOS.** Open the `.dmg` and drag the app to Applications. Then, once, in Terminal:

```bash
xattr -dr com.apple.quarantine "/Applications/Research Assistant.app"
```

and open the app from Applications.

The build is not signed with an Apple Developer ID or notarized, so macOS blocks it until you
say otherwise, and this command is how you say it: it clears the flag macOS attaches to every
downloaded file. `-r` matters — the app starts its engine as a separate program inside the
bundle, and that file carries the flag too.

**Every macOS build from 1.0.1 to 3.0.0 is reported as "damaged and can't be opened".** Those
builds were signed only by the linker, so a downloaded copy fails signature verification, and
macOS treats that as tampering: it offers the Trash and no *Open Anyway*. The command above is
the only way to open them. From 3.0.1 the whole bundle is signed, CI refuses a disk image
whose app is not, and a downloaded copy is an ordinary unverified app rather than a damaged
one.

**Windows.** Run the `.msi`. SmartScreen shows an unrecognised-publisher warning; choose
**More info** → **Run anyway**.

**Linux.** For the AppImage, `chmod +x` it and run it. For the `.deb`, install it with your
package manager.

## First run

On first launch the app seeds one **demo session** — a report produced by scripted models
and fixture sources — so you can see what the product produces before configuring anything.
In this release that demo does not complete on a fresh install: it is created corpus-only,
against a corpus that is still empty, so it finds no evidence and ends as failed.

The desktop app has no switch for demo mode: research you start needs a model, and without
one the app points you at Settings. (A self-hosted stack's keyless path is
`./start.sh --fake`; see the [quick start](20-quick-start.md).) Demo runs are marked in the
database and every export path stamps the artifact, so a demo report cannot be mistaken for
real research.

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
citation resolution, [agent instructions](../user-guide/38-agent-instructions.md), and the
exports are identical. These differ:

| | Desktop | Server |
|---|---|---|
| Storage | SQLite | PostgreSQL + Redis |
| Auth | None — it is your machine | Cookie sessions |
| Keys | OS keychain | Encrypted column |
| Corpus | One `corpus.sqlite` for the app | One file per project |
| PDF export | The WebView's print-to-PDF | Server-side WeasyPrint |
| Project chat and project memory | **Absent by design** — project memory is pgvector-only | Available |

Follow-up chat over one report works on both, for research recorded as a session; a run has
no report-scoped chat yet on either host.

## Updates

There is no auto-updater. Download the newer installer from the
[Download page](/download) or [Releases](/releases)
and install over the top; your data lives in the app's data directory and is not touched.

Auto-update is [planned](../project/10-roadmap.md) rather than dismissed. The open question
is whether Gatekeeper re-blocks an unsigned app after an in-place replacement, and that
deserves its own cycle.

**What the app does to your database on launch.** It adds any table or column the new
version expects and, where a schema change cannot be expressed by adding one, repairs that
specific case. One such repair exists: a database created before research runs existed
carries an obsolete foreign key on the trace table, which silently prevented a run from
recording its trace. It is rebuilt on first launch of a version that has this fix — **your
existing trace rows are copied across, not discarded** — and a database that does not need
it is left untouched.

The rebuild runs inside a transaction, so an interruption leaves the database exactly as it
was. **There is no automatic file-level backup**: the transaction is the safety net, not a
copy. If your research history matters to you, copy the app's data directory before
upgrading, as you would before any upgrade.

## Uninstall

**macOS** — drag the app out of Applications. **Windows** — uninstall through *Apps &
features*. **Linux** — delete the AppImage, or remove the package.

The app's data directory (sessions, corpus, settings) is not removed by the installer.
Delete it separately if you want the data gone; keys live in the OS keychain and are
removed from the app's Settings.
