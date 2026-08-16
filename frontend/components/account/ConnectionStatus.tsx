import type { ConnectionState, ConnectionVerdict } from "@/lib/types";

/**
 * Three states, distinct shape *and* colour — never colour alone (docs/07 §2, Phase
 * 2a; AGENTS.md, "Agent hue as reinforcement"): ● filled green "Connected · 47
 * models", ◐ half amber "Reachable, key rejected" / "quota exhausted", ○ hollow red
 * "No response". `reason` is always shown verbatim underneath — a light with no
 * explanation is exactly the "collapsing amber into red" trap the plan calls out.
 */

const STATE_LABEL: Record<ConnectionState, string> = {
  ok: "Connected",
  degraded: "Reachable, not confirmed",
  failed: "No response",
};

const STATE_COLOR: Record<ConnectionState, string> = {
  ok: "var(--success)",
  degraded: "var(--warning)",
  failed: "var(--danger)",
};

function StateMarker({ state }: { state: ConnectionState }) {
  const color = STATE_COLOR[state];
  const style: React.CSSProperties =
    state === "ok"
      ? { backgroundColor: color, borderColor: color }
      : state === "degraded"
      ? {
          background: `linear-gradient(135deg, ${color} 50%, transparent 50%)`,
          borderColor: color,
        }
      : { backgroundColor: "transparent", borderColor: color };

  return (
    <span
      aria-hidden
      className="inline-block h-2.5 w-2.5 shrink-0 border"
      style={style}
    />
  );
}

export function ConnectionStatus({
  verdict,
  loading = false,
  onRetest,
  retesting = false,
}: {
  verdict: ConnectionVerdict | null | undefined;
  loading?: boolean;
  onRetest?: () => void;
  retesting?: boolean;
}) {
  if (loading) {
    return (
      <span className="inline-flex items-center gap-1.5 font-mono text-xs text-text-muted">
        <span className="spinner" style={{ width: 10, height: 10 }} /> Checking…
      </span>
    );
  }

  if (!verdict) return null;

  return (
    <div className="space-y-1">
      <div className="flex flex-wrap items-center gap-2">
        <span className="inline-flex items-center gap-1.5 font-mono text-xs font-medium">
          <StateMarker state={verdict.state} />
          {STATE_LABEL[verdict.state]}
          {verdict.state === "ok" && verdict.model_count != null && (
            <span className="text-text-muted">· {verdict.model_count} models</span>
          )}
        </span>
        {onRetest && (
          <button
            type="button"
            onClick={onRetest}
            disabled={retesting}
            className="font-mono text-xs text-accent hover:underline disabled:opacity-50"
          >
            {retesting ? "Testing…" : "Test connection"}
          </button>
        )}
      </div>
      {/* Verbatim, not a paraphrase — "server refused the key" and "server errored"
          need different fixes, and only the reason string says which (docs/07 §2). */}
      <p className="text-xs leading-relaxed text-text-muted">{verdict.reason}</p>
    </div>
  );
}
