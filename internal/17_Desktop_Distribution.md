# 17. Desktop Distribution and First Run

> Engineering note, not documentation. It is cited from source by number — `docs/17 §6.2`
> and similar appear in 27 files — which is why the section numbers below are a contract
> rather than a convenience. Renumbering them breaks those comments silently.
>
> For how the product works, read [`../docs/`](../docs/00_INDEX.md). Milestone context is in
> [`12_Launch_Plan.md`](12_Launch_Plan.md) (M9 is the desktop milestone).

This note covers what a stranger meets in the first sixty seconds: the demo session the app
opens on, how a scripted artifact is marked so it cannot be mistaken for research, how the
installers are obtained, and what "ready to research" means before any key exists.

---

## 6. Demo mode

Demo mode exists because the first thing a new user sees decides whether they trust the
tool. An empty form and a request for an API key demonstrates nothing; a scripted run
demonstrates the whole pipeline — plan gate, evidence, citations, review gate, export —
before any key exists.

It is two flags, not one:

```python
RunConfig(llm_mode="fake", demo=True)
```

`llm_mode="fake"` selects *scripted models and fixture retrievers*. `demo=True` selects
*which content* those scripted models produce. The split is deliberate and
`research_engine/runconfig.py` says why: every `llm_mode == "fake"` comparison in the engine
gates a no-network guard, so making `demo` a third `llm_mode` value would mean a missed
comparison could send a demo run to a real provider. As a separate flag, the worst case is a
demo showing test filler — never a surprise API call.

### 6.1 The seeded session

**Home:** `research_engine/demo_fixtures.py`.

The desktop seeds one session on first launch, so the app opens on a finished report rather
than an empty form — guarded by `demo_already_seeded()` in `desktop/sidecar.py`. The seeding
is recorded by a marker file, not inferred from "no sessions exist" — see §8a.

These fixtures are **deliberately not `research_engine/fakes.py`**. Those are the *test*
fixtures: their output is deterministic filler ("A citable fact [1]" citing "Fixture Source
1") because tests assert on it. Pointing a stranger's first launch at them made the product
introduce itself with placeholder data, which is the one thing a tool claiming verifiability
cannot afford.

**The evidence in the demo is real.** Both sources exist, and every `snippet` is verbatim
text fetched from the URL it is attributed to (arXiv abstracts, retrieved 2026-08-15). The
UI presents a snippet as the verbatim quote supporting a claim, so an invented snippet under
a real DOI would be a fabricated citation — precisely the failure this product exists to make
impossible. **If you edit a snippet, re-fetch it. Do not paraphrase.**

Every claim in `DEMO_REPORT` is supported by the snippet it cites and carries no number
absent from that snippet, so the graph's own citation-fidelity pass leaves the draft
untouched. `backend/tests/task/test_demo_fixtures.py` enforces both properties.

### 6.2 Demo provenance — marking a scripted artifact

A demo run produces a report, a bundle and exports that are structurally
indistinguishable from real research. The rule is therefore:

> **Every surface a scripted artifact can leave the app by must mark it.**

`demo` is persisted on the row (`app/models/session.py`), not inferred from the process's
`LLM_MODE`, because a run is demo or not at the moment it executes and the process flag can
change underneath it. It is decided from the request flag **or** the resolved `llm_mode`, in
one branch, in all three run builders — see `AGENTS.md` on the three homes and
`tests/workflow/test_scripted_runs_are_recorded_as_demo.py`, which pins them.

| Surface | How it is marked | Where |
|---|---|---|
| `.md` and `.pdf` export | `DEMO_STAMP_MD` prepended — a blockquoted "⚠ DEMO — NOT REAL RESEARCH" | `research_engine/bundle.py` |
| The bundle | a `demo: bool` field beside the run's identity | `research_engine/bundle.py` |
| The verifier's output | `VerifyResult.demo` → "!! DEMO BUNDLE … NOT REAL RESEARCH." | `research_engine/verify_bundle.py` |
| Session view / history list | `DemoBadge` | `frontend/components/DemoBadge.tsx`, `SessionView.tsx` |
| API responses | `demo` on the summary, not only the detail | `frontend/lib/types.ts` |

Three of those carry a reason worth keeping:

**The stamp lives in `research_engine/bundle.py` as `DEMO_STAMP_MD`, not in the API layer.**
Both the server and the desktop sidecar export `.md`, and both must stamp it. It was once a
private constant in `app/api/v1/research.py`, which the sidecar could not reach — so desktop
`.md` exports shipped unstamped while `docs/user-guide/29-exports.md` promised that "every
export path stamps the artifact" (#52). The server still binds the old name
(`_DEMO_STAMP = bundle.DEMO_STAMP_MD`) so its existing call sites read unchanged; the value
has one home.

**The bundle deliberately does not carry the prose stamp.** `report_hash` is
`sha256(report_markdown)`, and prepending a banner to the hashed text would break the
approval chain. The bundle marks itself with the `demo` field instead — which is covered by
`bundle_hash`, so a demo bundle cannot be edited into a real-looking one without breaking
verification.

**The verifier reports `demo` alongside `passed`, not inside `notes`.** A demo bundle
verifies perfectly well — its hashes match and its citations resolve — so it would otherwise
print a clean PASS with nothing saying none of it was real.

---

## 7. Download and install

**Home:** `frontend/app/(site)/download/page.tsx`, built by `.github/workflows/desktop.yml`.

Four installers, built on a three-OS matrix (`ubuntu-latest`, `macos-latest`,
`windows-latest`) with `bundle.targets: "all"` in `desktop/tauri.conf.json`:

| OS | Artifact |
|---|---|
| macOS | `.dmg` |
| Windows | `.msi` |
| Linux | `.AppImage` and `.deb` |

The download page derives its asset URLs from `latestRelease()` in
`frontend/lib/releases.ts` — so a release whose entry is missing from that file offers the
*previous* installer. Adding the entry is part of cutting a release, not a follow-up.

`latestRelease()` is the **default**, not the only path: the page also carries a version
selector, over `DESKTOP_VERSIONS` rather than `RELEASES` — unreleased entries and `v1.0.0`
are filtered out, because desktop bundles only started shipping in v1.0.1 and offering an
entry with no installer attached is a guaranteed 404. The asset name template is the same
for every selection, which is what makes the selector cheap — and also what bounds it. A
past version resolves only while its release still carries assets under those exact names,
so a renamed or deleted asset turns an old selection into a 404 with nothing on the page to
say so. That widens the trap above rather than removing it: `releases.ts` is still the one
file that decides what the page offers.

**A desktop bundle that has not been launched is not verified.** The shipped `.app` must be
~180 MB, not ~5 MB: a 5 MB bundle means the sidecar was not copied in, which passes CI and
dies on first launch. `desktop.yml` asserts the size, and the `shell` job must `needs:
sidecar` or the two race.

Because the builds are unsigned (§8), the release notes carry an unblock table:

| OS | What the user sees | What to do |
|---|---|---|
| macOS | "Apple could not verify this app is free of malware" | System Settings → Privacy & Security → **Open Anyway** |
| Windows | SmartScreen warning | **More info** → **Run anyway** |
| Linux | AppImage is not executable | `chmod +x *.AppImage` (`.deb` needs nothing) |

Downloads should be checked against the published `SHA256SUMS` before running.

---

## 8. Distribution

### Code signing and notarization — **not built**

There are no signing secrets in `.github/workflows/desktop.yml` and no certificate
configuration in `desktop/tauri.conf.json`. Bundles ship unsigned: macOS shows a Gatekeeper
block, Windows shows SmartScreen. This is deferred deliberately rather than overlooked — it
needs an Apple Developer certificate and a Windows code-signing certificate, which are
account-owner assets, not code.

Until then, the unblock table in §7 *is* the install path, and it is published with the
release rather than left for users to discover.

### Auto-update — **not built**

No updater plugin in `desktop/Cargo.toml`, no `updater` key in `desktop/tauri.conf.json`. A
new version means downloading the installer again.

It should follow signing, not precede it: the open question is whether Gatekeeper re-blocks
an unsigned app after in-place replacement, and shipping an updater that can strand users on
a blocked binary is worse than shipping no updater.

### 8a. First run and readiness

**Can this user run research right now?** — `GET /models/readiness`, served by
`app/api/v1/models.py::get_readiness` and its desktop twin in `desktop/sidecar.py`.

```
ready = has_cloud_key or chat_models > 0
```

Computed on every request, never stored. A stored "has completed onboarding" flag
desynchronises from reality — it stays true after a key is revoked and false after Ollama
starts — whereas this answer is always current and stops being shown the moment a model
exists.

Two details that look like implementation and are not:

- **`available_providers()` cannot answer this.** It lists Ollama unconditionally, because
  local inference needs no key, so it is never empty and would report every user as ready.
  Reachability is the question, not permission.
- **A reachable server is not readiness.** An embedding model cannot fill an agent role, so
  the route counts *chat* models rather than trusting `reachable`. `tests/task/
  test_models_readiness.py` and `tests/workflow/test_desktop_contract_gaps.py` pin the
  unreachable, chat-model and embedding-only cases on both hosts.

`has_cloud_key` is the one piece that legitimately differs per host — the BYOK column plus
deployment settings on the server, the OS keychain plus environment on the desktop — which is
why `GET /models/readiness` is a declared entry in `MODELS_DIVERGENT`
(`tests/workflow/test_one_canonical_owner.py`) rather than a shared handler.

**What the UI does with it.** `FirstRunNotice` renders on `ready === false` and routes to
Settings rather than opening a wizard — a second key-entry surface would diverge from the
model picker the first time a provider was added. `AccountShell` promotes setup above usage
when nothing is configured. Absent data is not "not ready": a failed or in-flight request
must not accuse the user of missing configuration they may well have.

**A deleted demo stays deleted.** `demo_already_seeded` checks a marker file rather than
counting sessions. "No sessions exist" is the obvious test and it is wrong — it resurrects
the demo on every launch after the user deletes it, which is a peculiarly annoying way to
disrespect a deletion. The marker is written *before* the seeding run, not after, so a crash
mid-seed does not cause a second one.
