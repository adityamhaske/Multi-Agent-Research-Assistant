"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import toast from "react-hot-toast";

import { OutlineTemplatePicker } from "@/components/session/OutlineTemplatePicker";
import { queryKeys, useSessionPlan, useSubmitPlan } from "@/hooks/queries";
import { ApiError } from "@/lib/api";
import { formatCost } from "@/lib/format";
import type { OutlineSection, PlanTask, SessionDetail } from "@/lib/types";

/**
 * The research design gate (docs/07 §2, Phase 4).
 *
 * This is the difference between "the agent picked 6 queries" and "these are my six
 * subtopics, in my review's structure" — and it is the last moment before the run starts
 * spending. Everything editable here changes what the executor actually researches:
 * excluding a task removes it from the run, and the approved outline becomes the
 * synthesizer's section contract.
 *
 * Local state is seeded from the fetched plan and owned here until submit. The
 * alternative — writing each keystroke through the query cache — would make every edit a
 * re-render of the whole gate and would fight the cache update that lands on success.
 */

const MAX_TASKS = 24;

function blankTask(id: number): PlanTask {
  return { id, query: "", rationale: "", subtopics: [], include: true, source_hint: null };
}

function PlanSkeleton() {
  return (
    <div className="space-y-3" aria-hidden>
      {[0, 1, 2].map((i) => (
        <div key={i} className="h-20 animate-pulse bg-bg-elevated" />
      ))}
    </div>
  );
}

export function PlanGate({ session }: { session: SessionDetail }) {
  const id = session.session_id;
  const qc = useQueryClient();
  const planQuery = useSessionPlan(id);
  const submit = useSubmitPlan(id);

  // `undefined` means "not edited yet, mirror the server". Seeding into state on first
  // render rather than in an effect keeps this a pure derivation — the codebase's
  // no-setState-in-an-effect rule (frontend/AGENTS.md).
  const [draftTasks, setDraftTasks] = useState<PlanTask[] | undefined>();
  const [draftOutline, setDraftOutline] = useState<OutlineSection[] | undefined>();

  const tasks = draftTasks ?? planQuery.data?.tasks ?? [];
  const outline = draftOutline ?? planQuery.data?.outline ?? [];
  const included = tasks.filter((t) => t.include);
  const busy = submit.isPending;

  const setTasks = (next: PlanTask[]) => setDraftTasks(next);
  const patchTask = (index: number, patch: Partial<PlanTask>) =>
    setTasks(tasks.map((t, i) => (i === index ? { ...t, ...patch } : t)));

  const move = (index: number, delta: number) => {
    const target = index + delta;
    if (target < 0 || target >= tasks.length) return;
    const next = [...tasks];
    [next[index], next[target]] = [next[target], next[index]];
    setTasks(next);
  };

  const onSubmit = async () => {
    // Optimistically flip to RUNNING so the monitor re-subscribes immediately, exactly
    // as ApprovalGate does at the other gate; a failure re-fetches the true status.
    qc.setQueryData<SessionDetail>(queryKeys.session(id), (old) =>
      old ? { ...old, status: "RUNNING" } : old,
    );
    try {
      await submit.mutateAsync({
        // Renumber 1..n so the ids the reviewer sees match the ids the executor tags
        // evidence with. Trimmed queries, because a whitespace-only edit would fail the
        // server's min-length check with a message about a field the user cannot see.
        tasks: included.map((t, i) => ({ ...t, id: i + 1, query: t.query.trim() })),
        outline: outline.filter((s) => s.title.trim()).map((s) => ({ ...s, title: s.title.trim() })),
      });
      toast.success("Plan approved — starting research.");
    } catch (err) {
      qc.invalidateQueries({ queryKey: queryKeys.session(id) });
      toast.error(err instanceof ApiError ? err.message : "Could not submit the plan.");
    }
  };

  if (planQuery.isLoading) return <PlanSkeleton />;

  if (planQuery.isError || !planQuery.data) {
    return (
      <div className="card text-center">
        <p className="text-sm text-text-secondary">
          Couldn&apos;t load this run&apos;s research plan.
        </p>
        <button onClick={() => planQuery.refetch()} className="btn btn-secondary mt-3">
          Retry
        </button>
      </div>
    );
  }

  const emptyQuery = included.some((t) => t.query.trim().length < 3);
  const canSubmit = included.length > 0 && !emptyQuery && !busy;

  return (
    <div className="grid gap-6 lg:grid-cols-[1fr_20rem]">
      <div className="min-w-0 space-y-6">
        {/* Subtopics */}
        <section aria-labelledby="plan-heading" className="card p-6">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <h2 id="plan-heading" className="font-serif text-lg font-bold text-text-primary">
              Research plan
            </h2>
            <p className="text-xs text-text-muted">
              Each of these becomes one round of search. Nothing has been spent yet.
            </p>
          </div>

          <ol className="mt-4 space-y-3">
            {tasks.map((task, i) => (
              <li
                key={i}
                className="border p-3"
                style={{
                  borderColor: "var(--border)",
                  backgroundColor: task.include ? "var(--bg-surface)" : "var(--bg-elevated)",
                  opacity: task.include ? 1 : 0.6,
                }}
              >
                <div className="flex items-start gap-3">
                  <label className="flex items-center gap-2 pt-2">
                    <input
                      type="checkbox"
                      checked={task.include}
                      disabled={busy}
                      onChange={(e) => patchTask(i, { include: e.target.checked })}
                      className="h-4 w-4"
                    />
                    <span className="sr-only">Include “{task.query || "untitled task"}”</span>
                  </label>

                  <div className="min-w-0 flex-1 space-y-2">
                    <label className="sr-only" htmlFor={`task-${i}`}>
                      Search query for task {i + 1}
                    </label>
                    <input
                      id={`task-${i}`}
                      type="text"
                      value={task.query}
                      disabled={busy}
                      onChange={(e) => patchTask(i, { query: e.target.value })}
                      placeholder="A concrete, independently searchable question"
                      className="input-base w-full text-sm"
                    />
                    {task.rationale && (
                      <p className="text-xs leading-relaxed text-text-muted">{task.rationale}</p>
                    )}
                    <label className="sr-only" htmlFor={`subtopics-${i}`}>
                      Subtopics for task {i + 1}, comma separated
                    </label>
                    <input
                      id={`subtopics-${i}`}
                      type="text"
                      value={task.subtopics.join(", ")}
                      disabled={busy}
                      onChange={(e) =>
                        patchTask(i, {
                          subtopics: e.target.value
                            .split(",")
                            .map((s) => s.trim())
                            .filter(Boolean),
                        })
                      }
                      placeholder="Subtopics (comma separated, optional)"
                      className="input-base w-full font-mono text-xs"
                    />
                  </div>

                  <div className="flex flex-col gap-1">
                    <button
                      type="button"
                      onClick={() => move(i, -1)}
                      disabled={busy || i === 0}
                      className="btn btn-secondary px-2 py-1 text-xs disabled:opacity-30"
                      aria-label={`Move task ${i + 1} earlier`}
                    >
                      ↑
                    </button>
                    <button
                      type="button"
                      onClick={() => move(i, 1)}
                      disabled={busy || i === tasks.length - 1}
                      className="btn btn-secondary px-2 py-1 text-xs disabled:opacity-30"
                      aria-label={`Move task ${i + 1} later`}
                    >
                      ↓
                    </button>
                  </div>
                </div>
              </li>
            ))}
          </ol>

          <button
            type="button"
            onClick={() => setTasks([...tasks, blankTask(tasks.length + 1)])}
            disabled={busy || tasks.length >= MAX_TASKS}
            className="btn btn-secondary mt-3 w-full text-sm"
          >
            {tasks.length >= MAX_TASKS ? `Limit is ${MAX_TASKS} tasks` : "+ Add a subtopic"}
          </button>
        </section>

        {/* Outline */}
        <section aria-labelledby="outline-heading" className="card p-6">
          <h2 id="outline-heading" className="font-serif text-lg font-bold text-text-primary">
            Report structure
          </h2>
          <p className="mt-1 text-xs text-text-muted">
            The sections the report will be written in. Leave it empty for the default
            structure.
          </p>

          <div className="mt-4">
            <OutlineTemplatePicker
              sections={outline}
              onChange={setDraftOutline}
              disabled={busy}
            />
          </div>

          <ol className="mt-4 space-y-2">
            {outline.map((section, i) => (
              <li key={i} className="flex items-center gap-2">
                <span className="font-mono text-xs text-text-muted tabular-nums">{i + 1}</span>
                <label className="sr-only" htmlFor={`section-${i}`}>
                  Section {i + 1} title
                </label>
                <input
                  id={`section-${i}`}
                  type="text"
                  value={section.title}
                  disabled={busy}
                  onChange={(e) =>
                    setDraftOutline(
                      outline.map((s, j) => (j === i ? { ...s, title: e.target.value } : s)),
                    )
                  }
                  className="input-base flex-1 text-sm"
                />
                <button
                  type="button"
                  onClick={() => setDraftOutline(outline.filter((_, j) => j !== i))}
                  disabled={busy}
                  className="btn btn-secondary px-2 py-1 text-xs"
                  aria-label={`Remove section ${section.title || i + 1}`}
                >
                  ✕
                </button>
              </li>
            ))}
          </ol>

          <button
            type="button"
            onClick={() => setDraftOutline([...outline, { title: "", description: "" }])}
            disabled={busy || outline.length >= MAX_TASKS}
            className="btn btn-secondary mt-3 w-full text-sm"
          >
            + Add a section
          </button>
        </section>
      </div>

      {/* Decision panel — same shape as the draft gate's, so the two gates read as one
          pattern rather than two features. */}
      <aside className="lg:sticky lg:top-20 lg:self-start">
        <div className="card space-y-4 p-5">
          <div>
            <h2 className="font-serif text-base font-bold text-text-primary">Design gate</h2>
            <p className="mt-1 text-xs text-text-muted">
              Approve this plan to start researching. Editing it here is free; changing it
              afterwards is not.
            </p>
          </div>

          <dl className="space-y-2 border-y border-border py-3 text-sm">
            <div className="flex justify-between">
              <dt className="text-text-muted">Subtopics to research</dt>
              <dd className="font-mono tabular-nums text-text-primary">
                {included.length} of {tasks.length}
              </dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-text-muted">Report sections</dt>
              <dd className="font-mono tabular-nums text-text-primary">
                {outline.length || "Default"}
              </dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-text-muted">Spent so far</dt>
              <dd className="font-mono tabular-nums text-text-primary">
                {formatCost(session.total_cost_usd)}
              </dd>
            </div>
          </dl>

          <button
            type="button"
            onClick={onSubmit}
            disabled={!canSubmit}
            className="btn btn-primary w-full"
          >
            {busy && <span className="spinner" />}
            Approve &amp; start research
          </button>

          {included.length === 0 && (
            <p role="alert" className="text-xs" style={{ color: "var(--danger)" }}>
              Keep at least one subtopic — a plan with nothing in it researches nothing.
            </p>
          )}
          {emptyQuery && (
            <p role="alert" className="text-xs" style={{ color: "var(--danger)" }}>
              Every included subtopic needs a search query of at least 3 characters.
            </p>
          )}
        </div>
      </aside>
    </div>
  );
}
