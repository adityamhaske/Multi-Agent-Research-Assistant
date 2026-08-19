"use client";

import { useState } from "react";
import toast from "react-hot-toast";

import { Disclosure } from "@/components/ui/Disclosure";
import { EmptyState } from "@/components/ui/EmptyState";
import { useV2Verification } from "@/hooks/v2";
import { ApiError } from "@/lib/api";
import { apiBase } from "@/lib/desktop";
import { downloadExport } from "@/lib/download";
import type { V2RunGraph } from "@/lib/types";

import { Hash, runTotals } from "../primitives";

/**
 * The verifiable artifact.
 *
 * Two things this panel is responsible for beyond listing files. First, saying what an
 * artifact *is* — the tab used to offer a `.bundle.json` and leave the reader to work out
 * why they would want one. Second, actually delivering it: the three exports were plain
 * `<a href>` links, which carry the web host's cookie and carry nothing at all on the
 * desktop host, where the sidecar authenticates with a per-launch bearer token. Every
 * download control in this panel was therefore broken in the desktop build — the recurring
 * "two hosts, one contract" failure, in its usual direction.
 *
 * They are still anchors: the href is real, so middle-click, "copy link" and the
 * keyboard/screen-reader semantics of a link to a file all survive. Only the plain click is
 * intercepted, so that a 501 from a deployment without the PDF libraries becomes a message
 * instead of navigating the tab to a JSON error body.
 */

const VERIFY_COMMAND = "python -m research_engine.verify_bundle research-xxxxxxxx.bundle.json";

const CHECK_COPY: Record<string, string> = {
  bundle_integrity: "Bundle integrity",
  report_integrity: "Report integrity",
  evidence_integrity: "Evidence integrity",
  citation_resolution: "Citation resolution",
  claim_evidence_linkage: "Claim / evidence linkage",
  approval_chain: "Approval chain",
  schema_validity: "Schema validity",
};

const CHECK_MEANING: Record<string, string> = {
  bundle_integrity: "The bundle's own hash matches its contents.",
  report_integrity: "The report text hashes to the value that was approved.",
  evidence_integrity: "Every evidence snippet hashes to its recorded content hash.",
  citation_resolution: "Every citation marker in the report resolves to a listed source.",
  claim_evidence_linkage: "Every claim/evidence link points at rows the bundle contains.",
  approval_chain: "An approval record exists, and it is for this exact report.",
  schema_validity: "The bundle matches the published bundle format.",
};

type Format = "md" | "pdf" | "bundle.json";

export function ArtifactPanel({ graph }: { graph: V2RunGraph }) {
  const { data, isLoading, isError } = useV2Verification(graph.run.id, Boolean(graph.artifact));
  const [busy, setBusy] = useState<Format | null>(null);
  const base = apiBase();
  const totals = runTotals(graph);

  if (!graph.artifact) {
    return (
      <EmptyState
        title="No artifact yet"
        description="An artifact exists only once a person has approved a report at the review gate. Approving is what freezes the report, its evidence and the decision into something a third party can check."
      />
    );
  }

  const download = async (format: Format, event: React.MouseEvent) => {
    event.preventDefault();
    if (busy) return;
    setBusy(format);
    try {
      await downloadExport(
        `/v2/runs/${graph.run.id}/${format === "bundle.json" ? "bundle.json" : `export.${format}`}`,
        `research-${graph.run.id.slice(0, 8)}.${format}`,
      );
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "The download failed.");
    } finally {
      setBusy(null);
    }
  };

  const artifact = graph.artifact;

  return (
    <div className="space-y-4">
      <section className="card" aria-labelledby="artifact-heading">
        <h3 id="artifact-heading" className="font-serif text-base font-bold text-text-primary">
          Verified artifact
        </h3>
        <p className="mt-1 text-sm leading-relaxed text-text-secondary">
          A frozen copy of this report together with everything it rests on — every claim,
          every evidence snippet and its hash, every source, every recorded conflict, and the
          approval decision itself. It is hashed end to end, so someone who does not trust
          this app can check it offline, with no network and no model call.
        </p>

        <dl className="mt-3 grid gap-3 text-xs sm:grid-cols-2">
          <div>
            <dt className="text-text-secondary">Bundle hash</dt>
            <dd className="mt-0.5">
              <Hash value={artifact.artifact_hash} label="Bundle hash" />
            </dd>
          </div>
          <div>
            <dt className="text-text-secondary">Frozen at</dt>
            <dd className="mt-0.5 font-mono tabular-nums text-text-primary">
              {new Date(artifact.created_at).toLocaleString()}
            </dd>
          </div>
          <div>
            <dt className="text-text-secondary">Authorized by</dt>
            <dd className="mt-0.5 text-text-primary">
              {artifact.review_decision.toLowerCase()} {artifact.review_gate.toLowerCase()} review
            </dd>
          </div>
          <div>
            <dt className="text-text-secondary">Format version</dt>
            <dd className="mt-0.5 font-mono tabular-nums text-text-primary">
              {artifact.format_version}
            </dd>
          </div>
        </dl>

        {artifact.demo && (
          <p
            className="mt-3 border p-2 text-xs leading-relaxed"
            style={{
              color: "var(--warning)",
              backgroundColor: "var(--warning-soft)",
              borderColor: "var(--warning-line)",
            }}
          >
            This artifact came from a <strong>demo run</strong>: scripted models and fixture
            sources, not real research. The flag is carried inside the bundle and the verifier
            reports it.
          </p>
        )}
      </section>

      <section className="card" aria-labelledby="checks-heading">
        <h3 id="checks-heading" className="text-sm font-semibold text-text-primary">
          What the verifier found
        </h3>
        <p className="mt-1 text-xs leading-relaxed text-text-secondary">
          Run by the same standalone verifier that ships with the bundle — not asserted by
          this page.
        </p>
        <div className="mt-3 space-y-1.5">
          {isLoading && (
            <p className="text-xs text-text-muted">
              <span className="spinner mr-1.5 inline-block align-[-2px]" />
              Running the verifier…
            </p>
          )}
          {isError && (
            <p className="text-xs text-text-muted">
              The verifier result could not be loaded. That is this page failing to ask, not a
              check failing — download the bundle and run the verifier yourself.
            </p>
          )}
          {data?.assembled === false && (
            <p className="text-xs text-text-muted">
              Not verified: {data.reason}. This is not a failure — the verifier did not run.
            </p>
          )}
          {data?.checks.map((c) => (
            <div key={c.name} className="flex flex-wrap items-start gap-2 text-xs">
              <span className={c.passed ? "text-success" : "text-danger"} aria-hidden>
                {c.passed ? "✓" : "✕"}
              </span>
              <span className="text-text-primary" title={CHECK_MEANING[c.name]}>
                {CHECK_COPY[c.name] ?? c.name}
              </span>
              <span className="sr-only">{c.passed ? "passes" : "fails"}</span>
              {!c.passed && c.detail && (
                <span className="min-w-0 break-words text-danger">
                  — {c.detail.split("\n")[0]}
                </span>
              )}
            </div>
          ))}
        </div>
        {data?.passed === true && data.frozen && (
          <p className="mt-3 text-xs leading-relaxed text-text-secondary">
            Every check passed against the frozen bundle. You can re-run exactly these checks
            yourself on the downloaded file.
          </p>
        )}
        {data?.passed === false && (
          <p className="mt-3 text-xs leading-relaxed text-danger">
            At least one check did not pass. The artifact still exists and still downloads —
            what it does not do is verify, and that is reported rather than hidden.
          </p>
        )}
      </section>

      <section className="card" aria-labelledby="download-heading">
        <h3 id="download-heading" className="text-sm font-semibold text-text-primary">
          Download
        </h3>
        <div className="mt-2 flex flex-wrap gap-2">
          <a
            className="btn btn-primary"
            href={`${base}/v2/runs/${graph.run.id}/bundle.json`}
            onClick={(e) => download("bundle.json", e)}
          >
            {busy === "bundle.json" && <span className="spinner" />}
            Verification bundle
          </a>
          <a
            className="btn btn-secondary"
            href={`${base}/v2/runs/${graph.run.id}/export.md`}
            onClick={(e) => download("md", e)}
          >
            {busy === "md" && <span className="spinner" />}
            Markdown
          </a>
          <a
            className="btn btn-secondary"
            href={`${base}/v2/runs/${graph.run.id}/export.pdf`}
            onClick={(e) => download("pdf", e)}
          >
            {busy === "pdf" && <span className="spinner" />}
            PDF
          </a>
        </div>
        <p className="mt-2 text-xs leading-relaxed text-text-secondary">
          The bundle is the canonical export: report, claims, evidence with per-snippet
          hashes, sources, conflicts and the approval chain. Markdown and PDF are the report
          alone — readable, but not checkable.
        </p>

        <div className="mt-3 border-t border-border pt-3">
          <Disclosure label="Verify it yourself" summary="offline, no AI, no account">
            <div className="space-y-3 text-sm leading-relaxed text-text-secondary">
              <p>
                Download the bundle, then check it with the standalone verifier. It re-computes
                every hash, confirms each citation resolves to a source, and confirms an
                approval record matches this exact report text — with no network access and no
                model call.
              </p>
              <pre className="overflow-x-auto border border-border bg-bg-elevated p-3 font-mono text-xs text-text-primary">
                <code>{VERIFY_COMMAND}</code>
              </pre>
              <p className="text-text-muted">
                Exit status is 0 on pass and 1 on fail. Add{" "}
                <code className="font-mono text-xs">--format json</code> for a machine-readable
                report. A bundle produced in demo mode says so above its verdict.
              </p>
            </div>
          </Disclosure>
        </div>
      </section>

      <p className="text-xs leading-relaxed text-text-muted">
        The artifact covers {totals.claims.length} claim
        {totals.claims.length === 1 ? "" : "s"}, {totals.evidence} evidence item
        {totals.evidence === 1 ? "" : "s"} and {totals.sources} source
        {totals.sources === 1 ? "" : "s"}.
      </p>
    </div>
  );
}
