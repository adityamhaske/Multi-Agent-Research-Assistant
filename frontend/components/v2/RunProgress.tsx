"use client";

import { useMemo } from "react";

import { AGENT_TOKEN } from "@/lib/pipeline";
import { deriveStages, type Stage, type StageState } from "@/lib/v2Progress";
import type { AgentEvent, V2RunGraph } from "@/lib/types";

/**
 * What a run is doing right now.
 *
 * The V2 run page subscribed to the event stream and then threw the events away — it read
 * only `degraded` off the hook — so a run that takes minutes showed a static status line
 * and nothing else. This is the missing half: the same events, rendered as the steps that
 * have observably happened.
 *
 * **No percentage, no bar, no elapsed-time extrapolation.** The backend publishes discrete
 * events and a status; it does not publish completion, so a bar would be the frontend
 * inventing a measurement — the one thing this product must never do. The derivation lives
 * in `lib/v2Progress.ts` and is tested there; this file only draws it.
 *
 * Colour is reinforcement, never the carrier: every stage states its own state in words
 * (and in an `sr-only` phrase for a screen reader), and the marker is redundant with it.
 */

const STAGE_COLOR: Record<string, string> = {
  planner: `var(--${AGENT_TOKEN.planner})`,
  executor: `var(--${AGENT_TOKEN.executor})`,
  critic: `var(--${AGENT_TOKEN.critic})`,
  synthesizer: `var(--${AGENT_TOKEN.synthesizer})`,
  "plan-gate": "var(--agent-hitl)",
  review: "var(--agent-hitl)",
};

const STATE_WORD: Record<StageState, string> = {
  pending: "Not started",
  active: "In progress",
  done: "Done",
  waiting: "Waiting for you",
  stopped: "Did not run",
};

function Marker({ state, color }: { state: StageState; color: string }) {
  if (state === "done") {
    return (
      <span aria-hidden style={{ color }} className="font-mono text-sm leading-none">
        ✓
      </span>
    );
  }
  if (state === "active") {
    return (
      <span
        aria-hidden
        className="spinner"
        style={{ color, width: "0.75rem", height: "0.75rem" }}
      />
    );
  }
  if (state === "waiting") {
    return (
      <span
        aria-hidden
        className="status-marker"
        style={{ backgroundColor: "var(--warning)" }}
      />
    );
  }
  // "Did not run" and "not started yet" are different findings, so they are different
  // marks. Drawn as a dash rather than a second empty box: an outline one shade darker
  // than another outline is not a distinction anybody reads.
  if (state === "stopped") {
    return (
      <span aria-hidden className="font-mono text-sm leading-none text-text-muted">
        –
      </span>
    );
  }
  return (
    <span
      aria-hidden
      className="status-marker"
      style={{ backgroundColor: "transparent", border: "1px solid var(--border)" }}
    />
  );
}

function StageRow({ stage }: { stage: Stage }) {
  const color = STAGE_COLOR[stage.id] ?? "var(--text-muted)";
  const dim = stage.state === "pending" || stage.state === "stopped";
  return (
    <li className="flex items-start gap-2.5 py-1">
      <span className="mt-1 flex h-3 w-3 shrink-0 items-center justify-center">
        <Marker state={stage.state} color={color} />
      </span>
      <span className="min-w-0">
        <span
          className={`block text-[0.8125rem] ${
            dim ? "text-text-muted" : "text-text-primary"
          } ${stage.state === "active" || stage.state === "waiting" ? "font-medium" : ""}`}
        >
          {stage.label}
        </span>
        {stage.detail && (
          <span className="block text-xs text-text-secondary">{stage.detail}</span>
        )}
        <span className="sr-only">{STATE_WORD[stage.state]}</span>
      </span>
    </li>
  );
}

export function RunProgress({
  graph,
  events,
  degraded,
}: {
  graph: V2RunGraph;
  events: AgentEvent[];
  /** The stream is not delivering. Said out loud rather than left to look like a stall. */
  degraded: boolean;
}) {
  const stages = useMemo(
    () =>
      deriveStages({
        status: graph.run.status,
        events,
        planGate: !graph.run.skip_plan_gate,
        planDecided: graph.reviews.some((r) => r.gate === "PLAN"),
      }),
    [graph.run.status, graph.run.skip_plan_gate, graph.reviews, events],
  );

  // The last thing the pipeline actually said. Shown verbatim: a paraphrase here would be
  // the frontend narrating a run it cannot see.
  const lastMessage = [...events].reverse().find((e) => e.message)?.message ?? null;

  return (
    <section aria-labelledby="run-progress" className="card">
      <h2
        id="run-progress"
        className="font-mono text-[length:var(--text-micro)] font-semibold uppercase tracking-wider text-text-muted"
      >
        Progress
      </h2>
      <ol className="mt-2">
        {stages.map((s) => (
          <StageRow key={s.id} stage={s} />
        ))}
      </ol>

      {lastMessage && (
        <p className="mt-3 border-t border-border pt-2 text-xs text-text-secondary">
          <span className="font-mono text-[length:var(--text-micro)] uppercase tracking-wider text-text-muted">
            Latest{" "}
          </span>
          {lastMessage}
        </p>
      )}

      {degraded && (
        <p
          className="mt-3 border p-2 text-xs"
          style={{
            color: "var(--warning)",
            backgroundColor: "var(--warning-soft)",
            borderColor: "var(--warning-line)",
          }}
        >
          The live connection dropped. It reconnects automatically and replays anything
          missed, so nothing is lost — this page is not stuck.
        </p>
      )}
    </section>
  );
}
