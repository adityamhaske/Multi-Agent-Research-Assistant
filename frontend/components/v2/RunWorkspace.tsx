"use client";

import { useMemo, useState } from "react";

import { Disclosure } from "@/components/ui/Disclosure";
import { EmptyState } from "@/components/ui/EmptyState";
import { useV2Cancel, useV2PlanReview, useV2ReportReview, useV2Verification } from "@/hooks/v2";
import { apiBase } from "@/lib/desktop";
import type { V2Claim, V2Contradiction, V2Evidence, V2RunGraph, V2Source } from "@/lib/types";

import { CitationChip, Hash, ProvenanceChip, runTotals } from "./primitives";

/**
 * The V2 research workspace.
 *
 * The tab order *is* the argument the product makes: a report is the end of a chain, not the
 * whole of it.
 *
 *     Report → Claims → Evidence → Sources → Contradictions → Review → Artifact
 *
 * Every tab reads the same `V2RunGraph`, so the counts on one cannot disagree with the rows
 * on another, and moving claim → evidence → source is a filter rather than a fetch.
 *
 * Three distinctions the layout refuses to blur, because they are the product:
 * retrieved ≠ verified, retrieved ≠ cited, and a citation marker ≠ evidence.
 */

type Tab =
  | "plan"
  | "report"
  | "claims"
  | "evidence"
  | "sources"
  | "contradictions"
  | "review"
  | "artifact";

export function RunWorkspace({ graph }: { graph: V2RunGraph }) {
  const totals = useMemo(() => runTotals(graph), [graph]);
  // The tab a run's current state demands, or null when nothing is waiting on a person.
  const demanded: Tab | null = graph.artifact
    ? "artifact"
    : graph.run.status === "AWAITING_REVIEW"
      ? "review"
      : graph.run.status === "AWAITING_PLAN"
        ? "plan"
        : null;

  const [tab, setTab] = useState<Tab>(demanded ?? "report");

  // Re-route when the run REACHES a gate, not only when the page is first opened.
  //
  // Found by the end-to-end journey: a run watched from RUNNING through to
  // AWAITING_REVIEW left the reviewer on the Report tab with the decision hidden behind
  // another one, because the opening tab was computed once by `useState`. Written as
  // setState-during-render keyed on the demanded tab — the codebase's "reset state when a
  // prop changes" pattern — rather than an effect, so the correct tab is painted in the
  // same commit as the new status instead of one frame later.
  const [lastDemanded, setLastDemanded] = useState<Tab | null>(demanded);
  if (demanded !== lastDemanded) {
    setLastDemanded(demanded);
    if (demanded) setTab(demanded);
  }
  const [focusClaim, setFocusClaim] = useState<string | null>(null);
  const [focusSource, setFocusSource] = useState<string | null>(null);

  const tabs: { id: Tab; label: string; count?: number | null }[] = [
    ...(graph.plans.length > 0 ? [{ id: "plan" as const, label: "Plan" }] : []),
    { id: "report", label: "Report" },
    { id: "claims", label: "Claims", count: totals.claims.length },
    { id: "evidence", label: "Evidence", count: totals.evidence },
    { id: "sources", label: "Sources", count: totals.sources },
    { id: "contradictions", label: "Contradictions", count: totals.contradictions },
    { id: "review", label: "Review" },
    { id: "artifact", label: "Artifact" },
  ];

  return (
    <div className="space-y-4">
      <div role="tablist" aria-label="Research run" className="flex flex-wrap gap-1 border-b border-border-subtle">
        {tabs.map((t) => (
          <button
            key={t.id}
            role="tab"
            aria-selected={tab === t.id}
            onClick={() => setTab(t.id)}
            className={`-mb-px border-b-2 px-3 py-2 text-[0.8125rem] font-medium transition-colors ${
              tab === t.id
                ? "border-accent text-accent"
                : "border-transparent text-text-secondary hover:text-text-primary"
            }`}
          >
            {t.label}
            {t.count !== undefined && t.count !== null && (
              <span className="ml-1.5 text-text-muted">{t.count}</span>
            )}
          </button>
        ))}
      </div>

      <div role="tabpanel">
        {tab === "plan" && <PlanPanel graph={graph} />}
        {tab === "report" && <ReportPanel graph={graph} />}
        {tab === "claims" && (
          <ClaimsPanel
            graph={graph}
            onInspectSource={(id) => {
              setFocusSource(id);
              setTab("sources");
            }}
          />
        )}
        {tab === "evidence" && <EvidencePanel graph={graph} focusClaim={focusClaim} />}
        {tab === "sources" && <SourcesPanel graph={graph} focus={focusSource} />}
        {tab === "contradictions" && (
          <ContradictionsPanel
            graph={graph}
            onInspectEvidence={(claimId) => {
              setFocusClaim(claimId);
              setTab("evidence");
            }}
          />
        )}
        {tab === "review" && <ReviewPanel graph={graph} />}
        {tab === "artifact" && <ArtifactPanel graph={graph} />}
      </div>
    </div>
  );
}

/* ── Plan ───────────────────────────────────────────────────────────────────── */

/**
 * The design gate. **Approving a plan is not approving a report**, and nothing in this
 * panel may suggest otherwise: no "verified", no artifact language, and the button says
 * what happens next — research starts.
 */
function PlanPanel({ graph }: { graph: V2RunGraph }) {
  const review = useV2PlanReview(graph.run.id);
  const [feedback, setFeedback] = useState("");
  const plan = graph.plans[graph.plans.length - 1];
  const decided = graph.reviews.some((r) => r.gate === "PLAN");

  if (!plan) {
    return <EmptyState title="No plan" description="This run did not stop at the design gate." />;
  }

  const open = graph.run.status === "AWAITING_PLAN" && !decided;

  return (
    <div className="space-y-3">
      <div className="card p-4">
        <h3 className="text-sm font-semibold text-text-primary">Research plan</h3>
        <p className="mt-1 text-xs text-text-secondary">{graph.run.question}</p>
        <p className="mt-2 text-[0.6875rem] text-text-muted">
          Version {plan.version} ·{" "}
          {plan.origin === "MODEL_PROPOSED" ? "proposed by the planner" : plan.origin.toLowerCase()}
          {plan.approved_at && " · approved"}
        </p>

        <h4 className="mt-3 text-xs font-medium text-text-secondary">Tasks</h4>
        <ol className="mt-1 list-decimal space-y-1 pl-5 text-sm text-text-primary">
          {plan.tasks.map((t, i) => (
            <li key={i}>{typeof t === "object" && t && "query" in t ? String(t.query) : String(t)}</li>
          ))}
        </ol>

        {plan.outline_sections.length > 0 && (
          <>
            <h4 className="mt-3 text-xs font-medium text-text-secondary">Report outline</h4>
            <ul className="mt-1 list-disc space-y-1 pl-5 text-sm text-text-primary">
              {plan.outline_sections.map((sec, i) => (
                <li key={i}>
                  {typeof sec === "object" && sec && "title" in sec
                    ? String((sec as { title: unknown }).title)
                    : String(sec)}
                </li>
              ))}
            </ul>
          </>
        )}
      </div>

      {open ? (
        <div className="card p-4">
          <label htmlFor="plan-feedback" className="text-sm font-medium text-text-primary">
            Changes to request
          </label>
          <textarea
            id="plan-feedback"
            value={feedback}
            onChange={(e) => setFeedback(e.target.value)}
            rows={2}
            placeholder="What should the plan cover instead?"
            className="input mt-2 w-full"
          />
          <div className="mt-3 flex flex-wrap gap-2">
            <button
              className="btn-secondary"
              disabled={review.isPending}
              onClick={() =>
                review.mutate({ decision: "REWORK_REQUESTED", feedback: feedback || null })
              }
            >
              Request changes
            </button>
            <button
              className="btn-primary"
              disabled={review.isPending}
              onClick={() => review.mutate({ decision: "APPROVED" })}
            >
              Approve plan
            </button>
          </div>
          <p className="mt-2 text-xs text-text-secondary">
            Approving the plan starts the research. It does <strong>not</strong> approve a
            report and creates no artifact — you will review the draft separately.
          </p>
          {review.isError && (
            <p className="mt-2 text-xs text-status-danger">{(review.error as Error).message}</p>
          )}
        </div>
      ) : (
        <p className="text-xs text-text-secondary">
          {decided
            ? "This plan has been decided. Research runs against it."
            : "The plan gate is closed for this run."}
        </p>
      )}
    </div>
  );
}

/* ── Report ─────────────────────────────────────────────────────────────────── */

function ReportPanel({ graph }: { graph: V2RunGraph }) {
  const { latest } = runTotals(graph);
  if (!latest) {
    return (
      <EmptyState
        title="No report yet"
        description="The run has not produced a revision. Evidence gathered so far is on the Evidence tab."
      />
    );
  }
  return (
    <div className="space-y-3">
      {graph.revisions.length > 1 && (
        <p className="text-xs text-text-secondary">
          Revision {latest.version} of {graph.revisions.length}. Earlier revisions are kept
          unchanged — a rework adds a version, it never overwrites one.
        </p>
      )}
      <article className="prose-report whitespace-pre-wrap text-sm leading-relaxed text-text-primary">
        {latest.report_markdown}
      </article>
      <p className="text-xs text-text-muted">
        Report hash <Hash value={latest.report_hash} /> · evidence watermark{" "}
        {latest.evidence_watermark}
      </p>
    </div>
  );
}

/* ── Claims ─────────────────────────────────────────────────────────────────── */

function ClaimsPanel({
  graph,
  onInspectSource,
}: {
  graph: V2RunGraph;
  onInspectSource: (sourceId: string) => void;
}) {
  const { claims } = runTotals(graph);
  const evidenceById = new Map(graph.evidence.map((e) => [e.id, e]));
  const sourceById = new Map(graph.sources.map((s) => [s.id, s]));

  if (claims.length === 0) {
    return <EmptyState title="No claims yet" description="Claims are derived when a report is produced." />;
  }

  return (
    <div className="space-y-2">
      <p className="text-xs text-text-secondary">
        Every sentence the report asserts, with the evidence it resolved to. A claim with no
        supporting evidence is shown as such rather than hidden — that is the point of listing
        them separately from the prose.
      </p>
      {claims.map((claim) => {
        const links = graph.claim_evidence_links.filter((l) => l.claim_id === claim.id);
        const support = links
          .map((l) => evidenceById.get(l.evidence_id))
          .filter((e): e is V2Evidence => Boolean(e));
        return (
          <div key={claim.id} className="card p-3">
            <p className="text-sm text-text-primary">{claim.text}</p>
            <div className="mt-2 flex flex-wrap items-center gap-2 text-[0.6875rem] text-text-muted">
              <span
                title="No claim-level verification has run. This is not a judgement that the claim is true or false."
                className="rounded bg-bg-elevated px-1.5 py-0.5"
              >
                {claim.verification_state}
              </span>
              <span>·</span>
              <span title="Claims are derived from the report's prose, not emitted as structured output.">
                {claim.extraction_method.toLowerCase().replace(/_/g, " ")}
              </span>
            </div>
            {support.length === 0 ? (
              <p className="mt-2 text-xs text-status-warning">
                No evidence resolved for this claim. Its citation markers, if any, pointed at
                nothing the run retrieved.
              </p>
            ) : (
              <Disclosure label={`${support.length} supporting evidence item${support.length === 1 ? "" : "s"}`}>
                <ul className="space-y-2">
                  {support.map((e) => {
                    const source = sourceById.get(e.source_id);
                    return (
                      <li key={e.id} className="rounded border border-border-subtle p-2">
                        <div className="flex items-center gap-2">
                          {source && <CitationChip source={source} />}
                          <ProvenanceChip state={e.provenance_state} />
                          {source && (
                            <button
                              onClick={() => onInspectSource(source.id)}
                              className="truncate text-xs text-accent hover:underline"
                            >
                              {source.title || source.url}
                            </button>
                          )}
                        </div>
                        <blockquote className="mt-1.5 border-l-2 border-border-subtle pl-2 text-xs text-text-secondary">
                          {e.snippet || <em>The snippet was blanked when it could not be found in the retrieved text.</em>}
                        </blockquote>
                      </li>
                    );
                  })}
                </ul>
              </Disclosure>
            )}
          </div>
        );
      })}
    </div>
  );
}

/* ── Evidence ───────────────────────────────────────────────────────────────── */

function EvidencePanel({ graph, focusClaim }: { graph: V2RunGraph; focusClaim: string | null }) {
  const sourceById = new Map(graph.sources.map((s) => [s.id, s]));
  const claimById = new Map(graph.claims.map((c) => [c.id, c]));
  const linksByEvidence = new Map<string, V2Claim[]>();
  for (const link of graph.claim_evidence_links) {
    const claim = claimById.get(link.claim_id);
    if (!claim) continue;
    linksByEvidence.set(link.evidence_id, [...(linksByEvidence.get(link.evidence_id) ?? []), claim]);
  }

  const rows = focusClaim
    ? graph.evidence.filter((e) =>
        graph.claim_evidence_links.some((l) => l.claim_id === focusClaim && l.evidence_id === e.id),
      )
    : graph.evidence;

  if (rows.length === 0) {
    return (
      <EmptyState
        title="No evidence recorded"
        description="Nothing was retrieved for this run, or the run has not reached the executor yet."
      />
    );
  }

  return (
    <div className="space-y-2">
      <p className="text-xs text-text-secondary">
        What the executor extracted, in the order it arrived. <strong>Retrieved is not
        verified</strong> — the provenance chip says whether anything checked this snippet
        against what the retriever actually returned.
      </p>
      {rows.map((e) => {
        const source = sourceById.get(e.source_id);
        const claims = linksByEvidence.get(e.id) ?? [];
        return (
          <div key={e.id} className="card p-3">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-[0.6875rem] text-text-muted">#{e.sequence}</span>
              {source && <CitationChip source={source} />}
              <ProvenanceChip state={e.provenance_state} />
              {source && (
                <a
                  href={source.url}
                  target="_blank"
                  rel="noreferrer noopener"
                  className="truncate text-xs text-accent hover:underline"
                >
                  {source.title || source.url}
                </a>
              )}
            </div>
            <blockquote className="mt-2 border-l-2 border-border-subtle pl-2 text-sm text-text-primary">
              {e.snippet || (
                <em className="text-text-muted">
                  Blanked: this snippet could not be found in what the retriever returned.
                </em>
              )}
            </blockquote>
            {e.key_fact && <p className="mt-1.5 text-xs text-text-secondary">{e.key_fact}</p>}
            <div className="mt-2 flex flex-wrap items-center gap-2 text-[0.6875rem] text-text-muted">
              <Hash value={e.content_hash} />
              {claims.length > 0 && <span>· supports {claims.length} claim{claims.length === 1 ? "" : "s"}</span>}
            </div>
          </div>
        );
      })}
    </div>
  );
}

/* ── Sources ────────────────────────────────────────────────────────────────── */

function SourcesPanel({ graph, focus }: { graph: V2RunGraph; focus: string | null }) {
  if (graph.sources.length === 0) {
    return <EmptyState title="No sources" description="Nothing was retrieved for this run." />;
  }
  const evidenceBySource = new Map<string, V2Evidence[]>();
  for (const e of graph.evidence) {
    evidenceBySource.set(e.source_id, [...(evidenceBySource.get(e.source_id) ?? []), e]);
  }
  const uncited = graph.sources.filter((s: V2Source) => s.citation_index === null);

  return (
    <div className="space-y-2">
      <p className="text-xs text-text-secondary">
        Everything the run retrieved. <strong>Retrieved is not cited</strong>: {uncited.length} of{" "}
        {graph.sources.length} carry no citation number because the report does not reference
        them. They are listed anyway — omitting them would overstate how much of the retrieval
        made it into the report.
      </p>
      {graph.sources.map((s) => {
        const evidence = evidenceBySource.get(s.id) ?? [];
        return (
          <div
            key={s.id}
            className={`card p-3 ${focus === s.id ? "ring-1 ring-accent" : ""} ${
              s.citation_index === null ? "border-dashed" : ""
            }`}
          >
            <div className="flex flex-wrap items-center gap-2">
              <CitationChip source={s} />
              <a
                href={s.url}
                target="_blank"
                rel="noreferrer noopener"
                className="truncate text-sm text-accent hover:underline"
              >
                {s.title || s.url}
              </a>
            </div>
            <p className="mt-1 truncate text-xs text-text-muted">{s.url}</p>
            <div className="mt-1.5 flex flex-wrap gap-3 text-[0.6875rem] text-text-muted">
              <span>{s.kind === "CORPUS" ? "Uploaded document" : "Web"}</span>
              <span title="How the source was obtained. UNKNOWN means the run did not record it.">
                {s.retrieval_status.toLowerCase().replace(/_/g, " ")}
              </span>
              <span>
                {evidence.length} evidence item{evidence.length === 1 ? "" : "s"}
              </span>
            </div>
          </div>
        );
      })}
    </div>
  );
}

/* ── Contradictions ─────────────────────────────────────────────────────────── */

function ContradictionsPanel({
  graph,
  onInspectEvidence,
}: {
  graph: V2RunGraph;
  onInspectEvidence: (claimId: string) => void;
}) {
  const sourceById = new Map(graph.sources.map((s) => [s.id, s]));
  const detected = graph.contradictions.filter((c) => c.detection_state === "DETECTED");
  const notRun = graph.contradictions.filter((c) => c.detection_state !== "DETECTED");

  if (graph.contradictions.length === 0) {
    return (
      <EmptyState
        title="No conflicting claims recorded"
        description="The detector ran and surfaced no pair where two sources cannot both be right."
      />
    );
  }

  return (
    <div className="space-y-3">
      {notRun.length > 0 && (
        <p className="rounded border border-status-warning/40 bg-status-warning-bg p-2 text-xs text-status-warning">
          {notRun.length} record{notRun.length === 1 ? "" : "s"} where the detector did not
          produce an anchored pair. A detector that could not run is not the same as a clean
          bill of health, so it is shown rather than dropped.
        </p>
      )}
      {detected.map((c: V2Contradiction) => {
        const a = c.source_a_id ? sourceById.get(c.source_a_id) : null;
        const b = c.source_b_id ? sourceById.get(c.source_b_id) : null;
        return (
          <div key={c.id} className="card p-0">
            <div className="grid gap-px bg-border-subtle md:grid-cols-2">
              <Side source={a} quote={c.quote_a} summary={c.summary_a} />
              <Side source={b} quote={c.quote_b} summary={c.summary_b} />
            </div>
            {c.nature && (
              <p className="border-t border-border-subtle p-3 text-xs text-text-secondary">
                <span className="font-medium text-text-primary">Why they conflict: </span>
                {c.nature}
              </p>
            )}
            <p className="border-t border-border-subtle px-3 py-2 text-[0.6875rem] text-text-muted">
              Surfaced, not resolved. The report does not decide between these — a reviewer does.
              {c.evidence_a_id === null && (
                <>
                  {" "}
                  The quoted text could not be matched to exactly one evidence item, so no
                  evidence link is claimed.
                </>
              )}
            </p>
          </div>
        );
      })}
      {detected.length > 0 && graph.claims.length > 0 && (
        <button
          onClick={() => onInspectEvidence(graph.claims[0]!.id)}
          className="text-xs text-accent hover:underline"
        >
          Inspect the evidence behind these claims →
        </button>
      )}
    </div>
  );
}

function Side({
  source,
  quote,
  summary,
}: {
  source: V2Source | null | undefined;
  quote: string | null;
  summary: string | null;
}) {
  return (
    <div className="bg-bg-surface p-3">
      {source ? (
        <a
          href={source.url}
          target="_blank"
          rel="noreferrer noopener"
          className="truncate text-xs font-medium text-accent hover:underline"
        >
          {source.title || source.url}
        </a>
      ) : (
        <span className="text-xs text-text-muted">Source not recorded</span>
      )}
      {summary && <p className="mt-1.5 text-sm text-text-primary">{summary}</p>}
      {quote && (
        <blockquote className="mt-1.5 border-l-2 border-border-subtle pl-2 text-xs text-text-secondary">
          {quote}
        </blockquote>
      )}
    </div>
  );
}

/* ── Review ─────────────────────────────────────────────────────────────────── */

function ReviewPanel({ graph }: { graph: V2RunGraph }) {
  const totals = runTotals(graph);
  const review = useV2ReportReview(graph.run.id);
  const [feedback, setFeedback] = useState("");

  if (graph.artifact) {
    return (
      <EmptyState
        title="Already approved"
        description="This run has a verifiable artifact. See the Artifact tab."
      />
    );
  }
  if (!totals.latest) {
    return <EmptyState title="Nothing to review" description="The run has not produced a report." />;
  }

  const unchecked = graph.evidence.filter((e) => e.provenance_state === "UNCHECKED").length;

  return (
    <div className="space-y-4">
      <div className="card p-4">
        <h3 className="text-sm font-semibold text-text-primary">What you are approving</h3>
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
          />
        </dl>
      </div>

      {(totals.unsupported > 0 || unchecked > 0 || totals.contradictions > 0) && (
        <div className="rounded border border-status-warning/40 bg-status-warning-bg p-3 text-xs text-status-warning">
          <p className="font-medium">Before you approve</p>
          <ul className="mt-1.5 list-disc space-y-1 pl-4">
            {totals.unsupported > 0 && (
              <li>
                {totals.unsupported} claim{totals.unsupported === 1 ? "" : "s"} resolved to no
                evidence.
              </li>
            )}
            {unchecked > 0 && (
              <li>
                {unchecked} evidence item{unchecked === 1 ? "" : "s"} carry no per-item
                verification. Unchecked is not verified.
              </li>
            )}
            {totals.contradictions > 0 && (
              <li>
                {totals.contradictions} conflicting pair
                {totals.contradictions === 1 ? "" : "s"} remain unresolved.
              </li>
            )}
          </ul>
        </div>
      )}

      <div className="card p-4">
        <label htmlFor="rework-feedback" className="text-sm font-medium text-text-primary">
          Feedback for a rework
        </label>
        <textarea
          id="rework-feedback"
          value={feedback}
          onChange={(e) => setFeedback(e.target.value)}
          rows={3}
          placeholder="What should the next revision do differently?"
          className="input mt-2 w-full"
        />
        <div className="mt-3 flex flex-wrap gap-2">
          <button
            className="btn-secondary"
            disabled={review.isPending}
            onClick={() =>
              review.mutate({ decision: "REWORK_REQUESTED", feedback: feedback || null })
            }
          >
            Request rework
          </button>
          <button
            className="btn-primary"
            disabled={review.isPending}
            onClick={() => review.mutate({ decision: "APPROVED" })}
          >
            Approve report
          </button>
        </div>
        <p className="mt-2 text-xs text-text-secondary">
          Approving creates a <strong>verifiable research artifact</strong>: a frozen copy of
          this report, its evidence, its claims and this decision, hashed so a third party can
          check it offline without trusting this app.
        </p>
        {review.isError && (
          <p className="mt-2 text-xs text-status-danger">{(review.error as Error).message}</p>
        )}
      </div>
    </div>
  );
}

function Stat({ label, value, warn }: { label: string; value: string | number; warn?: boolean }) {
  return (
    <div>
      <dt className="text-xs text-text-secondary">{label}</dt>
      <dd className={`text-sm font-medium ${warn ? "text-status-warning" : "text-text-primary"}`}>
        {value}
      </dd>
    </div>
  );
}

/* ── Artifact ───────────────────────────────────────────────────────────────── */

const CHECK_COPY: Record<string, string> = {
  bundle_integrity: "Bundle integrity",
  report_integrity: "Report integrity",
  evidence_integrity: "Evidence integrity",
  citation_resolution: "Citation resolution",
  claim_evidence_linkage: "Claim / evidence linkage",
  approval_chain: "Approval chain",
  schema_validity: "Schema validity",
};

function ArtifactPanel({ graph }: { graph: V2RunGraph }) {
  const { data, isLoading } = useV2Verification(graph.run.id, Boolean(graph.artifact));
  const base = apiBase();

  if (!graph.artifact) {
    return (
      <EmptyState
        title="No artifact yet"
        description="An artifact exists only once a human has approved a report at the review gate."
      />
    );
  }

  return (
    <div className="space-y-4">
      <div className="card p-4">
        <h3 className="text-sm font-semibold text-text-primary">Verified artifact</h3>
        <p className="mt-1 text-xs text-text-secondary">
          Frozen at approval. Bundle hash <Hash value={graph.artifact.artifact_hash} />
        </p>
        <div className="mt-3 space-y-1.5">
          {isLoading && <p className="text-xs text-text-muted">Running the verifier…</p>}
          {data?.assembled === false && (
            <p className="text-xs text-text-muted">
              Not verified: {data.reason}. This is not a failure — the verifier did not run.
            </p>
          )}
          {data?.checks.map((c) => (
            <div key={c.name} className="flex items-start gap-2 text-xs">
              <span className={c.passed ? "text-status-success" : "text-status-danger"}>
                {c.passed ? "✓" : "✕"}
              </span>
              <span className="text-text-primary">{CHECK_COPY[c.name] ?? c.name}</span>
              {!c.passed && c.detail && (
                <span className="text-status-danger">— {c.detail.split("\n")[0]}</span>
              )}
            </div>
          ))}
        </div>
        {data?.passed === true && (
          <p className="mt-3 text-xs text-text-secondary">
            Every check was run by the same standalone verifier that ships with the bundle. You
            can re-run it yourself on the downloaded file.
          </p>
        )}
      </div>

      <div className="card p-4">
        <h3 className="text-sm font-semibold text-text-primary">Download</h3>
        <div className="mt-2 flex flex-wrap gap-2">
          <a className="btn-secondary" href={`${base}/v2/runs/${graph.run.id}/export.md`}>
            Markdown
          </a>
          <a className="btn-secondary" href={`${base}/v2/runs/${graph.run.id}/export.pdf`}>
            PDF
          </a>
          <a className="btn-primary" href={`${base}/v2/runs/${graph.run.id}/bundle.json`}>
            Verification bundle
          </a>
        </div>
        <p className="mt-2 text-xs text-text-secondary">
          The bundle is the canonical export: it carries the report, every claim, every evidence
          snippet with its hash, the sources, the conflicts and the approval chain, and it
          verifies offline with no network and no AI.
        </p>
      </div>
    </div>
  );
}

/* ── Cancel ─────────────────────────────────────────────────────────────────── */

export function CancelButton({ runId }: { runId: string }) {
  const cancel = useV2Cancel(runId);
  return (
    <div className="text-right">
      <button className="btn-secondary" disabled={cancel.isPending} onClick={() => cancel.mutate()}>
        Stop run
      </button>
      <p className="mt-1 max-w-xs text-[0.6875rem] text-text-muted">
        {cancel.data?.detail ??
          "Records a stop request. Work already in flight finishes its current step — this does not kill the run mid-sentence."}
      </p>
    </div>
  );
}
