"use client";

import { useState } from "react";

import { useV2PlanReview } from "@/hooks/v2";
import type { PlanTask, V2RunGraph } from "@/lib/types";

import { EmptyState } from "@/components/ui/EmptyState";

/**
 * The design gate.
 *
 * **Approving a plan is not approving a report**, and nothing in this panel may suggest
 * otherwise: no "verified", no artifact language, and the button says what happens next —
 * research starts.
 *
 * The panel also has to answer "why am I looking at this?", which the first version did
 * not: it opened on a bare list of queries with two buttons under it. A reviewer who does
 * not know what a research task is cannot approve one, so the list is framed by what the
 * planner did and what approving will cause.
 */

interface OutlineSection {
  title: string;
  description?: string;
}

/**
 * A plan task as this panel handles it: fully typed on a native run, and a bare
 * `{id, query}` on a migrated one whose original plan was free-form text.
 */
type PlanTaskish = PlanTask | { id: number; query: string };

/** The plan's tasks are `PlanTask[]` on a native run and free-form on a migrated one. */
function asTask(value: unknown, index: number): PlanTaskish {
  if (typeof value === "object" && value !== null && "query" in value) return value as PlanTask;
  return { id: index + 1, query: String(value) };
}

function asSection(value: unknown): OutlineSection {
  if (typeof value === "object" && value !== null && "title" in value) {
    const s = value as { title: unknown; description?: unknown };
    return {
      title: String(s.title),
      description: typeof s.description === "string" ? s.description : undefined,
    };
  }
  return { title: String(value) };
}

export function PlanPanel({ graph }: { graph: V2RunGraph }) {
  const review = useV2PlanReview(graph.run.id);
  const [feedback, setFeedback] = useState("");
  // `null` means "not edited yet, mirror the server". Seeded on first use rather than in
  // an effect, which is this codebase's rule for derived state (frontend/AGENTS.md).
  const [edited, setEdited] = useState<PlanTaskish[] | null>(null);
  const plan = graph.plans[graph.plans.length - 1];
  const decision = graph.reviews.find((r) => r.gate === "PLAN");

  if (!plan) {
    return (
      <EmptyState
        title="No plan recorded"
        description="This run did not stop at the design gate, so no plan was put to a reviewer."
      />
    );
  }

  const open = graph.run.status === "AWAITING_PLAN" && !decision;
  const tasks = edited ?? plan.tasks.map(asTask);
  const sections = plan.outline_sections.map(asSection);

  // A planner may propose a task already excluded, and one actually proposed *every* task
  // that way (run 63091d21): this panel counted the raw list, announced "4 research
  // areas", and the reviewer approved a plan that searched nothing. The count has to be
  // what will be researched, not what was written down — the panel is the only place a
  // V2 reviewer sees the plan, and it renders no per-task control to correct it with.
  //
  // Absent means selected, because that is how the backend reads it
  // (`t.get("include", True)`); migrated V1 plans carry no flag at all, and a UI that
  // treated absent as excluded would report every one of them as researching nothing.
  const isSelected = (t: PlanTaskish) => (t as PlanTask).include !== false;
  const selected = tasks.filter(isSelected);
  const excludedCount = tasks.length - selected.length;
  const noneSelected = tasks.length > 0 && selected.length === 0;

  const setAll = (include: boolean) =>
    setEdited(tasks.map((t) => ({ ...(t as PlanTask), include })));
  const toggle = (index: number, include: boolean) =>
    setEdited(
      tasks.map((t, i) => (i === index ? { ...(t as PlanTask), include } : (t as PlanTask))),
    );
  const origin =
    plan.origin === "MODEL_PROPOSED"
      ? "proposed by the planner"
      : plan.origin === "HUMAN_EDITED"
        ? "edited by a human"
        : plan.origin === "TEMPLATE"
          ? "from a report template"
          : // UNKNOWN appears only on plans migrated from V1, which could not tell the
            // model's proposal from a human's edit. Said, not guessed.
            "origin not recorded (migrated from a V1 session)";

  return (
    <div className="space-y-4">
      <section className="card" aria-labelledby="plan-heading">
        <h3 id="plan-heading" className="font-serif text-base font-bold text-text-primary">
          Research plan
        </h3>
        <p className="mt-1 text-sm leading-relaxed text-text-secondary">
          {tasks.length > 0 ? (
            <>
              The planner broke your question into{" "}
              <strong className="text-text-primary">
                {selected.length} research area{selected.length === 1 ? "" : "s"}
              </strong>
              {excludedCount > 0 && (
                <>
                  {" "}
                  and excluded {excludedCount} more
                </>
              )}
              . {open ? "Review them before any searching starts." : "Research ran against them."}
            </>
          ) : (
            "The planner recorded no research areas for this run."
          )}
        </p>

        {/* Only while a decision is pending. On a run that already ran, the per-task
            "excluded" labels and the count above are the honest record; telling a reader
            what "approving would do" about a gate that closed weeks ago is noise. */}
        {noneSelected && open && (
          <p
            role="alert"
            className="mt-3 border border-danger-line bg-danger-soft p-3 text-xs leading-relaxed text-text-primary"
          >
            <strong className="text-danger">Every research area is excluded.</strong> Approving
            this plan would search nothing, and a report produced with no evidence can only be
            written from the model&apos;s own memory — so the server refuses the approval.
            Select at least one below, or use “Request changes” to have the plan proposed
            again.
          </p>
        )}
        <p className="mt-2 font-mono text-[length:var(--text-micro)] text-text-muted">
          Version {plan.version} · {origin}
          {plan.approved_at && " · approved"}
        </p>

        <div className="mt-4 flex flex-wrap items-center justify-between gap-2">
          <h4 className="font-mono text-[length:var(--text-micro)] font-semibold uppercase tracking-wider text-text-muted">
            What will be researched
          </h4>
          {/* Only while a decision is pending: on a finished run these would offer to edit
              a plan that has already been executed. */}
          {open && tasks.length > 0 && (
            <div className="flex gap-2">
              <button
                type="button"
                className="btn btn-secondary px-2 py-1 text-xs"
                disabled={review.isPending || selected.length === tasks.length}
                onClick={() => setAll(true)}
              >
                Select all
              </button>
              <button
                type="button"
                className="btn btn-secondary px-2 py-1 text-xs"
                disabled={review.isPending || selected.length === 0}
                onClick={() => setAll(false)}
              >
                Clear all
              </button>
            </div>
          )}
        </div>
        <ol className="mt-2 space-y-2">
          {tasks.map((t, i) => {
            const full = t as PlanTask;
            const included = isSelected(t);
            return (
              <li
                key={i}
                className={`border border-border p-2.5 ${included ? "" : "opacity-60"}`}
              >
                <div className="flex items-baseline gap-2">
                  {/* Editable only while the gate is open. A closed gate renders the same
                      list read-only, so the record of what ran cannot be altered after. */}
                  {open ? (
                    <input
                      type="checkbox"
                      checked={included}
                      disabled={review.isPending}
                      onChange={(e) => toggle(i, e.target.checked)}
                      aria-label={`Research “${t.query}”`}
                      className="mt-0.5 h-4 w-4 shrink-0"
                    />
                  ) : (
                    <span className="shrink-0 font-mono text-[length:var(--text-micro)] text-text-muted">
                      {i + 1}
                    </span>
                  )}
                  <span className="min-w-0 break-words text-sm text-text-primary">{t.query}</span>
                  {/* Labelled, not just dimmed: "excluded" is the whole difference between
                      a plan that researches this and one that does not, and opacity alone
                      carries nothing to a screen reader or a low-contrast display. */}
                  {!included && (
                    <span className="shrink-0 font-mono text-[length:var(--text-micro)] uppercase tracking-wider text-danger">
                      excluded
                    </span>
                  )}
                </div>
                {full.rationale && (
                  <p className="mt-1 pl-5 text-xs leading-relaxed text-text-secondary">
                    {full.rationale}
                  </p>
                )}
                {full.subtopics?.length > 0 && (
                  <p className="mt-1 pl-5 text-xs text-text-muted">
                    Covers: {full.subtopics.join(" · ")}
                  </p>
                )}
              </li>
            );
          })}
        </ol>

        {sections.length > 0 && (
          <>
            <h4 className="mt-4 font-mono text-[length:var(--text-micro)] font-semibold uppercase tracking-wider text-text-muted">
              How the report will be structured
            </h4>
            <ul className="mt-2 space-y-1">
              {sections.map((sec, i) => (
                <li key={i} className="text-sm text-text-primary">
                  {sec.title}
                  {sec.description && (
                    <span className="text-text-secondary"> — {sec.description}</span>
                  )}
                </li>
              ))}
            </ul>
          </>
        )}
      </section>

      {open ? (
        <section className="card" aria-labelledby="plan-decision">
          <h3 id="plan-decision" className="text-sm font-semibold text-text-primary">
            Your decision
          </h3>
          <label
            htmlFor="plan-feedback"
            className="mt-3 block text-[0.8125rem] font-medium text-text-secondary"
          >
            Changes to request
          </label>
          <textarea
            id="plan-feedback"
            value={feedback}
            onChange={(e) => setFeedback(e.target.value)}
            rows={3}
            placeholder="What should the plan cover instead?"
            className="textarea-base mt-1.5 w-full"
            aria-describedby="plan-feedback-hint"
          />
          <p id="plan-feedback-hint" className="mt-1.5 text-xs text-text-muted">
            Only sent with &ldquo;Request changes&rdquo;. Approving ignores this box.
          </p>
          <div className="mt-3 flex flex-wrap gap-2">
            <button
              type="button"
              className="btn btn-primary"
              // Disabled rather than left to fail: the server refuses this approval with a
              // 422, and a button that always errors is a worse answer than one that says
              // it cannot be used. The server check is still the authority.
              disabled={review.isPending || noneSelected}
              // `tasks` only when the reviewer actually edited something: an unedited
              // approval must stay recorded as approving the *model's* proposal, not as a
              // human edit that happens to be identical.
              onClick={() =>
                review.mutate({
                  decision: "APPROVED",
                  ...(edited ? { tasks: edited as PlanTask[] } : {}),
                })
              }
            >
              {review.isPending && <span className="spinner" />}
              Approve plan
            </button>
            <button
              type="button"
              className="btn btn-secondary"
              disabled={review.isPending}
              onClick={() =>
                review.mutate({ decision: "REWORK_REQUESTED", feedback: feedback || null })
              }
            >
              Request changes
            </button>
          </div>
          <p className="mt-3 text-xs leading-relaxed text-text-secondary">
            Approving the plan starts the research. It does <strong>not</strong> approve a
            report and creates no artifact — you will review the draft separately.
          </p>
          {review.isError && (
            <p className="mt-2 text-xs text-danger" role="alert">
              Couldn&apos;t record that decision: {(review.error as Error).message}
            </p>
          )}
        </section>
      ) : (
        <p className="text-xs text-text-secondary">
          {decision
            ? decision.decision === "APPROVED"
              ? "You approved this plan. Research ran against it."
              : `This plan was ${decision.decision.replace(/_/g, " ").toLowerCase()}.`
            : "The plan gate is closed for this run."}
        </p>
      )}
    </div>
  );
}
