# Deferred work

Patches for work that was started, is real, and is **not** shipping in the release being
prepared. They live here rather than in a `git stash` because a stash is local to one
machine and one clone: the container this was developed in is reclaimed on idle, and a
stash goes with it. Anything worth resuming has to survive that.

Each patch applies with `git apply` against the commit named in its header. If it has gone
stale, the issue it references is the source of truth, not the patch.

| Patch | Issue | Why it is deferred |
|---|---|---|
| `issue-54-cancellation-durable-state.patch` | #54 | See below |

## #54 — cancellation is advisory, not durable

**The defect is real.** "Stop research" records an intent and nothing enforces it. The run
continues; when it finishes, the outcome writer overwrites the stopped session with
`AWAITING_APPROVAL` or `COMPLETED`. The user is shown a stopped run, then a live one, with
nothing explaining the transition — and approving at that point puts a report they tried to
abandon into project memory. `AGENTS.md` already records this as a known deliberate gap on
both hosts, including that the server's Redis `cancelled` key is read by nothing.

**Why it is not in this release.** The patch is ~123 insertions across five files and adds
Alembic migration `0019` to the `sessions` table, changes both hosts' outcome writers, and
touches the ORM model that the desktop's `create_all` plus startup column sync reads. That
is a schema change and a behavioural change to the write path on the server *and* the
desktop, and it arrived during final release hardening with no tests and no documentation.
Landing it here would trade a documented, long-standing limitation for an undocumented,
untested change to how every run's terminal state is written — on the two code paths this
repository has the worst track record of keeping in step.

**What finishing it requires**, so the next person does not rediscover it:

1. The migration *and* the ORM model, because the desktop builds its schema from
   `create_all` rather than from Alembic (`AGENTS.md`, "Schema → an Alembic migration for
   Postgres *and* the ORM model").
2. A status check in **both** outcome writers — `pipeline_runner::_persist_outcome` and
   `sidecar::_apply_outcome` — since a fix in one is the divergence this repository keeps
   shipping.
3. Tests that assert a cancelled run's terminal state *survives* a completing outcome, on
   both hosts. Negative-control them: without the guard the run must come back
   `COMPLETED`.
4. A decision, written down, on what a cancelled-then-completed run shows in History, and
   whether its report is reachable at all.
