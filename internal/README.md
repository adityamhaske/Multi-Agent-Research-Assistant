# Internal engineering notes

**This directory is not documentation.** Nothing here is published to the documentation
site, linked from the docs navigation, or maintained to the standard `docs/` is held to.

It is a notebook: milestone sequencing, budget assumptions, and decision archaeology. It is
kept because a large number of source comments cite it by number (`docs/12 M7`, and
similar), and because the reasoning behind a decision is worth having after the decision has
shipped. It is **not** kept because it is accurate — parts of it describe a plan rather than
the code.

If you want to know how the system actually works, read [`../docs/`](../docs/00_INDEX.md).
`docs/` is the build contract; this directory is a notebook.

| File | What it is |
|---|---|
| `12_Launch_Plan.md` | Milestone plan M5–M19, defect log, budget and scale assumptions. Cited from source comments as `docs/12`. |
| `04_Interview_Defense.md` | Personal notes — gitignored, absent from a clone |

**Do not link to these from `docs/` or from the README.** The docs site renders every
Markdown file under `docs/`, so a note that belongs here and is filed there gets published.
Directory classification in `frontend/lib/docs.ts` fails the build on an unclassified
directory, which is the backstop rather than the rule.
