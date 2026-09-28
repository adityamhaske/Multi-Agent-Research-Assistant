# Agent instructions

Each of the five agents in the pipeline runs on instructions that ship with the product. From
3.0.0 you can replace them with your own — to change how the planner breaks a question down,
what the critic accepts as good evidence, how the synthesizer writes — while the checks that
keep a report honest go on running on the shipped instructions, whatever you write.

This page covers what you can change, when a change takes effect, and how anyone reading your
research can tell that it ran on instructions of yours. It applies to the desktop app and the
server alike.

## The five agents

| Agent | What it does | What your instructions replace |
|---|---|---|
| **Planner** | Breaks your question into research tasks | Its planning prompt |
| **Executor** | Runs the searches and gathers evidence | Its research prompt |
| **Critic** | Grades that evidence and sends weak work back | Its grading of each task's evidence — and nothing else it does |
| **Synthesizer** | Writes the cited report | Its drafting prompt, not the repair pass |
| **Follow-up chat** | Answers questions about a finished report | Its prompt for chat about one report, not project chat |

Five agents run nine prompts between them, and whether a prompt can be replaced is decided per
prompt, not per agent. That is how instructions for the critic reach its grading while the
citation verifier — which is also the critic's — keeps running as shipped.

## What cannot be rewritten

Four prompts are protected, and nothing you save reaches them:

- **Citation verification** — the check that a cited sentence is supported by its snippet.
- **Contradiction detection** — the pass that finds sources that cannot both hold.
- **Report repair** — the pass that fixes a draft's uncited sentences.
- **Project chat** — including its instruction to refuse anything the approved research does
  not cover.

The refusal is enforced in one place, before any saved instruction is read, so there is no
second route to a protected prompt. The guarantees that do not live in a prompt at all hold
whatever an agent is told: an evidence snippet must be text the tools actually fetched, citation
markers are validated against the evidence, the critic still fails closed on output it cannot
parse, and the planner's output is still schema-checked.
([Security](../architecture/06-security.md))

Where a shipped prompt tells the model that retrieved web content is data and never
instructions, the system adds that rule before and after your text. It is not part of what you
edit and cannot be removed; the editor says so on each agent it applies to.

## Customizing an agent

Open **Settings → Agents**. Each agent shows whether it is on its **Shipped** or **Customized**
instructions, and which model it runs on — changed under Settings → Models, not here.

1. Choose **Customize**, or **Edit instructions** on an agent you already changed. The editor
   starts from what runs today: your saved text, or else the shipped prompt.
2. Edit. Each agent takes up to **2,500 characters**, and the counter says when you are over.
3. **Save instructions.**

To go back, use **Reset to default** on the agent's card; it resets that agent alone. Emptying
the box is not a reset — an agent needs instructions, so an empty prompt is refused rather than
read as "use the default".

Instructions belong to your account and apply to every run you start. There is no per-run
override, and the pipeline's agents are fixed: you cannot add one.

## When a change takes effect

| | Your saved instructions apply |
|---|---|
| A research run | From its start to its end. The run keeps the instructions it started with through both human gates and every rework |
| Follow-up chat | On your next message |

A run reads your instructions once, when it starts, and keeps that copy. Editing an agent while
a run waits for you at the design gate or the review gate changes your next run, not that one —
a report is never written under two sets of instructions.

If the copy a run took cannot be used — it fails the checks the editor applies — the run does not
apply part of it. Every agent runs on its shipped instructions, and the run records that it did.

Research recorded as a session, on the earlier pipeline, never applies them, and a session that
ignored them says so.

## What gets recorded

Every run records whether it ran on your instructions, in four places:

- **The run** keeps its copy of your instructions, and whether they were applied (`APPLIED`),
  absent (`NONE`), or could not be used (`UNUSABLE`).
- **The Artifact tab** lists every agent that ran on replaced instructions, with each prompt's
  SHA-256, above the verifier's checks — every check can pass on a run whose agents were
  reconfigured, so a reader should know that first.
- **The verification bundle** carries every prompt the run used: its full text, its SHA-256, and
  whether it was replaced. Editing any of it after the fact fails the bundle's integrity check.
  ([Bundle format](../reference/15-bundle-format.md))
- **The standalone verifier** prints a banner above its verdict, then lists the replaced prompts:

  ```
  !! CUSTOMISED AGENTS — one or more prompts were replaced by the run's owner.
  !! The checks below confirm what those prompts were and that they are
  !! unmodified since assembly, not that they were sound.
  ```

**Your instructions travel with the bundle.** They are written into it in full, so anyone you
share a bundle with can read them. Keep nothing in an agent's instructions that you would not
hand to a reader of your research.

## Bundle compatibility

Bundles from 3.0.0 on are format version 2, which is what records the prompts. A verifier from
before 3.0.0 knows only version 1 and refuses them, so check a bundle with the verifier from
3.0.0 or later — it verifies both versions. Research recorded before 3.0.0 still exports as a
version 1 bundle with no prompts in it: they were never captured, and the bundle does not
invent them.

## Measuring instructions before you trust them

Changing an agent's instructions changes the research it produces. The evaluation harness can
run a candidate set of instructions against the same fixed questions and the same thresholds as
the shipped prompts, and report the two side by side:

```bash
cd backend
python -m evals.harness --judge <provider:model> --candidate my-agents.json
```

`my-agents.json` holds one entry per agent you changed, such as `{"planner": "…", "critic":
"…"}`. A candidate that scores worse is reported, not refused — the choice stays yours. What a
candidate can and cannot reach is in [Testing and evaluation](../developers/08-testing-and-evaluation.md).

## From the API

Instructions are the `prompt_overrides` preference, set through `PATCH /auth/me` and merged per
agent: `{"preferences": {"prompt_overrides": {"planner": "…"}}}` sets the planner and leaves the
others alone, and `{"planner": null}` resets it. `GET /models/prompt-defaults` returns what each
editor starts from. ([API reference](../reference/34-api.md))

## Limits

- Instructions apply per account, to every run; there is no per-run override, and no agents of
  your own.
- Research recorded as a session does not apply them.
- A bundle shares them, in full, with whoever receives it.
- Research recorded before 3.0.0 has no instructions recorded, and never will.
