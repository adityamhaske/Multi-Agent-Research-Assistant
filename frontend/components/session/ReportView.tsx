"use client";

import toast from "react-hot-toast";

import { Report, SourcesPanel } from "@/lib/citations";
import { formatCost, formatDuration, formatNumber } from "@/lib/format";
import type { SessionDetail } from "@/lib/types";

import { ChatPanel } from "./ChatPanel";

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-[0.7rem] uppercase tracking-wide text-text-muted">{label}</div>
      <div className="font-mono text-sm text-text-primary tabular-nums">{value}</div>
    </div>
  );
}

export function ReportView({ session }: { session: SessionDetail }) {
  const report = session.final_report ?? session.draft_report ?? "";
  const sources = session.sources ?? [];
  const tokens = session.total_tokens_input + session.total_tokens_output;

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(report);
      toast.success("Report copied to clipboard.");
    } catch {
      toast.error("Couldn't access the clipboard.");
    }
  };

  // Generated client-side — no server export endpoint needed (docs/07 §3 export buttons).
  const downloadMarkdown = () => {
    const blob = new Blob([report], { type: "text/markdown;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `research-${session.session_id.slice(0, 8)}.md`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="space-y-6">
      <section aria-labelledby="report-heading" className="card">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <h1 id="report-heading" className="text-lg font-semibold text-text-primary">
            Report
          </h1>
          <div className="flex gap-2 print:hidden">
            <button type="button" onClick={copy} className="btn btn-secondary px-3 py-1.5 text-sm">
              Copy
            </button>
            <button
              type="button"
              onClick={downloadMarkdown}
              className="btn btn-secondary px-3 py-1.5 text-sm"
            >
              .md
            </button>
            <button
              type="button"
              onClick={() => window.print()}
              className="btn btn-secondary px-3 py-1.5 text-sm"
            >
              Save as PDF
            </button>
          </div>
        </div>

        <div className="mb-6 flex flex-wrap gap-x-8 gap-y-3 border-y border-border py-3">
          <Metric label="Duration" value={formatDuration(session.elapsed_seconds)} />
          <Metric label="Cost" value={formatCost(session.total_cost_usd)} />
          <Metric label="Tokens" value={formatNumber(tokens)} />
          <Metric label="Sources" value={String(sources.length)} />
        </div>

        {report ? (
          <Report markdown={report} sources={sources} />
        ) : (
          <p className="text-sm text-text-muted">This report has no body.</p>
        )}
        <SourcesPanel sources={sources} />
      </section>

      <div className="print:hidden">
        <ChatPanel sessionId={session.session_id} sources={sources} />
      </div>
    </div>
  );
}
