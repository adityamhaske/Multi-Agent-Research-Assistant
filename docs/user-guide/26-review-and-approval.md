# Review and approval

Two human checkpoints. Neither can be skipped from the app's run form, and both are durable
— the graph stops, the worker exits, and your decision resumes it hours later from exactly
where it paused.

## Why the gates exist

Auto-finalising a research report means shipping whatever the model produced. The gates make
that a decision rather than a default, and they record it: every approval writes an audit
row with the SHA-256 of the exact draft that was reviewed. That hash is what lets the
[bundle export](29-exports.md) prove an approval applies to *this* report and not to an
earlier draft.

The two gates are at deliberately different moments:

| | Design gate | Review gate |
|---|---|---|
| When | After the planner, **before any search** | After the synthesizer, before finalising |
| Session status | `AWAITING_PLAN` | `AWAITING_APPROVAL` |
| What you are approving | The research plan and report structure | The finished draft |
| Cost so far | Effectively nothing | The whole run |
| Your edits change | What gets researched | What the final report says |

## The design gate

The run pauses with the planner's proposal: a list of research tasks, each with its query,
rationale, and subtopics, plus a proposed report outline.

You can:

- **Reword a task.** What you write is what gets searched.
- **Drop a task.** Unchecking it removes it from the run entirely — the executor never sees
  it. A review that could not remove anything would be a rubber stamp.
- **Add tasks.** Up to 24, which is deliberately more than the 6 the planner may propose
  unprompted: the whole point of the gate is adding the subtopics the planner missed.
- **Edit the outline** — section titles and descriptions — or choose a different template.

Leaving a section untouched means *unedited*, and that is not the same as empty: submitting
an explicitly empty task list is rejected, because a plan with nothing in it researches
nothing.

Approving stamps the decision on the session, writes a `plan_approved` audit row hashing the
design you signed off on, and resumes the run. What is stored is what you **decided**, not
what was proposed — so a later reader sees the design behind the report.

The gate is the product default. The app's run form always sends "do not skip". A script
posting the API body it posted before this gate existed keeps its old behaviour, so
integrations do not start pausing at a checkpoint they cannot see; the same is true for the
CLI and the evaluation harness, neither of which can render or resume a second interrupt.

## The review gate

The run pauses with the draft and a summary of what you are about to approve:

- **word count** and **source count**;
- **unresolved contradictions** — how many conflicting-claim pairs the detector found and
  did not resolve. The report surfaces them; the gate makes the count impossible to miss.
- **cost so far**.

Read the draft with the citation chips live: hovering any `[n]` shows the source and the
verbatim snippet behind that claim, so reviewing the citations is part of reviewing the
draft rather than a separate audit. ([Citations](27-citations.md))

### Approve

The session resumes at the **finalizer**, not at the planner. The research you already paid
for is not repeated — a regression test asserts the planner is invoked exactly once across
submit and approve. The draft becomes the final report, the sources table is persisted, the
citation resolution rate is computed and stored, and the session moves to `COMPLETED`.

On the server build, approving is also what admits the report into
[project memory](28-projects-and-memory.md). Only approved research is ever retrievable —
drafts, rejected work, and failed runs never enter it. Approving is curating.

### Send it back

Rejecting requires feedback; that is enforced, because "rejected" with no reason gives the
synthesizer nothing to act on.

The run resumes at the **synthesizer** with your feedback and the same evidence. Nothing is
re-searched. Feedback can change emphasis, structure, and tone — it explicitly cannot
authorise an uncited claim. The synthesizer is told this directly.

The redrafted report comes back to the same gate. **Rework is bounded at three rounds**;
after that the gate refuses further rework and you approve or abandon the session.

## What becomes final

Only an approved draft becomes `final_report`. Until then a session carries `draft_report`,
and exports fall back to it — clearly, because a session that has not been approved is not
`COMPLETED` and the bundle export refuses to run at all.

The audit trail carries every decision in order: each `approved` or `rework_requested`
action, its verbatim feedback, the hash of the draft it applied to, and its timestamp. The
bundle export carries that chain, and its verifier checks that at least one `approved` entry
hashes to the report you are holding.
