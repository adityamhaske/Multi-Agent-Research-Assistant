# Internal engineering notes

**This directory is not documentation.** Nothing here is published to the documentation
site, linked from the docs navigation, or maintained to the standard `docs/` is held to.

These are working notes: milestone sequencing, release checklists, budget assumptions, and
decision archaeology. They are kept because a large number of source comments cite them by
number (`docs/12 M7`, and similar), and because the reasoning behind a decision is worth
having even after the decision has shipped. They are **not** kept because they are
accurate — several of them describe a plan rather than the code.

If you want to know how the system actually works, read [`../docs/`](../docs/00_INDEX.md).
`docs/` is the build contract; this directory is a notebook.

| File | What it is |
|---|---|
| `12_Launch_Plan.md` | Milestone plan M5–M19, defect log, budget and scale assumptions |
| `Launch_Go_No_Go.md` | A point-in-time release-readiness checklist |
| `V2_Audit_and_Migration_Map.md` | Phase 0 of the V2 plan: what V1 actually contains, what survives, and the milestone sequence |
| `V2_Migration_Validation_M2E3.md` | M2E-3: the V1→V2 migration dry-run results, limitations and readiness verdict |
| `V2_Migration_Fidelity_M2F.md` | M2F: the seven fidelity gaps M2E found, and what each would take to close. A proposal — nothing in it is implemented |
| `V2_Migration_Fidelity_M2F_Amendment.md` | M2F amendment: the approved findings as numbered V2 domain invariants, and the three migration-validation gates. Also a proposal |
| `V2_Release_Validation_RestoredProduction.md` | The release gate: the migration run against a restored copy of real production data, with all three gates |
| `m2e_dryrun/*.json` | The dry-run measurements that report is computed from |
| `04_Interview_Defense.md` | Personal notes — gitignored, absent from a clone |

`V2_Audit_and_Migration_Map.md` was filed here rather than beside the V2 Master Plan in
`docs/plans/` because, at the time, `NEVER_PUBLISH` in `frontend/lib/docs.ts` was a
**per-file** denylist naming two exact paths — so a third file under `docs/plans/` would
have been published at a URL nothing linked to.

M0B fixed that: publication is now decided per directory, and an unclassified directory
fails the build. `docs/plans/` would be a safe home today. It stays here anyway, because
this directory is a notebook and that is what the document is — but the choice is now
editorial rather than forced.

**Do not link to these from `docs/` or from the README.** The docs site renders every
Markdown file under `docs/`, so a note that belongs here and is filed there gets published.
