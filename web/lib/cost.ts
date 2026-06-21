import type { RunCost } from "./api";

/** Compact integer: 1234 → "1.2K", 1_500_000 → "1.5M". */
export function fmtCompact(n: number): string {
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1).replace(/\.0$/, "") + "M";
  if (n >= 1_000) return (n / 1_000).toFixed(1).replace(/\.0$/, "") + "K";
  return String(n);
}

/** Milliseconds → human: 2400 → "2.4s", 320 → "320ms". */
export function fmtMs(ms: number): string {
  if (ms >= 1000) return (ms / 1000).toFixed(1).replace(/\.0$/, "") + "s";
  return Math.round(ms) + "ms";
}

/**
 * The honest one-liner for what a run spent: "12.4K tokens · 3 queries · 847 rows · 2.4s".
 * Real compute only — no fabricated $ (docs/MOTHERDUCK_LEARNINGS.md). Returns "" when
 * nothing was measured (older/unmetered answers) so callers can omit it gracefully.
 */
export function costSummary(cost?: RunCost | null): string {
  if (!cost) return "";
  const parts: string[] = [];
  if (cost.total_tokens) parts.push(`${fmtCompact(cost.total_tokens)} tokens`);
  if (cost.query_count) parts.push(`${cost.query_count} ${cost.query_count === 1 ? "query" : "queries"}`);
  if (cost.rows_returned) parts.push(`${fmtCompact(cost.rows_returned)} rows`);
  const ms = (cost.llm_ms || 0) + (cost.query_ms || 0);
  if (ms > 0) parts.push(fmtMs(ms));
  return parts.join(" · ");
}
