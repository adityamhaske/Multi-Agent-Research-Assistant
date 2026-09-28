# Review and approval

Two human checkpoints, both durable — the graph stops, the worker exits, and your decision
resumes it hours later from exactly where it paused. The review gate cannot be skipped. The
design gate is on by default, and the run form's options can turn it off for a run that
should start searching immediately.

## Why the gates exist

Auto-finalising a research report means shipping whatever the model produced. The gates make
that a decision rather than a default, and they record it: every decision is a review bound to
the SHA-256 of exactly what was reviewed. That hash is what lets the
[bundle export](29-exports.md) prove an approval applies to *this* report and not to an
earlier draft.

The two gates are at deliberately different moments:

| | Design gate | Review gate |
|---|---|---|
| When | After the planner, **before any search** | After the synthesizer, before anything is final |
| Run status | `AWAITING_PLAN` | `AWAITING_REVIEW` |
| What you are approving | The research plan | The draft, and the evidence chain under it |
| Cost so far | Effectively nothing | The whole run |
| Your decision changes | What gets researched | What becomes final |

Your [agent instructions](38-agent-instructions.md) do not change at either gate. A run keeps
the instructions it started with, so editing an agent while a run waits for you changes your
next run, not this one.

## The design gate

The run pauses with the planner's proposal: the research areas it chose — each with its query,
the reason for it, and the subtopics it covers — and how the report will be structured.

**Uncheck an area and it is never researched** — the executor never sees it. *Select all* and
*Clear all* work on the whole list. A review that could not remove anything would be a rubber
stamp.

Approving with nothing selected is refused: a plan with nothing in it researches nothing, and a
report written from no evidence could only come from the model's memory. When you changed the
selection, what you approved is recorded as its own plan version, marked as edited by a human,
so a later reader sees both the design the run executed and what the planner proposed.

**Approve plan** starts the research. It does not approve a report and creates no artifact —
you review the draft separately.

**Request changes** records your feedback against the plan. It does not yet send the plan back
to the planner, and the app does not reopen the gate afterwards; to research with a different
plan, stop the run and start another.

## The review gate

The run pauses with the draft, and the **Review** tab shows what you are about to approve:

- how many claims the report makes, and how many have supporting evidence;
- how many evidence items there are, and how many sources were cited versus only retrieved;
- how many pairs of claims conflict;
- the citation resolution rate — *not measured* until you approve, and never shown as `0%`;
- the SHA-256 of the exact revision your approval will sign.

Read the draft with its citation chips live: hovering any `[n]` shows the source and the
verbatim snippet behind that claim, so reviewing the citations is part of reviewing the draft
rather than a separate audit. ([Citations](27-citations.md))

### Approve

Approving records your decision against the hash of the revision you read, measures its
citation resolution rate, and freezes the artifact — all in one transaction, so an approval
that cannot produce a verifiable artifact is not recorded as an approval. The run moves to
`COMPLETED`. Nothing is re-researched and no model is called.

The approved report is then saved into the project's corpus and, on the server, into
[project memory](28-projects-and-memory.md). Both are best-effort, after the approval is
committed: an embedding provider that is down costs those copies, never the approval. Only
approved research is ever retrievable there — drafts, reworked revisions and failed runs never
enter it. Approving is curating.

### Request rework

The run resumes at the **synthesizer** with your feedback and the same evidence. Nothing is
re-searched, so a rework costs one synthesis rather than a whole run. Feedback can change
emphasis, structure and tone; it explicitly cannot authorise an uncited claim, and the
synthesizer is told so.

The redraft is a new revision and comes back to the same gate. The revision you read is never
overwritten — each one stays readable, and the review records which one every decision was
about.

## What becomes final

Only an approved revision is frozen into an artifact, and only a report approval can create
one — a plan approval never does. That rule is enforced in the database, in the application, in
the bundle's serialization and in the verifier.

Every decision is kept, in order: each approval and each rework request, its feedback, the hash
of what it applied to, and when. The bundle carries that chain, and its verifier checks that at
least one approval hashes to the report you are holding.

One limitation worth knowing as a reviewer: a decision is recorded before the work it triggers
is dispatched, so in the rare case that the dispatch fails, the record can show a decision whose
work never ran, and nothing reconciles the two.

Research recorded as a session, on the earlier pipeline, went through gates of its own — among
other differences, its design gate let you reword and add tasks. Those sessions stay readable;
nothing in the app starts a new one.
