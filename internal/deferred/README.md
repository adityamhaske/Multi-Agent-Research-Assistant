# Deferred work

Patches for work that was started, is real, and is **not** shipping in the release being
prepared. They live here rather than in a `git stash` because a stash is local to one
machine and one clone: the container this was developed in is reclaimed on idle, and a
stash goes with it. Anything worth resuming has to survive that.

Each patch applies with `git apply` against the commit named in its header. If it has gone
stale, the issue it references is the source of truth, not the patch.

| Patch | Issue | Why it is deferred |
|---|---|---|
| _(none)_ | | |

## Resolved

**#54 — cancellation is advisory, not durable.** Shipped in V2.0.0; the patch that lived
here has been deleted rather than left to rot beside the code that supersedes it. What
landed is larger than what was parked: the parked patch covered the two V1 writers, and the
V2 adapter turned out to have the same race with a worse failure — `ck_run_cancelled` made
the late write raise `IntegrityError` inside the worker, which kept the status correct by
accident and rolled the run's spend back to zero. The shipped fix guards all three writers,
preserves spend on each, stops `lifecycle_event` announcing COMPLETED for a run the user
stopped, and is pinned by `backend/tests/test_cancellation_is_authoritative.py`, which
forces the t0 → t1 → t2 order rather than avoiding it.

The four conditions this file recorded for finishing it were met: the migration *and* the
ORM model (`0019_sessions_cancelled_at`, and the desktop's `_add_missing_columns` picks the
column up from `Base.metadata` on an existing install); a guard in both V1 outcome writers;
tests with negative controls proving each guard is load-bearing; and a written decision on
what a cancelled-then-completed run shows — it stays `FAILED` with "Research stopped by
user", keeps its spend, and never gains the draft report, so there is nothing to approve.
