/** Pure display formatters (unit-tested). */

export function formatCost(usd: number | null | undefined): string {
  const v = usd ?? 0;
  if (v === 0) return "$0.00";
  if (v < 0.01) return `$${v.toFixed(4)}`;
  return `$${v.toFixed(2)}`;
}

export function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return "—";
  if (seconds < 60) return `${seconds.toFixed(1)}s`;
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return `${m}m ${s}s`;
}

export function formatNumber(n: number | null | undefined): string {
  return new Intl.NumberFormat("en-US").format(n ?? 0);
}

export function relativeTime(iso: string, now: number = Date.now()): string {
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return iso;
  const diff = Math.max(0, now - t);
  const s = Math.floor(diff / 1000);
  if (s < 45) return "just now";
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  const d = Math.floor(h / 24);
  if (d < 30) return `${d}d ago`;
  const mo = Math.floor(d / 30);
  if (mo < 12) return `${mo}mo ago`;
  return `${Math.floor(mo / 12)}y ago`;
}
