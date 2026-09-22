# 07. Interface delivery phases — historical vocabulary

**This is an appendix, not a specification.** It exists for one reason: 106 source comments
cite a delivery phase by number (`Phase 2a`, `Phase 4`, …) and the document that defined
those numbers no longer exists. Without this file, every one of those comments points a
reader at nothing.

## Why the citations dangle

The phases were defined in `docs/07_UIUX_Guidelines.md` §2 "Information architecture",
added in `feb0ac8`, moved to `docs/product/07_UIUX_Guidelines.md` in `a852659`, and
**deleted** in `40d2ee6` ("docs: restructure the documentation set around who is reading
it"), which replaced it with `docs/developers/07-frontend-guidelines.md` — a different
document, with unnumbered sections.

So `docs/07 §2` was correct when written and resolves to nothing now. `AGENTS.md` says the
document *number* is stable and free of renaming; what happened here is subtler and worse —
the number was kept while the content behind it was replaced, so the citation silently
resolves to the wrong document rather than failing loudly.

**This file does not restore the deleted document.** It records only the phase vocabulary,
which is what the surviving citations actually depend on. For how the interface works today,
read [`../docs/developers/07-frontend-guidelines.md`](../docs/developers/07-frontend-guidelines.md)
and the user guide; for how the product works, read [`../docs/`](../docs/00_INDEX.md).

## The phases

Each entry is reconstructed from the deleted document and from the shipped code that cites
it. Every phase below is **complete** — this is archaeology, not a plan.

| Phase | What it delivered | Where it lives now |
|---|---|---|
| **0** | Removed the redundant `/dashboard` nav item and the standalone Appearance settings section; the light/dark toggle moved into the account menu | `frontend/components/AccountMenu.tsx` |
| **2a** | BYOK connection flow where **saving a key is testing it** — the key is probed before it is stored, and re-probed on demand, so the UI never shows a stale "connected" | `app/api/v1/models.py`, `app/api/v1/auth.py`, `app/services/provider_health.py` |
| **2b** | Local-model onboarding: recommended models with a one-click Start, and streamed Ollama pull progress | `app/api/v1/models.py` (`local/pull`, `local/start`, `local/status`) |
| **3** | The **settings customization surface** — sectioned settings IA, and the per-user preference knobs stored as one JSON blob rather than a column each | `users.preferences` (migration `0011`), `app/schemas/auth.py::UserPreferences`, `app/services/run_config.py::PREFERENCE_FIELDS` |
| **4** | The **research design gate** — a second durable `interrupt()` after the planner, with its own status, resume path and request fields | `research_engine/graph.py::plan_gate_node`, migrations `0012`–`0014`, `RunConfig.skip_plan_gate` |
| **5** | **Grounding scope for follow-up questions** — pin a question to this report, the corpus, the web, or everything, and say which produced the answer | `app/services/chat_scope.py` |
| **6** | The **project workspace** — `/project` as a place rather than a filter, with in-place corpus document preview in a sandboxed frame | `frontend/app/(app)/project/`, `frontend/components/preview/` |
| **7** | **One status vocabulary**, and the citation-resolution rate as a stored measurement rather than a derived one | migration `0015`, `app/maintenance.py`, `research_engine/citation_rate.py` |

## Citing a phase

Write `internal/07 Phase 4`. Do not write `docs/07 §2, Phase 4` — that form is what this
file exists to retire, and `docs/07` is a live document about something else.

A phase number is **historical**. It says when something arrived and under what plan, never
how it behaves now. If a comment needs to explain current behaviour, it should say the
behaviour; the phase citation is only useful for the archaeology.
