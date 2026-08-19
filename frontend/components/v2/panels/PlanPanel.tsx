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

/** The plan's tasks are `PlanTask[]` on a native run and free-form on a migrated one. */
function asTask(value: unknown, index: number): PlanTask | { id: number; query: string } {
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
  const tasks = plan.tasks.map(asTask);
  const sections = plan.outline_sections.map(asSection);
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
                {tasks.length} research area{tasks.length === 1 ? "" : "s"}
              </strong>
              . {open ? "Review them before any searching starts." : "Research ran against them."}
            </>
          ) : (
            "The planner recorded no research areas for this run."
          )}
        </p>
        <p className="mt-2 font-mono text-[length:var(--text-micro)] text-text-muted">
          Version {plan.version} · {origin}
          {plan.approved_at && " · approved"}
        </p>

        <h4 className="mt-4 font-mono text-[length:var(--text-micro)] font-semibold uppercase tracking-wider text-text-muted">
          What will be researched
        </h4>
        <ol className="mt-2 space-y-2">
          {tasks.map((t, i) => {
            const full = t as PlanTask;
            return (
              <li key={i} className="border border-border p-2.5">
                <div className="flex items-baseline gap-2">
                  <span className="shrink-0 font-mono text-[length:var(--text-micro)] text-text-muted">
                    {i + 1}
                  </span>
                  <span className="min-w-0 break-words text-sm text-text-primary">{t.query}</span>
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
              disabled={review.isPending}
              onClick={() => review.mutate({ decision: "APPROVED" })}
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
