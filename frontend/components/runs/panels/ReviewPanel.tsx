"use client";

import { useState } from "react";

import { Disclosure } from "@/components/ui/Disclosure";
import { EmptyState } from "@/components/ui/EmptyState";
import { useReportReview, useV2Verification } from "@/hooks/runs";
import type { RunGraph } from "@/lib/types";

import { Hash, Stat, runTotals } from "../primitives";

/**
 * The report gate — the decision that creates a verifiable artifact.
 *
 * A reviewer has to be able to answer four questions before pressing the button, and the
 * panel is organised around them: *what am I approving*, *what was actually checked*, *has
 * the report changed since I last looked*, and *what exactly gets signed*. The last one is
 * the report hash, which was nowhere on this surface — the approval is a signature over
 * that string, and a signature whose subject is invisible is a worse guarantee than none.
 *
 * The verifier preview is the second addition. `GET /verification` assembles the bundle
 * live before approval — the backend's own words for it are "the honest answer to *what
 * would be frozen if I approved this?*" — and the UI only ever called it *after* approval,
 * so the one moment the answer is decision-relevant was the one moment it was not asked.
 * `frozen: false` distinguishes the preview from the artifact's own verdict, and is shown.
 */

const CHECK_COPY: Record<string, string> = {
  bundle_integrity: "Bundle integrity",
  report_integrity: "Report integrity",
  evidence_integrity: "Evidence integrity",
  citation_resolution: "Citation resolution",
  claim_evidence_linkage: "Claim / evidence linkage",
  approval_chain: "Approval chain",
  schema_validity: "Schema validity",
};

export function ReviewPanel({ graph, onShowTab }: { graph: RunGraph; onShowTab: (tab: string) => void }) {
  const totals = runTotals(graph);
  const review = useReportReview(graph.run.id);
  const [feedback, setFeedback] = useState("");
  const open = !graph.artifact && Boolean(totals.latest);
  // Only asked while a decision is actually open: on an approved run the Artifact tab runs
  // the same query against the frozen payload, and two callers would verify twice.
  const preview = useV2Verification(graph.run.id, open);

  if (graph.artifact) {
    return (
      <EmptyState
        title="Already approved"
        description="This run has a verifiable artifact. See the Artifact tab for its checks and downloads."
      />
    );
  }
  if (!totals.latest) {
    return (
      <EmptyState
        title="Nothing to review"
        description="This run has not produced a report, so there is no draft to approve."
      />
    );
  }

  const prior = graph.reviews.filter((r) => r.gate === "REPORT");
  const reworked = prior.filter((r) => r.decision === "REWORK_REQUESTED");
  const gateOpen = graph.run.status === "AWAITING_REVIEW";

  return (
    <div className="space-y-4">
      <section className="card" aria-labelledby="approving">
        <h3 id="approving" className="text-sm font-semibold text-text-primary">
          What you are approving
        </h3>
        <p className="mt-1 text-xs leading-relaxed text-text-secondary">
          Revision {totals.latest.version}
          {graph.revisions.length > 1 && ` of ${graph.revisions.length}`}, and the evidence
          chain underneath it.
        </p>

        <dl className="mt-3 grid gap-3 text-sm sm:grid-cols-2">
          <Stat label="Claims in the report" value={totals.claims.length} />
          <Stat
            label="Claims with supporting evidence"
            value={`${totals.supported} of ${totals.claims.length}`}
            warn={totals.unsupported > 0}
          />
          <Stat label="Evidence items" value={totals.evidence} />
          <Stat
            label="Sources cited"
            value={`${totals.citedSources} cited · ${totals.uncitedSources} retrieved only`}
          />
          <Stat
            label="Conflicting claim pairs"
            value={totals.contradictions}
            warn={totals.contradictions > 0}
          />
          <Stat
            label="Citation resolution"
            value={
              graph.run.citation_resolution_rate === null
                ? "not measured"
                : `${Math.round(graph.run.citation_resolution_rate * 100)}%`
            }
            hint={
              graph.run.citation_resolution_rate === null
                ? "Not recorded for this run. Not the same as 0%."
                : undefined
            }
          />
        </dl>

        <div className="mt-4 border-t border-border pt-3">
          <p className="text-xs text-text-secondary">
            Approving signs this exact text. The signature is over its hash:
          </p>
          <p className="mt-1.5 flex flex-wrap items-center gap-2">
            <Hash value={totals.latest.report_hash} label="Report hash being approved" />
            <button
              type="button"
              onClick={() => onShowTab("report")}
              className="text-xs text-accent hover:underline"
            >
              Read the report again →
            </button>
          </p>
        </div>

        {reworked.length > 0 && (
          <div className="mt-3 border-t border-border pt-3">
            <p className="text-xs text-text-secondary">
              You asked for {reworked.length} rework{reworked.length === 1 ? "" : "s"} on this
              run. Each produced a new revision; none overwrote an earlier one.
            </p>
          </div>
        )}
      </section>

      {(totals.unsupported > 0 || totals.uncheckedEvidence > 0 || totals.contradictions > 0) && (
        <div
          className="border p-3 text-xs"
          style={{
            color: "var(--warning)",
            backgroundColor: "var(--warning-soft)",
            borderColor: "var(--warning-line)",
          }}
        >
          <p className="font-medium">Before you approve</p>
          <ul className="mt-1.5 list-disc space-y-1 pl-4 leading-relaxed">
            {totals.unsupported > 0 && (
              <li>
                {totals.unsupported} claim{totals.unsupported === 1 ? "" : "s"} resolved to no
                evidence.{" "}
                <button
                  type="button"
                  onClick={() => onShowTab("claims")}
                  className="underline hover:no-underline"
                >
                  See which
                </button>
              </li>
            )}
            {totals.uncheckedEvidence > 0 && (
              <li>
                {totals.uncheckedEvidence} evidence item
                {totals.uncheckedEvidence === 1 ? " carries" : "s carry"} no per-item
                verification. Unchecked is not verified.
              </li>
            )}
            {totals.contradictions > 0 && (
              <li>
                {totals.contradictions} conflicting pair
                {totals.contradictions === 1 ? " remains" : "s remain"} unresolved.{" "}
                <button
                  type="button"
                  onClick={() => onShowTab("contradictions")}
                  className="underline hover:no-underline"
                >
                  Read them
                </button>
              </li>
            )}
          </ul>
        </div>
      )}

      <section className="card" aria-labelledby="would-verify">
        <h3 id="would-verify" className="text-sm font-semibold text-text-primary">
          What the verifier would say
        </h3>
        <p className="mt-1 text-xs leading-relaxed text-text-secondary">
          The standalone verifier, run against the bundle this approval would freeze. It is a
          preview, not the artifact&apos;s own verdict — nothing is frozen until you approve.
        </p>
        <div className="mt-3 space-y-1.5">
          {preview.isLoading && (
            <p className="text-xs text-text-muted">
              <span className="spinner mr-1.5 inline-block align-[-2px]" />
              Assembling the bundle and running the verifier…
            </p>
          )}
          {preview.isError && (
            <p className="text-xs text-text-muted">
              The verifier preview could not be loaded. That says nothing about this report —
              it is this page failing to ask, not a check failing.
            </p>
          )}
          {preview.data?.assembled === false && (
            <p className="text-xs text-text-muted">
              No bundle can be assembled yet: {preview.data.reason}. This is not a failed
              check — the verifier did not run.
            </p>
          )}
          {preview.data?.checks.map((c) => (
            <div key={c.name} className="flex flex-wrap items-start gap-2 text-xs">
              <span className={c.passed ? "text-success" : "text-danger"} aria-hidden>
                {c.passed ? "✓" : "✕"}
              </span>
              <span className="text-text-primary">{CHECK_COPY[c.name] ?? c.name}</span>
              <span className="sr-only">{c.passed ? "passes" : "fails"}</span>
              {!c.passed && c.detail && (
                <span className="min-w-0 break-words text-danger">
                  — {c.detail.split("\n")[0]}
                </span>
              )}
            </div>
          ))}
        </div>
      </section>

      <section className="card" aria-labelledby="your-decision">
        <h3 id="your-decision" className="text-sm font-semibold text-text-primary">
          Your decision
        </h3>
        {!gateOpen && (
          <p className="mt-1 text-xs text-warning">
            This run is not currently parked at the review gate ({graph.run.status
              .replace(/_/g, " ")
              .toLowerCase()}
            ). A decision may be refused.
          </p>
        )}
        <label
          htmlFor="rework-feedback"
          className="mt-3 block text-[0.8125rem] font-medium text-text-secondary"
        >
          Feedback for a rework
        </label>
        <textarea
          id="rework-feedback"
          value={feedback}
          onChange={(e) => setFeedback(e.target.value)}
          rows={3}
          placeholder="What should the next revision do differently?"
          className="textarea-base mt-1.5 w-full"
          aria-describedby="rework-hint"
        />
        <p id="rework-hint" className="mt-1.5 text-xs text-text-muted">
          Only sent with &ldquo;Request rework&rdquo;. Approving ignores this box.
        </p>
        <div className="mt-3 flex flex-wrap gap-2">
          <button
            type="button"
            className="btn btn-primary"
            disabled={review.isPending}
            onClick={() => review.mutate({ decision: "APPROVED" })}
          >
            {review.isPending && <span className="spinner" />}
            Approve report
          </button>
          <button
            type="button"
            className="btn btn-secondary"
            disabled={review.isPending}
            onClick={() =>
              review.mutate({ decision: "REWORK_REQUESTED", feedback: feedback || null })
            }
          >
            Request rework
          </button>
        </div>
        <p className="mt-3 text-xs leading-relaxed text-text-secondary">
          Approving creates a <strong>verifiable research artifact</strong>: a frozen copy of
          this report, its evidence, its claims and this decision, hashed so a third party can
          check it offline without trusting this app.
        </p>
        {review.isError && (
          <p className="mt-2 text-xs text-danger" role="alert">
            Couldn&apos;t record that decision: {(review.error as Error).message}
          </p>
        )}

        {prior.length > 0 && (
          <div className="mt-3 border-t border-border pt-3">
            <Disclosure label={`${prior.length} earlier decision${prior.length === 1 ? "" : "s"}`}>
              <ul className="space-y-1.5 text-xs">
                {prior.map((r) => (
                  <li key={r.id} className="flex flex-wrap items-center gap-2">
                    <span className="font-mono text-text-muted">#{r.sequence}</span>
                    <span className="text-text-primary">
                      {r.decision.replace(/_/g, " ").toLowerCase()}
                    </span>
                    <Hash value={r.reviewed_hash} label="Reviewed hash" />
                    {r.feedback && (
                      <span className="min-w-0 break-words text-text-secondary">
                        — {r.feedback}
                      </span>
                    )}
                  </li>
                ))}
              </ul>
            </Disclosure>
          </div>
        )}
      </section>
    </div>
  );
}
