# One runtime, two hosts — making parity structural

**Status:** plan, revision 2, awaiting approval.
**Audited at:** `8ae66d6` (main, clean), 2026-08-26.
**Goal:** a product behaviour is implemented once; the server and the desktop differ only
in infrastructure, and CI proves it rather than a human remembering it.

Revision 2 applies sixteen constraints supplied after revision 1. §0 states what changed
and why; the rest of the document is the plan as revised.

---

## 0. What changed in revision 2

Three of the constraints invalidated a decision in revision 1. Those are the ones worth
reading first.

### 0.1 Reversals — revision 1 was wrong

| # | Revision 1 said | Revision 2 says | Why it flipped |
|---|---|---|---|
| **R-a** | Project memory is *“a capability, not a port”* — `memory.is_available(db)` stays the one home and the pgvector query stays in `app/services/memory.py`. | **`MemoryIndex` becomes port P12.** Postgres/pgvector implementation on the server, a `MemoryUnavailable` implementation on the desktop. | Constraint 1 forbids PostgreSQL-specific behaviour in the application layer. Verified: `app/services/memory.py:275` calls `MemoryChunk.embedding.cosine_distance(...)` — a pgvector operator, inline, in a module revision 1 classified as canonical. That is a direct violation, not a borderline call. |
| **R-b** | `RateLimiter` is port P12, with a no-op desktop implementation. | **The port is deleted.** Rate limiting stays entirely inside the server adapter; the desktop declares `rate_limits: false` as a capability. | Constraint 7. A `RateLimiter` whose desktop implementation always returns “allowed” is a security control that reads as present and enforces nothing. An absent capability that says so is honest; a no-op that satisfies an interface is not. |
| **R-c** | Version metadata carries both `git_sha` and an `engine_sha` (a git tree hash of `backend/research_engine`). | **One `git_sha`, plus a `dirty` flag.** No `engine_sha`. | Constraint 11. The engine tree hash existed to catch a server and a desktop built from different commits — which the single release orchestrator (§10) makes structurally impossible. Once one workflow builds both from one checkout, a second SHA is a redundant source, and the real remaining risk (a locally built dirty tree) is a boolean, not a hash. |

### 0.2 Additions — new work revision 1 did not contain

| # | Addition | Driven by | Size |
|---|---|---|---|
| **A-a** | **`app/errors.py`** — a domain error taxonomy plus one shared status-code map. The application layer raises `NotFound` / `Conflict` / `Invalid` / `CapabilityUnavailable`; each host maps them to its own transport. | Constraints 1, 2 | New phase. Verified impact: `app/api/v1/runs.py` — the handlers both hosts already share — raises `HTTPException` **13 times** and references FastAPI transport types **47 times**. Today's “shared” layer is not transport-free. |
| **A-b** | **`app/handlers/registry.py`** + `test_one_canonical_owner`. Every shared operation names exactly one owning function; each host's route carries `__canonical__` pointing at it, and the test asserts both hosts point at the *same object*. | Constraint 3 | Small, high leverage. Unfakeable: two copies cannot be one object. |
| **A-c** | **`test_sidecar_is_transport_only.py`** — AST rules forbidding ORM query construction, `research_engine` imports and multi-statement route bodies anywhere in `desktop/` outside `desktop/infrastructure/`, plus a ratcheting line-count ceiling on `sidecar.py` that can only fall. | Constraints 4, 5 | New test module. This is the guard that stops the file growing back. |
| **A-d** | **Non-degeneracy guards in the parity suite.** Each journey declares `must_observe` facts; a journey whose steps are all empty fails even when both hosts agree. A checked-in golden whose bodies are all `{}`/`[]` fails `test_golden_is_not_degenerate`. | Constraint 15 | The single most important addition. It closes the subtlest version of “both implementations agree and both are wrong”. |
| **A-e** | **Capability differences must be *observable*.** Each `CAPABILITY_DIFFERENCES` entry is asserted to answer with a documented capability response carrying a machine-readable code — never a 404, never a silent omission. | Constraints 6, 7 | Small. Turns “absent by design” into behaviour a client can branch on. |
| **A-f** | **`test_desktop_is_self_contained`** — the desktop import tree and configuration contain no server origin, and the packaged smoke run completes every journey with egress blocked. | Constraint 10 | Small. |
| **A-g** | **Per-operation migration ladder.** Every operation moves through seven fixed steps, and **deletion of the old implementation is the last**, gated on the golden test passing on both hosts *and* on the packaged desktop. | Constraints 12, 13 | Restructures §6 entirely — the biggest change to the shape of the plan. |
| **A-h** | **Release verification extracts the real installer.** The final check mounts the `.dmg` / unpacks the `.AppImage`, runs the sidecar from *inside the shipped artifact*, and compares its `git_sha` to the server image's. | Constraint 16 | Replaces revision 1's weaker check against `backend/dist/`. |
| **A-i** | **Deterministic routing pinned on both hosts in the harness**, which lets the normalizer get *stricter*: cost and `model_routing` become exactly comparable instead of reduced. | Constraint 15 | Tightens work already begun. |

### 0.3 Unchanged, and now stated as invariants

Constraints 8, 9 and 10 confirm decisions revision 1 already made: the session and run
pipelines stay separate; Postgres/SQLite, Celery/asyncio, Redis/local bus, encrypted
column/keychain and server/local identity all stay; the desktop never talks to the server.
They move from prose into `AGENTS.md` and into tests, so they stop being recollections.

### 0.4 Phase 0 is complete — what it found

Landed under the revised methodology. **57 new tests, all green; full backend suite 799
passed / 90 skipped; `ruff check` and `ruff format --check` clean. No production code was
touched.**

| File | What it is |
|---|---|
| `tests/parity/normalize.py` | redaction — value never key, shape-aware, structural rules for `id`/`_id`, `_at`/`ts`, `_hash` |
| `tests/parity/liveness.py` | the non-degeneracy guard (A-d) |
| `tests/parity/drivers.py` | both hosts in-process, every pin justified in the docstring |
| `tests/parity/journeys.py` | four journeys, each declaring product facts |
| `tests/parity/golden/*.json` | the recorded contract, from the server |
| `tests/parity/test_{normalize,liveness,golden_journeys}.py` | 57 tests |

**`research-run` passes identically on both hosts** — create, design gate, plan approval,
report gate, rework, second revision, approval, artifact, bundle, standalone verifier,
archive, restore, delete, 404. That is the largest single piece of evidence that the
`/runs` surface is genuinely shared.

**Ten divergences recorded in `XFAIL_DIVERGENCES`, six of them new.** The audit predicted
the corpus upload set (§2.5 #2) exactly. Phase 0 additionally found:

| # | Finding | Host at fault |
|---|---|---|
| N-1 | The desktop serves a corpus download with **no `Content-Type` at all**; the server sends `text/plain` | desktop |
| N-2 | The desktop's `corpus status` carries an extra `corpus_only` field the server does not have | desktop |
| N-3 | **The server answers `DELETE …/documents/{id}` with `204` *and* `content-type: application/json` and an empty body**, so the response does not parse | **server** |
| N-4 | The desktop's `/auth/me` omits `is_active`, every `api_key_*` field, `connection_verdict` and every `preferences` key the server's `UserResponse` declares | desktop |
| N-5 | The desktop's `/models` omits `available_providers` entirely | desktop |
| N-6 | A fresh install lists one project on desktop and zero on the server — the desktop seeds `General` eagerly, the server lazily | both, by design drift |

N-4 and N-5 are §2.4's hole made concrete: those are exactly the routes where the desktop
declares no `response_model`, and the parity harness could not see them until now.

**Three findings about the harness itself, which are findings about the product too:**

- `server_driver` originally inherited `LLM_MODE` from the environment rather than pinning
  it. Running the harness outside pytest therefore reached real providers — it called
  Tavily and Gemini once before I caught it. The driver now pins `settings.llm_mode`
  explicitly, the way the desktop driver already passed `fake=True`.
- `app/api/v1/corpus.py` does `from app.adapters import embeddings_for`, binding at import,
  so patching the module attribute is not enough. Any future test double for that port has
  the same trap.
- **On the desktop, an approved report is ingested into the corpus twice** — once by the
  shared server handler and once by the sidecar's completion path — into two stores built
  by two separate `make_corpus_store` calls. `AGENTS.md` says the shared attempt “always
  fails cleanly here”; that is true in the *bundle*, where `app.config` is excluded, and
  false in a source checkout. Verified in a source checkout only; the packaged behaviour
  is untested and should be checked before Phase 8 touches this path.

**Known limits of the harness, recorded rather than hidden:** the server driver runs on
SQLite, so project memory reports absent on both hosts and the memory journey is not yet
written (it will declare `requires={"postgres"}` and skip loudly). The bundle `trace`
reduces to presence only, because the harness supplies the server's `EventSink`; Phase 5's
port work is what makes it comparable. The server's session path still cannot be driven
in-process at all, which is the point being made.

### 0.5 Phase 1 is complete — the shape hole is closed

**Full backend suite 802 passed / 90 skipped; `ruff check` and `ruff format --check` clean.**

The hole itself is now a test: `test_no_shared_route_declares_a_model_on_only_one_host`
fails when a shared operation declares a `response_model` on one host and none on the
other, which is the condition that made the old shape check skip exactly the twelve routes
the desktop hand-writes.

**It could not be closed by declaring the models where they were.** Six of the eight shapes
lived in `app/api/v1/models.py` and two in `app/api/v1/corpus.py`, both of which import
`app.config` — the exact chain that killed the packaged sidecar in #50. So they moved to
`app/schemas/models.py` and `app/schemas/corpus.py`, pure pydantic, re-exported from the
route modules, with identity assertions (`is`, not `==`) in `test_sidecar_startup.py`.
The same relocation `app/schemas/runs.py` and `app/services/document_headers.py` already
made, for the same reason.

`GET /auth/me` and `PATCH /auth/me` now return the ORM row and let `UserResponse` project
it, instead of assembling a dict that omitted `is_active`, every `api_key_*` field,
`connection_verdict` and the whole `preferences` object.

**A test was removing itself from usefulness.** `test_desktop_contract_gaps.py::
test_per_project_corpus_status_matches_the_flat_one` asserted the desktop's per-project
route equalled the desktop's *flat* route — two implementations compared against each
other, the anti-pattern `AGENTS.md` names — and then required `corpus_only` to appear in
the canonical response, "or the Corpus page's airgap toggle would read as off". There is no
such toggle: `corpus_only` appears nowhere in `frontend/`, and nothing calls
`PUT /corpus/mode`. The reason was stale and it was pinning a divergence. It now asserts
against `CorpusStatusResponse.model_fields` — the server's shape — and checks that
`corpus_only` stays on the desktop-only flat route where it belongs.

**Closed:** the `corpus status` shape; the field-omission half of `/auth/me`; the missing
`available_providers` key; the missing body fields on corpus upload.

**One new finding (N-7).** The server enriches `presets.ollama` from the models actually
installed on the machine (`_ollama_presets_from_installed()`); the desktop returns the
static `catalog.PRESETS` table. So the host that can *see* a local Ollama is the one that
does not ask it — the picker offers a desktop user preset tags that may not exist locally,
which is the failure `_ollama_presets_from_installed` was written to prevent. Recorded for
Phase 8.

**Reclassified rather than fixed.** `who am I` still differs on `email` and `display_name`,
and always will: the desktop is one local user with a fixed sentinel identity. That is a
capability difference, not a divergence, and its `XFAIL_DIVERGENCES` reason now says so and
points at Phase 10. The catalog's `available` flags differ because the server reads keys
from settings and the desktop from the keychain — a declared infrastructure difference the
harness does not yet pin.

Nine divergences remain recorded, every reason rewritten to match what is actually true.

---

### 0.6 Phase 2 is complete — the three live defects are fixed

**Full backend suite 835 passed / 90 skipped; ruff clean. Divergences recorded: 10 → 3.**
Regression test written first for each; every fix is one commit's worth of change with a
shared home, not a patch applied twice.

#### 2a — one SSE id space

`SessionEventBus` no longer mints ids. `persist_and_publish` writes the durable
`agent_logs` row, takes **its** id as the cursor, stamps it into the payload and only then
fans out live — the ordering `adapters.agent_log_sink` already had on the server, now the
one home for it on the desktop. The event sink and both lifecycle publishers call it; all
three previously got the order wrong in the same way.

Two things surfaced while fixing it that the audit had not seen:

- **Every persisted payload's `id` was null.** The old sink assigned it *after* the commit.
- Assigning it before the commit is not enough either: the row held the caller's own dict,
  so mutating and reassigning left SQLAlchemy with an old value equal to the new one and no
  net change to write. The row takes a copy now, and the comment says why.

An event whose durable write fails is now delivered live **without** an id, and both stream
generators leave `Last-Event-ID` where it was — a client cannot resume from an event that
was never stored.

#### 2b — one corpus contract

`app/services/corpus_ingest.py` holds the validation, the failure mapping and the response
shaping; both hosts call it. Stdlib/pydantic/FastAPI only, so the sidecar can import it
(#50). Phase 4 replaces its `HTTPException` with the domain taxonomy.

| | was (server / desktop) | now, both |
|---|---|---|
| success | `200` / `201` | **`201`** |
| empty, unsupported, no basename | `400` / `422` | **`400`** |
| over the size limit | *unenforced* / `413` | **`413`** — a real robustness gain on the server |
| embedder unreachable | *500* / `503` | **`503`** |
| body | full / three fields | **full `DocumentResponse`** |
| download `Content-Type` | `text/plain` / **absent** | **`media_type_for(kind)`** |
| delete | `204` **+ `application/json`, unparseable** / `204` | **body-less `204`** |

The desktop's missing `Content-Type` was worse than cosmetic: the same response sends
`X-Content-Type-Options: nosniff`, so the browser was forbidden from guessing the type it
had not been given.

The golden was re-recorded and the diff read: exactly four server changes, nothing else.
Two existing desktop tests asserted the old `422` and were updated with the reason.

#### 2c — one lifecycle mapping

`app/services/session_events.py::lifecycle_event` is the single `RunOutcome` → event
mapping. The desktop published the right event *type* with `data: null` for all four
outcomes, so a desktop client had no task count at the design gate, no word or source count
at the review gate, no elapsed time or cost on completion, and a failure reason in
`message` where the server puts it in `data.reason`.

This closes the `AGENTS.md` trap directly — *"a new `RunOutcome.status` →
`pipeline_runner::_persist_outcome` and **both** dict literals in
`sidecar::_apply_outcome`"* — from three homes to one, with a test that asserts both hosts
resolve to the same function object rather than that two copies agree.

#### What is left

| Divergence | Why it remains | Phase |
|---|---|---|
| `who am I` | the desktop is one local user with a sentinel identity — a capability difference | 10 |
| `the model catalog` | key source (settings vs keychain), plus N-7: the server enriches `presets.ollama` from installed models and the desktop does not | 8 |
| `list projects` | `General` seeded eagerly on desktop, lazily on the server | 8 |

---

### 0.7 Desktop corpus-only mode — removed, and a P0-class bug with it

Spun off from Phase 2 as its own decision. The chip proposed (a) surface the switch or
(b) delete it. **Neither was sufficient on its own**, because inspecting it first turned up
something the chip had not described.

**What was actually wrong, in two opposite directions.**

1. `PUT /corpus/mode` wrote a persistent `corpus_only` flag that **nothing in `frontend/`
   ever set or read** — the bundle-export class inverted: not a control that 404s, but a
   piece of state with no control at all.
2. That flag was the **only** input to `RunConfig.corpus_mode` on this host
   (`sidecar_run_config`). Meanwhile `POST /research` and `POST /runs` accepted
   `corpus_mode` and persisted it onto the row — and neither `_drive_session` nor
   `_drive_run` ever read it back. **A desktop run requested as airgapped was recorded as
   airgapped and executed over the open web.** Verified before fixing: the failing test
   reported sources of `https://arxiv.org/abs/2005.11401`.

`app/schemas/research.py:39` names this exact class in a comment — *"a field the schema
accepts and the run never reads is the exact bug AGENTS.md records for corpus_mode/demo."*
The comment describes a defect that had been fixed for the request→row hop and was still
live on the row→`RunConfig` hop.

**And `docs/` was right the whole time.** `docs/25 §Corpus only` and
`docs/28 §Corpus-only mode` describe a **per-run** option; no document anywhere describes a
persistent desktop switch. So this was code contradicting the build contract, not a
documented feature being removed — `docs/` needed no change.

**What was done.** Deleted the route, `corpus_only_enabled`, `save_corpus_config`,
`_corpus_config_path` and the `corpus.json` file; dropped the `INTENTIONAL_DESKTOP_ONLY`
entry (the anti-rot guard caught it immediately); and carried `corpus_mode` from the row
into `RunConfig` in both drivers, beside the other per-run overrides, matching
`pipeline_runner._execute` and `run_execution.execute_run`.

The flat `/corpus/status` now returns exactly `CorpusStatusResponse` — identical in body to
the canonical per-project route, differing only in path, which is the real infrastructure
difference (one `corpus.sqlite` for the app).

**Three tests, written first.** A run asking for corpus mode gets `corpus://` sources; a
run that did not ask is *not* silently restricted to the corpus — impossible to express
with a global switch, and the clearest argument that per-run is the right contract; and a
corpus-mode run with an empty corpus fails rather than falling back to the web, which is
`docs/25`'s promise, newly reachable on this host and confirmed to hold.

**837 passed / 90 skipped; ruff clean.**

---

### 0.8 Phase 3 is complete — the boundary is declared and enforced

**846 passed / 90 skipped; ruff clean.** Nine tests, and the acceptance criterion the
phase was written around was checked rather than assumed: a violation planted in
`app/handlers/` fires all three application rules, and the tree greps clean afterwards.

`tests/workflow/test_layer_boundaries.py` walks the AST for the full direction —
transport → application → domain → ports → infrastructure, downward only. **Deferred
imports count**: moving an import inside a function keeps a dependency out of *startup*,
which is a real and separate concern (`test_sidecar_startup`), but the layer still depends
on it at request time — and `app/run_execution.py` reaching `app.runtime` inside a function
is exactly how the packaged sidecar's run routes came to 500.

`app/handlers/` and `app/ports.py` exist and are empty, with docstrings saying what belongs
in each. The rule is declared before anything moves into it, because a boundary drawn after
the fact is drawn around whatever the code already does.

The invariant is now in `AGENTS.md`, beside the “two hosts, one contract” table it
replaces the discipline for.

#### It found a violation on its first run

`app/run_dispatch.py` imports `app.workers.tasks`. The module holds the `RunDispatcher`
Protocol **and** the server's `CeleryDispatcher`, whose methods import the tasks lazily —
the deferral being load-bearing today, because the desktop imports this module and
`research-sidecar.spec` excludes `celery`.

The implementation belongs beside the other server adapters. It cannot move yet:
`app/api/v1/runs.py` is simultaneously the shared handler module *and* the server's
router, so it binds `Depends(get_run_dispatcher)` at module scope and the desktop imports
it. Phase 6 splits those two, and the import moves with the split.

Recorded in `KNOWN_EXCEPTIONS` with that reason. The allowlist is a dict, not a set:
every entry names the phase that removes it, a test asserts the reason is real, and an
entry that stops being true fails the suite.

---

### 0.9 Phase 4 is complete — the error contract has one home

**867 passed / 90 skipped; ruff clean.** The acceptance criterion was that the parity
goldens **do not move**, and they did not: the only golden change in the working tree is
still Phase 2b's recorded corpus contract. Every status and `detail` string this product
emits is byte-identical either side of the conversion.

`app/api/v1/runs.py` raised `HTTPException` at 13 sites while **both hosts call it**. So
the status a client saw was never actually shared — it was thirteen literals reached from
two places, and the module could not move into `app/handlers/` without the layer test
refusing it, correctly: "not found" is a product fact and `404` is a delivery detail.

Two modules, and the split is the point:

| Module | Layer | Holds |
|---|---|---|
| `app/errors.py` | domain | `AppError` + seven subclasses. No FastAPI, no host. |
| `app/services/error_responses.py` | shared transport | `ERROR_STATUS`, `status_for`, `error_body`, `install_error_handlers`. Same shape as `document_headers.py` and `sse.py`. |

The table is keyed by **class, not class name** — mapping by name would make a rename a
silent status change, which is the kind of edit that looks safe in review. `status_for`
walks the MRO, so a future `RunNotFound(NotFound)` inherits `404` without an entry.
`CapabilityUnavailable` carries a machine-readable `capability`, which is what will make
Phase 10's capability differences observable rather than a claim in a table.

Both hosts install the handler, and the test asserts they install the **same function
object** — two handlers that agree today are two homes.

`app/services/corpus_ingest.py` came off `HTTPException` too, which let the layer test
gain a rule it could not hold before: **the domain layer imports no transport.**

#### Two things worth stating plainly

**`Invalid` (400) and `Unprocessable` (422) both mean "the domain refuses this".** They are
two errors only because the product already answers two codes: the run surface has always
used `422` for an unknown depth, an unroutable model or an emptied task list, while the
corpus surface uses `400`. Phase 4 is a refactor, so it preserves both. Unifying them is a
client-visible contract change and needs its own decision — **open question, see §14 Q5.**

**The phase introduces one footgun.** An app that mounts these routes and does not install
the handler turns every refusal into an unhandled 500. `test_runs_api` built its own bare
`FastAPI()` and hit exactly that, which is how it surfaced. Both real hosts are asserted;
the requirement is documented at `install_error_handlers`, where the next person mounting
these routes will meet it.

---

### 0.10 Where this stands

**Backend 952 passed / 90 skipped. Frontend typecheck, lint, 315 tests, and all three
build targets. Ruff clean. Parity goldens unmoved since Phase 2b.** Twelve commits.

#### Done

| Phase | |
|---|---|
| 0 | recorded contract, non-degeneracy guards, both drivers |
| 1 | the response-shape hole closed; eight models relocated for #50 |
| 2 | three live defects fixed — SSE ids, corpus contract, lifecycle payloads |
| — | desktop corpus-only mode removed; per-run `corpus_mode` now honoured |
| 3 | the layer boundary declared and enforced; `KNOWN_EXCEPTIONS` empty |
| 4 | one error taxonomy, one status table, both hosts |
| 5 | the demo rule; P10 `CorpusLocator`; P12 `MemoryIndex` |
| 6 | canonical-owner check; dispatch port split; four SSE loops → one |
| 9 | `VERSION`, `sync_version.py`, `stamp_build.py`, `GET /api/v1/version` |
| 10 | `GET /api/v1/capabilities`; five frontend branches off the build flag |

#### Not done

| Remaining | State |
|---|---|
| **Phase 5** P9 `SecretStore`, P11 `RoutingStore` | not started. Both small; neither is a recorded defect |
| **Phase 6** moving the 14 run handlers into `app/handlers/` | not started. `app/handlers/` is empty and its layer rule holds vacuously |
| **Phase 7** the session journey | not started — the largest behavioural surface, four gated commits |
| **Phase 8** projects, corpus, models | not started |
| **Phase 11** release orchestration | **not written, deliberately** |

**Phase 9's packaging half is written and unrun.** `research-sidecar.spec` names
`research_engine._build`; `desktop.yml` stamps before `pyinstaller`. Neither has executed —
no Tauri toolchain, no macOS runner. **The assertion that the SHA reaches the shipped
bundle is still owed**, so `GET /api/v1/version` on a *packaged* app is unproven.
`AGENTS.md` records a 5 MB `.app` that passed CI and died on first launch.

**Phase 11 was left unwritten on purpose.** Its acceptance is `release-artifact-revision`
mounting a `.dmg` on a macOS runner. The design in §10 is unchanged and complete. Its one
change with real blast radius — removing `desktop.yml`'s `release` job so the orchestrator
owns the GitHub Release — only shows up during a release, and YAML that looks finished is
worse than an absence anyone can see. One tag push verifies it; nothing here can.

#### What remained of `isDesktop`, and why it is correct

Transport, all of it: cookies vs bearer token, `withCredentials` on an `EventSource`, a
dynamic route vs a static export, the refresh-token flow. Those are properties of the
build. The five that were about *what a person can do* now ask the host.

One genuine contract difference survives and is not arbitrary: provider health takes a
provider on the desktop and not on the server, because the server stores one active
connection while a keychain holds one entry per provider. It keys off `byok_storage` — the
fact it follows from — rather than off the build.

#### Rules that went stale, recorded rather than left

- `AGENTS.md` still says the README download badge carries a version. It points at
  `docs/getting-started/23-desktop-app.md` and carries none, which is why
  `sync_version.py` omits it.
- The run stream's `DIVERGENT_BY_DESIGN` reason said the `EventStream` port would let the
  generator be shared. It is shared; what remains per host is the backlog source and the
  live feed. Corrected in `2929459`.

---

## 1. Current architecture

Everything below was verified against the working tree. Where a claim needed a check, the
check is named. Findings not already recorded in `AGENTS.md` are marked **NEW**.

```
                                  frontend/  (Next.js, 3 build targets)
                                  ├── build          → server image, cookie auth,  /api/v1 same-origin
                                  ├── build:desktop  → static export, bearer token, 127.0.0.1:PORT/api/v1
                                  └── build:pages    → static marketing/docs site (no API)
                                         │
                        ┌────────────────┴────────────────┐
                        │        ONE HTTP CONTRACT?       │   ← intended; 12 operations escape the check (§2.4)
                        ▼                                 ▼
        ┌──────────────────────────────┐    ┌────────────────────────────────────┐
        │ SERVER HOST                  │    │ DESKTOP HOST                       │
        │ app/main.py → app/api/v1/*   │    │ desktop/sidecar.py                 │
        │  auth.py    research.py      │    │  create_sidecar_app()  ← 2,324 LOC │
        │  projects.py corpus.py       │    │  ONE function, ~120 nested defs    │
        │  chat.py    models.py        │    │                                    │
        │  threads.py runs.py          │    │  /research/*  restated by hand     │
        │                              │    │  /projects/*  restated by hand     │
        │                              │    │  /corpus/*    restated by hand     │
        │                              │    │  /models/*    restated by hand     │
        │                              │    │  /runs/*      DELEGATES to app/    │
        └───────────┬──────────────────┘    └───────────┬────────────────────────┘
                    │                                   │
      Depends: get_db / get_current_user      per-launch bearer token, one local user
               get_redis / rate limits        own AsyncSession factory, no rate limit
                    │                                   │
        ┌───────────┴───────────┐           ┌───────────┴────────────┐
        │ SERVER INFRASTRUCTURE │           │ DESKTOP INFRASTRUCTURE │
        │ app/config.py         │           │ SQLite (create_all +   │
        │ app/db/base.py (PG)   │           │   column sync)         │
        │ app/db/redis.py       │           │ OS keychain (keyring)  │
        │ app/workers/* (Celery)│           │ asyncio.create_task    │
        │ app/adapters.py       │           │ SessionEventBus        │
        │ app/dependencies.py   │           │ SqliteCache            │
        │ app/services/crypto   │           │ flat corpus.sqlite     │
        └───────────┬───────────┘           └───────────┬────────────┘
                    │                                   │
                    └──────────────┬────────────────────┘
                                   ▼
    ══════════ “SHARED” TODAY — but not transport-free, and not infrastructure-free ═══════
      app/run_lifecycle.py     app/run_bundle.py        app/authorization.py
      app/run_dispatch.py      app/run_execution.py     app/services/memory.py  ← pgvector inline
      app/api/v1/runs.py       ← 13 × HTTPException, 47 × FastAPI transport types
      app/services/chat_scope  app/services/export      app/services/report_corpus
      app/models/*  app/schemas/*
                                   ▼
    ═════════════════════ research_engine/  — boundary ENFORCED by test_engine_boundary ═══
      graph.py runner.py ports.py runconfig.py corpus.py bundle.py verify_bundle.py …
      Ports: EventSink · Cache · Embeddings · Corpus   (+ LangGraph saver is its own port)
      KNOWN_EXCEPTIONS = set()   ← the engine imports nothing from app/ or evals/
```

The bottom two bands are the revision-2 correction. Revision 1 drew one “shared, host-free”
band; the audit against constraints 1–2 shows it is neither transport-free nor
infrastructure-free, and the plan now has a phase for each.

### 1.1 The 28 traced paths

| # | Path | Server | Desktop | Verdict |
|---|---|---|---|---|
| 1 | Startup | `main.py` lifespan | `sidecar` lifespan + seeding | intentional + duplicated seeding |
| 2 | Project create | `projects.create_project` | restated (own 409 path) | **duplicated** |
| 3 | Project load / list | `list_projects` + `_counts` | restated + own count query | **duplicated** |
| 4 | Run creation | `runs.create_run` | **imports it** | shared |
| 5–8 | Planning · execution · retrieval · claims | engine | engine | shared |
| 9 | Citation handling | `citation_rate`, `record_revision` | same | shared |
| 10 | Critic / review | engine | engine | shared |
| 11 | Approval — runs | `submit_report_review` | imports it | shared |
| 11b | Approval — sessions | `research.approve_or_rework` | `sidecar.approve_or_rework` | **duplicated** |
| 12 | Rework | Celery | asyncio | shared via `RunDispatcher` |
| 13 | Report synthesis | engine | engine | shared |
| 14 | Artifact generation | `record_artifact` + `authorization` | same | shared |
| 15 | Bundle — runs | `app/run_bundle.py` | same | shared |
| 15b | Bundle — sessions | `research.export_bundle_json` | restated, ~105 LOC | **duplicated** |
| 16 | Bundle verification | `verify_bundle.py` | same | shared |
| 17 | Project memory | pgvector, inline in the “shared” layer | absent | **capability difference + layering violation** |
| 18 | Corpus ingestion | per-project file, DTO inlined twice | flat file, DTO shaped a third time | intentional infra + **duplicated contract** |
| 19 | Report chat | `chat.send_message` | restated, ~115 LOC | **duplicated** |
| 19b | Project chat | `threads.py` | absent | capability difference |
| 20–23 | History · archive · restore · delete | runs shared, sessions restated | same | mixed |
| 24 | Authentication | JWT + refresh + cookies | per-launch bearer token | intentional |
| 25 | Authorization | `app/authorization.py`; ownership predicate restated per route | same | shared gate, duplicated predicate |
| 26 | Configuration | three builders, six construction sites | — | **duplicated** |
| 27 | Provider routing | `model_routing.resolve` | `routing_rules` + JSON file | partial |
| 28 | Secrets | encrypted column | OS keychain | intentional; resolution duplicated |

---

## 2. Duplication inventory

### 2.1 Genuinely reused today

`research_engine/*` (boundary enforced) · all fourteen `runs.py` handlers ·
`run_lifecycle` · `run_execution.persist_outcome` · `run_bundle` · `authorization` ·
`run_dispatch` · `schemas/{runs,research,project}` · `services/document_headers` ·
`services/{chat_scope, local_llm, provider_health, custom_endpoint, usage, report_corpus,
sse}` · `models/*` with `POSTGRES_ONLY_TABLES`.

**The load-bearing observation.** The repository already knows how to do this: `runs.py`
handlers are plain functions with `Depends` only as defaults, so the sidecar calls them
directly with its own dispatcher. Nothing needs inventing. Revision 2 adds the correction
that this pattern is *incomplete* — those same handlers still raise transport exceptions
and take FastAPI types, which is why the error contract has never been shared, only
coincidentally identical.

### 2.2 Duplicated product logic

| Behaviour | Server | Desktop | Real difference | Canonical owner | Risk |
|---|---|---|---|---|---|
| Session start / list / get | `research.py:55–189` | `sidecar.py:1424–1515` | dispatch, project resolution | `handlers/sessions.py` | M |
| Session SSE stream | `research.py:190–271` | `sidecar.py:1516–1583` | Redis vs in-process bus | `handlers/streams.py` + P7 | H |
| Run SSE stream | `runs.py:753–857` | `sidecar.py:2730–2795` | same | same | H |
| Plan gate GET / POST | `research.py:420–526` | `sidecar.py:1590–1678` | dispatch | `handlers/sessions.py` | M |
| Approve / rework | `research.py:527–570` | `sidecar.py:1679–1735` | dispatch | same | M |
| Cancel / archive / delete session | `research.py:571–672` | `sidecar.py:1997–2099` | none of substance | same | L |
| Session bundle export | `research.py:335–419` | `sidecar.py:1881–1986` | checkpoint reader, corpus | `handlers/exports.py` | H |
| Session `export.md` | `research.py:295–310` | `sidecar.py:1855–1880` | none | same | M |
| Report chat | `chat.py:81–198` | `sidecar.py:1756–1854` | key source, store factory, rate limit | `handlers/chat.py` | M |
| Projects CRUD | `projects.py:125–285` | `sidecar.py:857–1030` | corpus file cleanup | `handlers/projects.py` | M |
| Corpus doc → DTO | `corpus.py`, two sites | `sidecar.py:2414–2445` | **three copies** | `handlers/corpus.py` | H |
| Corpus upload validation | `corpus.py:72–101` | `sidecar.py:2546–2587` | **status + error codes differ** | same | M |
| Catalog / routing / probes | `models.py:218–472` | `sidecar.py:2100–2349` | routing storage | `handlers/models.py` + P11 | M |
| `RunConfig` construction | 3 sites | 3 sites | **demo rule restated ×4** | P8 | H |
| Session outcome → row | `_persist_outcome` | `_apply_outcome` | **event payloads differ** | `handlers/session_outcome.py` | H |
| Corpus store location | 4 sites | `make_corpus_store` | 5 sites total | P10 | M |
| Ownership check | 3 sites | 2 sites | none | `handlers/_access.py` | L |
| **Error → status mapping** | `HTTPException` at 13 sites in shared code, more per host | restated per route | **never shared, only coincidentally equal** | `app/errors.py` (**new, A-a**) | M |

**Scale.** `desktop/sidecar.py` is 2,973 lines; `create_sidecar_app` is 2,324. Roughly
1,450 lines are restated product behaviour. The `/runs` block (~260 lines) is the
delegating counter-example.

### 2.3 Intentional infrastructure differences — keep (constraint 9)

| Concern | Server | Desktop |
|---|---|---|
| Relational store | Postgres + pgvector, Alembic | SQLite, `create_all` + column sync |
| Execution | Celery over Redis, Redis session lock | `asyncio.create_task`, in-flight set |
| Live event fan-out | Redis pub/sub | `SessionEventBus` |
| Search cache | `RedisCache` | `SqliteCache` |
| Secrets | encrypted user column | OS keychain |
| Identity | JWT + refresh rotation | one local user + per-launch token |
| Corpus layout | one file per project | one file per app |
| Process lifecycle | container + healthcheck | Tauri shell + stdout handshake |
| Checkpointer | `AsyncPostgresSaver` | `AsyncSqliteSaver` |

### 2.4 The parity harness's structural hole — **NEW**

`test_shared_routes_return_the_same_response_models` compares only operations where *both*
hosts publish a `$ref`. The desktop's hand-written routes mostly declare no
`response_model`. Enumerated by running both `openapi()` documents: **49 shared operations,
12 never compared** —

```
GET/PATCH /auth/me · GET /models · GET/PUT/DELETE /models/routing
GET /models/local/status · GET /models/custom/status · POST /models/providers/test
GET/POST /projects/{id}/corpus/documents · GET /projects/{id}/corpus/status
```

Those twelve are exactly the routes the desktop restates by hand — the class that produced
the corpus `{"documents": […]}` bug `AGENTS.md` records.

### 2.5 Accidental differences found in this audit

**#1 — the desktop SSE cursor uses two id spaces. NEW.** `PersistingSink` writes
`payload["id"]` from a per-session counter starting at 1; the backlog replays
`agent_logs.id`, a global autoincrement. The server does it correctly
(`adapters.agent_log_sink` sets `event["id"] = row.id`). Reproduced against a real sidecar
app, two sessions:

```
agent_logs (db id, session, msg)        bus live ids
  1 …c5f4  a0                            s1: [1, 2, 3, 4, 5]
  6 …feb3  b0   ← db id  6               s2: [1, 2, 3]
  8 …feb3  b1   ← db id  8
 10 …feb3  b2   ← db id 10
```

For every session after the first — and the first-launch demo seed guarantees the user's
first real run is the second — a reconnect replays the backlog as duplicates, then sets
`seen_max` to a large DB id, after which every live event is dropped silently. Affects both
stream copies. Tests miss it because each test uses a fresh database and one session.

**#2 — the canonical corpus upload contract disagrees. NEW.**

| | Server | Desktop |
|---|---|---|
| success | `200` | `201` |
| missing filename / empty / unsupported | `400` | `422` |
| over size limit | *no limit* | `413` |
| embedder unavailable | *propagates* | `503` |
| body | full `DocumentResponse` | `id`, `filename`, `chunks` only |

**#3 — desktop lifecycle events carry `data: None`. NEW**, where the server sends
`{task_count…}`, `{word_count…}`, `{elapsed_s…}`.

**#4 — `/models/providers/health` has two shapes**, query parameter vs path segment, with
the only product-behaviour `isDesktop` branch in the frontend.

**#5 — three `RunConfig` builders, six construction sites.** Two recorded drifts and one
P0 honesty bug already.

**#6 — rate limiting silently absent on desktop.** Under constraint 7 this becomes a
declared capability, not a port.

**#7 — session-scoped chat, corpus mode and bundle export exist for sessions and not for
runs.** Already in the release notes under `known`. Identical on both hosts, so out of
scope — but it means the session pipeline is live code (constraint 8).

---

## 3. Root causes

1. **There is no application layer — only a server layer and an engine.** The engine
   boundary is explicit and enforced. Above it, `app/` mixes host-free application logic,
   server infrastructure, and handlers that bind both. Revision 2 adds: even the part that
   *is* shared carries transport (`HTTPException`, `UploadFile`, `StreamingResponse`) and,
   in `memory.py`, a Postgres-only query.
2. **`Depends(…)` is the coupling vector.** A route written the ordinary FastAPI way binds
   `get_db`, `get_current_user`, `get_redis` and `settings` into the same function as the
   product rule, so the desktop cannot reuse it and restates it.
3. **Parity is asserted at the route surface, not the behaviour surface.** Existence is
   checked; shape only sometimes; bodies, status codes and event payloads never.
4. **Nothing ties an artifact to a source revision.** Zero matches for `git_sha` or
   `git rev-parse`. Five hand-maintained version constants, two of which already drifted
   for a whole release line.
5. **Two workflows own one GitHub Release.** No ordering, no cross-gate, and a `v2.1` tag
   would ship installers with no images.

---

## 4. Target architecture

### 4.1 The dependency direction (constraint 2)

```
   ┌──────────────────────────────────────────────────────────────────────┐
   │ TRANSPORT            app/api/v1/*.py          desktop/routes/*.py     │
   │                      FastAPI routers, Depends, HTTPException,         │
   │                      StreamingResponse, UploadFile, auth extraction   │
   └───────────────────────────────┬──────────────────────────────────────┘
                                   │ calls exactly one owner per operation
   ┌───────────────────────────────▼──────────────────────────────────────┐
   │ APPLICATION          app/handlers/*.py        app/handlers/registry.py│
   │ (use cases)          plain async functions · domain errors only       │
   │                      NO FastAPI · NO Depends · NO HTTPException       │
   │                      NO Redis/Celery/keyring · NO dialect-specific SQL │
   └───────────────────────────────┬──────────────────────────────────────┘
                                   │
   ┌───────────────────────────────▼──────────────────────────────────────┐
   │ DOMAIN               app/models/*  app/schemas/*  app/errors.py       │
   │                      run_lifecycle · run_bundle · authorization       │
   │                      research_engine/*  (its own enforced boundary)   │
   └───────────────────────────────┬──────────────────────────────────────┘
                                   │
   ┌───────────────────────────────▼──────────────────────────────────────┐
   │ PORTS                app/ports.py  ·  research_engine/ports.py        │
   │                      Protocols only. Imports neither host.            │
   └───────────────────────────────┬──────────────────────────────────────┘
                                   │
   ┌──────────────────┬────────────▼─────────────┬───────────────────────┐
   │ INFRASTRUCTURE   │  app/adapters.py         │ desktop/infrastructure│
   │ (host-specific)  │  app/db/* app/workers/*  │   db · events ·       │
   │                  │  app/config.py  crypto   │   dispatch · secrets ·│
   │                  │  app/dependencies.py     │   config · corpus ·   │
   │                  │                          │   routing             │
   └──────────────────┴──────────────────────────┴───────────────────────┘
```

Arrows point **downward only**. Enforced by `test_layer_boundaries.py`, which extends the
existing `test_engine_boundary` idiom to the whole stack, with a `KNOWN_EXCEPTIONS` set
that starts empty and cannot rot.

### 4.2 What the application layer may and may not touch

**May depend on:** `app/models` (the shared ORM — dialect-portable by construction, with
`POSTGRES_ONLY_TABLES` naming the one exception), `app/schemas`, `app/errors`,
`app/ports`, `run_lifecycle`, `run_bundle`, `authorization`, and `research_engine`.

**Receives as collaborators, never constructs:** an `AsyncSession`, the identity of the
caller, and any port instance. The session is passed in by the adapter; the application
layer never reads a DSN, never opens an engine, never begins the outermost transaction.

**May not import:** `fastapi`, `starlette`, `app.config`, `app.db.*`, `app.dependencies`,
`app.adapters`, `app.workers`, `celery`, `redis`, `keyring`, `desktop.*`.

**May not contain:** dialect-specific SQL. The one instance today —
`MemoryChunk.embedding.cosine_distance(...)` at `app/services/memory.py:275` — moves
behind port P12.

### 4.3 File layout

```
backend/
  research_engine/        ← UNCHANGED. pipeline + its own ports.
  app/
    errors.py             ← NEW  domain error taxonomy + ONE shared status map
    ports.py              ← NEW  host ports (§5)
    handlers/             ← NEW  THE CANONICAL APPLICATION RUNTIME
      registry.py           the operation → owner table (constraint 3)
      _access.py            ownership predicates (404-not-403, one home)
      sessions.py           start · list · get · plan · approve · cancel · archive · delete
      session_outcome.py    RunOutcome → session row + lifecycle event (one home)
      runs.py               moved from api/v1/runs.py, transport stripped
      projects.py · corpus.py · chat.py · models.py · exports.py
      streams.py            ONE event generator; the adapter frames it as SSE
      version.py            /version and /capabilities
    ── SERVER ADAPTER ──
    api/v1/*.py           thin routers; rate limiting lives here and only here
    config.py db/* dependencies.py adapters.py workers/* services/crypto.py
    ── DOMAIN, already host-free ──
    run_lifecycle.py run_bundle.py run_execution.py authorization.py run_dispatch.py
    models/* schemas/*
  desktop/                ← DESKTOP ADAPTER
    sidecar.py            app factory · token middleware · lifespan · entry point (~450 LOC)
    infrastructure/       db · events · dispatch · secrets · config · corpus · routing
    routes/               thin routers
```

**Why not `research_engine/`:** the engine must stay shippable without SQLAlchemy and
without the domain; `run_lifecycle` is unavoidably ORM-shaped. **Why not a top-level
`core/`:** the root of `app/` is already the canonical layer and `app/api`, `app/db`,
`app/workers` are already the adapter. A rename is cosmetic and deliberately deferred.

### 4.4 The invariant (constraint 14)

> **A new product feature must be implementable once in the canonical
> application/domain layer and exposed by both hosts through thin adapters.**

Goes into `AGENTS.md`, and is made checkable by `test_one_canonical_owner`
(§8) — every operation in the registry is served by both hosts unless it appears in
`CAPABILITY_DIFFERENCES`, and both hosts' routes for it resolve to the same function
object.

---

## 5. Errors, ports and capabilities

### 5.1 `app/errors.py` (new — constraint 1, 2)

```
AppError                     code            server        desktop
├─ NotFound                  not_found       404           404
├─ Conflict                  conflict        409           409
├─ Invalid                   invalid         400           400
├─ PayloadTooLarge           too_large       413           413
├─ DependencyUnavailable     unavailable     503           503
└─ CapabilityUnavailable     capability      501           501
```

One `ERROR_STATUS` map, in the application layer, applied by both adapters — so the status
code is part of the shared contract rather than something each host happens to choose.
The adapter is the only place `HTTPException` is constructed. `CapabilityUnavailable`
carries a `capability` field, which is what makes §5.3 observable.

### 5.2 Ports

| # | Port | Interface | Server | Desktop | Status |
|---|---|---|---|---|---|
| P1 | `EventSink` | `(session_id, event) → None` | `agent_log_sink` → Redis | `PersistingSink` → bus | exists |
| P2 | `Cache` | `get` / `set` | `RedisCache` | `SqliteCache` | exists |
| P3 | `Embeddings` | `model_id` / `embed` / `is_local` | `embeddings_for` | `LocalEmbeddings` | exists |
| P4 | `Corpus` | `search` / `read` | per-project store | flat store | exists |
| P5 | Checkpointer | LangGraph saver | `AsyncPostgresSaver` | `AsyncSqliteSaver` | exists |
| P6 | `RunDispatcher` | `start` / `resume_plan` / `rework` | `CeleryDispatcher` | `_SidecarDispatcher` | exists |
| P7 | `EventStream` | `subscribe(id) → AsyncIterator[(int, dict)]` | Redis pub/sub | `SessionEventBus` | new |
| P8 | `RunConfigBuilder` | `build(db, row) → RunConfig` | settings + BYOK + routing | env + keychain + file | new |
| P9 | `SecretStore` | `keys_for(owner) → dict` | `crypto.decrypt` | `keyring` | new |
| P10 | `CorpusLocator` | `for_project(id) → Corpus \| None` | one file per project | one flat store | new |
| P11 | `RoutingStore` | `get` / `set` / `clear` | `users.model_routing` | `routing.json` | new |
| **P12** | **`MemoryIndex`** | `available` · `index(report)` · `search(vector, k)` · `purge(owner)` | pgvector over `memory_chunks` | raises `CapabilityUnavailable` | **new — R-a** |

**Deleted from revision 1:** `RateLimiter` (R-b). **Still not ports,** and why: persistence
and transactions (one ORM, both hosts; the dialect difference is `POSTGRES_ONLY_TABLES`
plus P12); filesystem and HTTP (engine-owned, already egress-guarded); run locking (host
scheduling — Redis token lock vs. an in-process set are legitimately different shapes);
cancellation (durable state, already enforced by three writers that collapse to one).

Per-port contract — lifecycle, errors, transactions, concurrency and test strategy — is
unchanged from revision 1 for P7–P11. P12 adds: `available` is read from the port, never
re-derived by a caller (`memory.is_available(db)`'s dialect test moves *into* the Postgres
implementation); `index` never raises into a completed run (today's behaviour preserved);
`search` on the desktop raises `CapabilityUnavailable("project_memory")`, which the adapter
renders as a 501 naming the capability.

### 5.3 Capability differences (constraints 6, 7)

`test_host_parity` gains a third table beside `INTENTIONAL_SERVER_ONLY` and
`INTENTIONAL_DESKTOP_ONLY`:

| Capability | Server | Desktop | How a client learns |
|---|---|---|---|
| `project_memory` | yes | no — pgvector-only | `GET /capabilities`; the route answers 501 `capability: project_memory` |
| `project_chat` | yes | no — pgvector-only | same |
| `server_pdf` | yes | no — WebView print-to-PDF | 501, already today |
| `rate_limits` | yes | **no — not enforced** | `GET /capabilities` |
| `byok_storage` | encrypted column | OS keychain | `GET /capabilities` |
| `local_llm_control` | no | yes — can spawn Ollama | `GET /capabilities` |

**`KNOWN_DESKTOP_GAPS` stays empty and stays a defect list.** A capability difference is
never filed there. Two new assertions make that stick: every `CAPABILITY_DIFFERENCES` entry
must answer with a capability response carrying its code (never a 404, never a silent
omission), and every capability the frontend branches on must appear in `GET /capabilities`
on both hosts.

`rate_limits: false` is the constraint-7 answer: the desktop states plainly that it does
not rate-limit, rather than satisfying a `RateLimiter` interface with a function that
always allows.

---

## 6. Migration plan

### 6.1 The ladder every operation climbs (constraint 13)

No operation skips a rung, and **the last rung is deletion**:

```
1  baseline        golden contract recorded for the operation, on BOTH hosts, unchanged code
2  canonical       the use case lands in app/handlers/, transport-free, domain errors only
3  server adapter  app/api/v1/… becomes a thin router over it
4  desktop adapter desktop/routes/… becomes a thin router over it
5  parity          the operation's golden test passes on both hosts
6  packaged        the same golden test passes against the FROZEN PyInstaller sidecar
7  delete          the duplicate implementation is removed — and not before rung 6
```

Rungs 2–7 for one operation are one PR where the operation is small, two where it is not.
Rung 6 is the constraint-12 gate: **nothing is deleted until the packaged desktop has run
the contract.** That moves `parity-frozen` from a release-time job to a merge gate on any
PR that reaches rung 7.

### 6.2 Phases

| Phase | Name | Contains | Risk |
|---|---|---|---|
| **0** | Record the contract | parity harness, normalizer, drivers, journeys, goldens; the four known divergences recorded as `XFAIL_DIVERGENCES`, not fixed | none — pure addition |
| **1** | Close the shape hole *(fix)* | `response_model=` on the twelve desktop operations; the shape test fails on a one-sided model | L |
| **2** | Three behavioural fixes *(fix)* | 2a SSE id space · 2b corpus upload contract · 2c lifecycle event payloads. Regression test first, one commit each | M (2a) |
| **3** | Declare the layers | `test_layer_boundaries.py`, empty `app/handlers/`, empty `app/ports.py`, `AGENTS.md` invariant | none |
| **4** | **Errors before movement** *(new — A-a)* | `app/errors.py`; strip `HTTPException` and FastAPI types from the already-shared `runs.py` handlers; both adapters apply the one status map | **M–H** — 13 raise sites, 47 transport references; guarded by Phase 0 goldens |
| **5** | The ports | P7–P12 as Protocols + one implementation per host. `RunConfigBuilder` wired first (highest-risk duplication); `MemoryIndex` extracts the pgvector query | M |
| **6** | Registry + `runs` + `streams` | `handlers/registry.py`, `test_one_canonical_owner`; `runs.py` and the four SSE generators climb the ladder | M |
| **7** | The session journey | sessions CRUD → gates → outcome → exports → chat, each on the ladder. `_persist_outcome` and `_apply_outcome` collapse to one owner | **H** |
| **8** | Projects, corpus, models | as above; `/models/providers/health/{provider}` served on both, query form deprecated for one release | M |
| **9** | Version traceability | `VERSION`, `sync_version.py`, `stamp_build.py`, `/version` — **one `git_sha` + `dirty`, no engine SHA** (R-c) | L |
| **10** | Capabilities | `GET /capabilities`; frontend branches on reported capability, not the build flag; `CAPABILITY_DIFFERENCES` table and its two assertions | M |
| **11** | Sidecar containment | `test_sidecar_is_transport_only.py` with the ratcheting LOC ceiling; delete the remaining shims; CI and release work (§9, §10) | L |

**Constraint 8 restated:** no phase merges the session and run pipelines. `handlers/sessions.py`
and `handlers/runs.py` are separate owners, and `test_layer_boundaries` asserts neither
imports the other.

**What is deleted, and when.** Nothing in Phase 6–8 deletes on the same PR that moves,
unless rung 6 ran in that PR. `desktop/sidecar.py` shrinks 2,973 → ~450 across Phases 6–11,
each decrement gated by its operation's frozen-host test.

---

## 7. File-level change plan

| Path | Action | Phase |
|---|---|---|
| `backend/app/errors.py` | CREATE | 4 |
| `backend/app/ports.py` | CREATE | 5 |
| `backend/app/handlers/` — registry, `_access`, sessions, session_outcome, runs, projects, corpus, chat, models, exports, streams, version | CREATE | 3, 6–10 |
| `backend/app/api/v1/{runs,research,chat,projects,corpus,models}.py` | REWRITE as thin routers (~60 LOC each); rate limiting stays here | 4, 6–8 |
| `backend/app/api/v1/{auth,threads,router}.py` | UNCHANGED — server-only by design | — |
| `backend/app/services/memory.py` | SPLIT — the pgvector query moves to the P12 server adapter; the chunking/ingestion rules stay canonical | 5 |
| `backend/app/adapters.py`, `dependencies.py`, `runtime.py` | UPDATE — server port implementations | 5 |
| `backend/app/workers/pipeline_runner.py` | UPDATE — keeps only the lock and Celery wiring | 5, 7 |
| `backend/app/workers/tasks.py`, `celery_app.py` | UNCHANGED — **task names must not change** | — |
| `backend/app/run_execution.py` | UPDATE — stops importing private names from `pipeline_runner` | 5 |
| `backend/app/{run_lifecycle,run_bundle,authorization,run_dispatch}.py` | UNCHANGED | — |
| `backend/research_engine/*` | UNCHANGED except the generated build stamp | 9 |
| `backend/research_engine/local.py` | UPDATE — CLI/eval `RunConfigBuilder` | 5 |
| `backend/desktop/sidecar.py` | SHRINK 2,973 → ~450 | 6–11 |
| `backend/desktop/infrastructure/*`, `desktop/routes/*` | CREATE | 5–8 |
| `backend/desktop/research-sidecar.spec` | UPDATE — ship the build stamp | 9 |
| `VERSION`, `scripts/sync_version.py`, `scripts/stamp_build.py` | CREATE | 9 |
| `frontend/lib/capabilities.ts` | CREATE | 10 |
| `frontend/hooks/queries.ts`, `SideNav`, `ProjectHealth`, `SectionContent` | UPDATE — capability branches | 10 |
| `releases.ts`, `README.md`, `tauri.conf.json`, `Cargo.toml` | UPDATE — derived from `VERSION` | 9 |
| `.github/workflows/{ci,desktop,release}.yml` | UPDATE | 11 |
| `AGENTS.md` | UPDATE in the same commits — the “two hosts, one contract” table shrinks as each row is fixed | every |

---

## 8. Test plan

### 8.1 New

| Test | Kind | Phase | Guards |
|---|---|---|---|
| `tests/parity/test_golden_journeys.py` + `golden/*.json` | parity | 0 | every journey, both hosts, against a reviewed third artifact |
| `tests/parity/test_normalize.py` | unit | 0 | the normalizer — **17 written and passing** |
| `tests/parity/test_golden_is_not_degenerate.py` | meta | 0 | **A-d** — a golden of empty bodies fails |
| `tests/workflow/test_layer_boundaries.py` | contract | 3 | the full downward dependency direction, `KNOWN_EXCEPTIONS = set()` |
| `tests/workflow/test_error_contract_has_one_home.py` | contract | 4 | both adapters apply the same `ERROR_STATUS` map |
| `tests/workflow/test_one_canonical_owner.py` | contract | 6 | **A-b** — both hosts' routes resolve to the same function object |
| `tests/workflow/test_sidecar_is_transport_only.py` | architecture | 11 | **A-c** — no ORM queries, no engine imports, ratcheting LOC ceiling |
| `tests/workflow/test_desktop_is_self_contained.py` | architecture | 10 | **A-f** — no server origin anywhere in the desktop tree |
| `tests/workflow/test_capability_differences_are_observable.py` | contract | 10 | **A-e** — a capability answers 501 with its code, never 404 |
| `tests/workflow/test_desktop_stream_reconnect.py` | regression | 2a | §2.5 #1 |
| `tests/workflow/test_corpus_upload_contract.py` | contract | 2b | §2.5 #2, both hosts, same table |
| `tests/workflow/test_lifecycle_event_payloads.py` | contract | 2c | §2.5 #3 |
| `tests/workflow/test_run_config_has_one_home.py` | contract | 5 | the demo rule resolves to one function |
| `tests/workflow/test_memory_capability.py` | contract | 5 | P12 — `available` is read from the port, never re-derived |
| `tests/workflow/test_version_has_one_source.py` | contract | 9 | every constant derives from `VERSION`; no fabricated SHA |
| `frontend/lib/capabilities.test.ts` | unit | 10 | capability resolution, no `isDesktop` |

### 8.2 Golden parity methodology (constraint 15)

| Requirement | How |
|---|---|
| Both hosts use deterministic fake providers | `llm_mode=fake` on both, **and the same `MODEL_*` routing pinned on both** (A-i), so the fixture pipeline is byte-identical |
| Infrastructure ids and timestamps normalized | `normalize()` — uuid → `<uuid>`, ISO instant → `<timestamp>`, autoincrement → `<int-id>` |
| Product-visible state NOT normalized away | **a value may be redacted, a key never is** — `==` still fails when a host omits a field. Redaction is shape-aware: an `id` holding `"skip"` survives verbatim, because `corpus.upload_document` really returns that |
| Because routing is pinned, compare *more* | cost and `model_routing` compared exactly (A-i). Reduction is kept only where a host difference is genuine — `chunks_by_model`, where the embedder really is local on one host |
| Expected contract independently reviewed | goldens recorded from the server, committed in their own PR, read by a human. `PARITY_RECORD=1` never runs in CI |
| The normalizer has tests | 17, covering the redact-value-not-key rule, null-vs-present, shape-awareness, recursion and list order |
| Parity cannot pass on a shared empty result | **A-d** — each journey declares `must_observe` facts (the run reached `AWAITING_APPROVAL`; the report carries ≥1 citation marker; the bundle verified; the document list was non-empty). A journey whose steps are all empty fails on both hosts even when they agree, and a golden of empty bodies fails its own meta-test |

### 8.3 Regression coverage that must survive untouched

Project memory chunking · citation resolution rate · Windows verifier · desktop sidecar
packaging · Docker tag correctness · release note race · corpus response shape · desktop
import-time configuration failure · `host.docker.internal` · chat routes · run lifecycle ·
deletion clearing memory chunks · eval unmeasured-vs-zero · zero evidence never
synthesizes.

Where a phase moves the code under one of these, that phase's acceptance criterion is that
the test passes **unchanged**. Phase 5 is the one to watch: splitting `memory.py` touches
both project-memory chunking and deletion-clears-memory-chunks.

---

## 9. CI plan

| Job | New? | Runs on | Fails when |
|---|---|---|---|
| `backend`, `frontend`, `golden-e2e`, `eval-artifacts` | — | as today | as today |
| `parity` | new | PR + main | a journey differs between hosts or from the golden, or a journey is degenerate |
| `layers` | new | PR + main | the dependency direction is violated; the engine boundary regresses |
| `canonical-owner` | new | PR + main | a shared operation has two owners |
| `sidecar-containment` | new | PR + main | product logic appears in `desktop/`, or the LOC ceiling rises |
| `version-consistency` | new | PR + main | `sync_version.py --check` disagrees with `VERSION` |
| `contract-version` | new | PR + main | the OpenAPI hash changed without `contract_version.txt` in the same PR |
| `parity-frozen` | new | **PR (when a PR reaches ladder rung 7) + main + tag** | the goldens fail against the PyInstaller binary |
| `sidecar`, `shell` | + steps | PR + main + tag | as today, plus `/version.git_sha` ≠ this checkout |
| `release-artifact-revision` | new | tag | the SHA inside the shipped installer ≠ the server image's |

**Why divergence becomes impossible rather than discouraged**

1. `layers` makes it impossible to *write* a use case only one host can call.
2. `canonical-owner` makes it impossible for a second implementation to exist unnoticed —
   two copies cannot be one object.
3. `sidecar-containment` makes it impossible for `sidecar.py` to grow back.
4. `parity` makes it impossible to *merge* a divergence, and A-d makes it impossible to
   pass by both hosts doing nothing.
5. `parity-frozen` gates deletion, so the packaged artifact is proven before the fallback
   is removed (constraint 12).
6. `release-artifact-revision` makes it impossible to ship artifacts from different source.

---

## 10. Release plan

```
git tag v2.0.2                       ← the only trigger
        ▼
release.yml  (sole owner of the GitHub Release)
        ├── verify        VERSION == tag · sync_version --check · contract_version fresh
        ├── images        matrix(api|worker|frontend × amd64|arm64) → digests → manifest
        ├── desktop       uses: ./.github/workflows/desktop.yml   (workflow_call)
        │                 sidecar + shell on ubuntu · macos · windows
        ├── parity-frozen goldens against the frozen sidecar
        ├── release-artifact-revision        ← A-h, constraint 16
        │     mount the .dmg / unpack the .AppImage
        │     run the sidecar FROM INSIDE THE SHIPPED ARTIFACT → GET /version
        │     docker run <api image> → GET /version
        │     assert both git_sha == the tag's commit, and dirty == false
        └── publish       needs: all of the above · ONE release call · ONE body
```

`desktop.yml` gains `on: workflow_call`, loses its `release` job and its `v*` tag trigger —
removing the race by removing the second owner, and closing the `v2.1`-tag hole.
`release.yml` narrows to `v[0-9]+.[0-9]+.[0-9]+*`.

**Revision-2 change (A-h):** the final check no longer inspects `backend/dist/`. It runs
the sidecar extracted from the installer a user would download, on macOS and Linux runners,
and compares one `git_sha` against the server image's. That is the artifact-level proof
constraint 16 asks for, and it needs no second SHA (R-c).

---

## 11. Risks

| # | Risk | L | I | Mitigation |
|---|---|---|---|---|
| R1 | Phase 7 changes session behaviour invisibly | M | H | goldens recorded before any move; five ladder steps per operation; existing session tests untouched |
| R2 | New handler imports pull an excluded package into the frozen bundle | M | H | `LAZY_REQUEST_IMPORTS` extended in the same commit; `parity-frozen` gates deletion |
| **R3** | **Phase 4 changes an error contract while stripping `HTTPException`** | **M** | **H** | **new in revision 2.** 13 raise sites. Phase 0 goldens record every status and `detail` string first; the error map is asserted to have one home |
| R4 | `RunConfigBuilder` collapses the demo rule wrongly → the P0 honesty bug returns | L | H | the demo-stamp test runs first, unchanged; the new test asserts one implementation |
| **R5** | **Extracting the pgvector query breaks memory ingestion or deletion cascade** | **M** | **H** | **new in revision 2 (R-a).** Both regression suites run unchanged either side of the split; P12's `available` is asserted to be read, never re-derived |
| R6 | Normalization too lenient → vacuous parity | M | H | A-d non-degeneracy guards; normalizer unit-tested; goldens human-reviewed |
| R7 | Normalization too strict → flaky CI | L | M | ids, timestamps and durations discarded; routing pinned on both hosts so cost is deterministic |
| R8 | Celery task names change accidentally | L | H | `tasks.py` out of scope; a test asserting the four registered names |
| R9 | `workflow_call` refactor breaks the tag build | L | H | land the plumbing on main and exercise it with `workflow_dispatch` first |
| R10 | Three frontend build targets diverge in Phase 10 | M | M | all three run locally; CI runs two |
| R11 | Fixing the SSE id space invalidates cursors held during upgrade | L | L | a restart resets the client; the stream re-syncs from `agent_logs` |
| R12 | Scope creep into merging sessions and runs | M | H | constraint 8; `test_layer_boundaries` asserts the two owners do not import each other |
| **R13** | **`parity-frozen` on PRs makes the merge gate slow** | **M** | **M** | **new in revision 2.** It runs only on PRs that reach rung 7, on Linux only; the macOS/Windows frozen runs stay on `main` and tags |

---

## 12. Rollback

Every phase is a separate PR with **no database migration**, so `git revert` is always
available and there is no forward-only step.

| Phase | Rollback |
|---|---|
| 0 | delete `tests/parity/` |
| 1 | revert; desktop routes lose `response_model` |
| 2a–2c | revert per commit; each is one behaviour |
| 3 | delete two files |
| 4 | revert; adapters go back to raising `HTTPException` directly. Goldens prove the contract is unchanged either way |
| 5 | revert; ports unreferenced except `RunConfigBuilder` and `MemoryIndex`, whose call sites revert with them |
| 6–8 | revert the PR. Because deletion is rung 7, a reverted PR that stopped at rung 6 leaves the original implementation still present and serving |
| 9 | revert; `/version` vanishing breaks nothing that predates it |
| 10 | revert; `GET /capabilities` may stay — additive |
| 11 | revert the workflow changes and the containment test |

**Constraint 12 is what makes rollback cheap:** for any operation that has not reached rung
7, both implementations exist and the adapter is one line away from pointing back at the
old one.

---

## 13. Definition of Done

| # | Requirement | Satisfied by | Phase |
|---|---|---|---|
| 1 | One canonical implementation of product behaviour | `app/handlers/` + `test_layer_boundaries` + `test_one_canonical_owner` | 3, 6–10 |
| 2 | Desktop does not reimplement research behaviour | `sidecar.py` ≤500 LOC + `test_sidecar_is_transport_only` | 6–11 |
| 3 | Different infrastructure allowed | P1–P12; every row of §2.3 stays | 5 |
| 4 | Infrastructure isolated behind explicit boundaries | twelve ports; the layer test enforces direction | 3, 5 |
| 5 | Frontend consumes one contract | P1 closes the shape hole; P8 removes the health-route divergence; P10 replaces product `isDesktop` branches with reported capabilities | 1, 8, 10 |
| 6 | Server and desktop built from the same commit | one orchestrator, one tag trigger, `workflow_call` | 11 |
| 7 | Bundled desktop engine exposes its exact SHA | build stamp shipped by the spec; `/version`; handshake line | 9 |
| 8 | Server exposes its exact SHA | the same `/version` owner | 9 |
| 9 | CI fails if revisions differ | `release-artifact-revision`, from inside the installer | 11 |
| 10 | Same deterministic journeys against both hosts | `tests/parity/`, fake providers, routing pinned on both | 0 |
| 11 | Normalized behaviour compared, not storage | §8.2, with product state explicitly not normalized away | 0 |
| 12 | `KNOWN_DESKTOP_GAPS` empty for shipping behaviour | stays empty; `CAPABILITY_DIFFERENCES` is a separate, *observable* category | 10 |
| 13 | Intentional infra differences documented | §2.3 into `AGENTS.md`; each port states both implementations | 5, 11 |
| 14 | Existing user data compatible | **zero migrations**; no ORM change; no Alembic revision touched | all |
| 15 | Security and isolation intact | token middleware, SSRF guard, corpus egress guard, artifact authorization, download headers unchanged; **rate limiting is declared absent on desktop rather than faked** | all |
| 16 | Release verification intact | bundle-size check, SHA256SUMS, both-arch check, eval write-once retained | 11 |
| 17 | macOS and Linux contain the same revision as server | `release-artifact-revision` on both runners | 11 |
| 18 | A developer can inspect a running build and know the commit | `/version` + handshake + Settings → About | 9, 10 |
| 19 | A released build traces to a commit | asset → tag → `VERSION` → `git_sha`, asserted from inside the installer | 9, 11 |
| 20 | A new feature is implemented once | §4.4, made checkable by `test_one_canonical_owner` | 3–10 |

---

## 14. Questions

Three from revision 1 remain open; two are now partly answered by the constraints.

**Q1 — How should the parity suite execute a *server* run?**
Constraint 15 requires deterministic fake providers on both hosts, which the dispatcher
override provides. **Recommendation: override `get_run_dispatcher` with an in-process
dispatcher; keep `golden-e2e` as the real-Celery proof.** Proceeding this way unless told
otherwise.

**Q2 — Fix the three live defects before the refactor, or during it?**
Constraint 12's “baseline before change” ladder argues for before: the goldens are recorded
once and then only change when a contract deliberately changes. **Recommendation: Phases
1–2, before any movement.**

**Q3 — Rate limiting on desktop.**
**Answered by constraint 7.** It is a declared capability difference (`rate_limits: false`),
not a port and not a no-op. No longer an open question.

**Q5 — new, from Phase 4.** `Invalid` maps to `400` and `Unprocessable` to `422`, and the
only reason both exist is that the run surface and the corpus surface already answered
different codes for the same *kind* of refusal. Unifying them would be a cleaner contract
and a client-visible change. **Recommendation: leave both until the frontend's error
handling is reviewed in Phase 10, then unify on `422` and re-record the goldens in one
deliberate commit.** Not urgent, and not something to fold into a refactor.

**Q4 — answered by doing it.** Phase 4 strips `HTTPException` from `app/api/v1/runs.py`, which the desktop
already imports and calls today. During that phase the desktop must map domain errors
itself. **Recommendation: land `app/errors.py` and both mapping call sites in one PR** —
splitting it would leave one host translating and the other raising, which is precisely the
divergence class this work exists to remove.

---

## Out of scope, deliberately

- **Merging the session and run pipelines** (constraint 8). This plan makes both
  host-symmetric; it does not merge them, and `test_layer_boundaries` asserts the two
  owners do not import each other.
- **Making the desktop depend on the server** (constraint 10). The desktop stays
  self-contained, asserted by `test_desktop_is_self_contained`.
- Preemptive run cancellation — unbuilt on purpose.
- Project memory and server-side PDF on the desktop — real capability differences.
- Renaming `app/handlers/` to `backend/core/` — cosmetic, one mechanical commit later.
