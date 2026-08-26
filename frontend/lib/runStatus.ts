import type { RunStatus } from "./types";

/**
 * One status vocabulary for a run — the list, the card, the header and the filters
 * (docs/07 §2, Phase 7).
 *
 * The session equivalent lives in `lib/status.ts` and is a different union: a run adds
 * `AWAITING_REVIEW` and `CANCELLED`, and has no `AWAITING_APPROVAL`. They are kept
 * separate rather than merged because a merged map would have to accept a status neither
 * host can actually produce, and `Record<RunStatus, …>` is what makes "added a status
 * and forgot a surface" a type error instead of a blank badge.
 *
 * `sentence` is the run page's status line and `label` is the badge; both exist because
 * a list needs two words and a header needs an explanation, and deriving one from the
 * other produced either a cryptic badge or a paragraph in a table cell.
 */
export interface V2StatusMeta {
  /** CSS token name (without `--`). Colour is never the sole carrier — the label is. */
  token: string;
  label: string;
  /** What this status means, in a sentence, for the run header. */
  sentence: string;
  /** Waiting on a person rather than on the pipeline. */
  needsYou?: boolean;
  /** The server still has something to say — drives the pulse and the live subscription. */
  live?: boolean;
}

export const V2_STATUS_META: Record<RunStatus, V2StatusMeta> = {
  PENDING: {
    token: "text-muted",
    label: "Queued",
    sentence: "Queued. Waiting for a worker to pick this run up.",
    live: true,
  },
  RUNNING: {
    token: "info",
    label: "Running",
    sentence: "Running. This page updates as the pipeline reports in.",
    live: true,
  },
  // Both gates are amber: to someone scanning a list they are one urgency class —
  // "waiting on you" — and the label says which decision is owed.
  AWAITING_PLAN: {
    token: "warning",
    label: "Plan review",
    sentence: "Paused before searching: the research plan is waiting for your approval.",
    needsYou: true,
  },
  AWAITING_REVIEW: {
    token: "warning",
    label: "Needs review",
    sentence: "Paused: a draft report is waiting for your review.",
    needsYou: true,
  },
  COMPLETED: {
    token: "success",
    label: "Approved",
    sentence: "Approved. A verifiable artifact exists for this run.",
  },
  CANCELLED: {
    token: "text-muted",
    label: "Stopped",
    sentence: "A stop was requested. Work already in flight ran to its next checkpoint.",
  },
  FAILED: {
    token: "danger",
    label: "Failed",
    sentence: "This run failed before producing a report.",
  },
};

/** Every run status, in the order a run moves through them. */
export const RUN_STATUS_ORDER: RunStatus[] = [
  "PENDING",
  "RUNNING",
  "AWAITING_PLAN",
  "AWAITING_REVIEW",
  "COMPLETED",
  "CANCELLED",
  "FAILED",
];

/**
 * Never throws on a status the client has not been taught.
 *
 * A backend that adds a state before the frontend ships is the ordinary case during a
 * rolling deploy, and a crashed History page is a worse answer than an honest "unrecognised":
 * the raw wire value is shown rather than mapped onto the nearest familiar one, because
 * guessing here would print a status the run is not in.
 */
export function runStatusMeta(status: string): V2StatusMeta {
  return (
    V2_STATUS_META[status as RunStatus] ?? {
      token: "text-muted",
      label: status.replace(/_/g, " ").toLowerCase(),
      sentence: `This run reports a status this page does not recognise (${status}).`,
    }
  );
}
