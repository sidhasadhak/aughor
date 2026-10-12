/**
 * What an open Data Canvas says, decided here and laid out by `components/CanvasWorkspace.tsx`, to
 * `aughor-v2/CLARITY.md`: the facts a canvas wears as chips, and its history with a question asked eleven times said
 * once. (The list of canvases, `CanvasBrowser.tsx`, is kept as it was — the user, 2026-10-12.) Pure: nothing here
 * fetches.
 */
import type { Canvas, CanvasHistoryItem, Connection } from "@/lib/api";
import { countNoun, formatCount, MONTHS_SHORT } from "@/lib/format";

const DAY = 86_400_000;

/** Whole days from an instant to `now`; null for a missing or unreadable one. */
export function daysSince(iso: string | null | undefined, now: number): number | null {
  if (!iso) return null;
  const t = Date.parse(iso);
  return Number.isNaN(t) ? null : Math.max(0, Math.floor((now - t) / DAY));
}

/** An instant as a person says it: "today", "yesterday", "9 days ago", "3 months ago", "1 year ago". */
export function agoWords(iso: string | null | undefined, now: number): string {
  const d = daysSince(iso, now);
  if (d == null) return "—";
  if (d === 0) return "today";
  if (d === 1) return "yesterday";
  if (d < 60) return `${d} days ago`;
  if (d < 365) return `${Math.floor(d / 30)} months ago`;
  const y = Math.floor(d / 365);
  return `${y} year${y === 1 ? "" : "s"} ago`;
}

/** A day and its month in the reader's own zone: "3 Oct". */
export function dayMonth(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? String(iso) : `${d.getDate()} ${MONTHS_SHORT[d.getMonth()]}`;
}

export const connectionIdOf = (c: Canvas): string => c.scopes[0]?.connection_id ?? "";
export const tablesOf = (c: Canvas): string[] => c.scopes[0]?.tables ?? [];

/** What a canvas reads: "All tables" (its whole connection) or "24 tables". */
export function scopeWords(c: Canvas): string {
  const n = tablesOf(c).length;
  return n === 0 ? "All tables" : countNoun(n, "table");
}

/** The tables a canvas reads, for a hover: the first twelve by name and how many more. */
export function tablesTitle(c: Canvas): string {
  const t = tablesOf(c);
  if (!t.length) return "Every table of its connection";
  const shown = t.slice(0, 12).join(", ");
  return t.length > 12 ? `${shown} and ${formatCount(t.length - 12)} more` : shown;
}

/** A connection's kind as a person names it. */
export function connectionKind(conn: Connection | undefined): string {
  if (!conn) return "";
  const t = conn.conn_type;
  return t === "duckdb" ? "DuckDB" : t === "postgres" ? "PostgreSQL" : t === "bigquery" ? "BigQuery" : t;
}

/**
 * Whether a canvas's connection is gone from the connections this screen was handed. Unknown — never "gone" — while
 * that list is empty: an empty list is one not read yet, and saying every canvas lost its connection would be false.
 */
export function connectionGone(c: Canvas, connections: readonly Connection[]): boolean {
  if (!connections.length) return false;
  const id = connectionIdOf(c);
  return !id || !connections.some(x => x.id === id);
}

// ── An open canvas's history, a question said once ────────────────────────────────────────────────────────────────

export type RunKind = "chat" | "deep";

export interface AskedQuestion {
  /** The newest run's id — an identity, never the question's words — for a React key. */
  key: string;
  /** The kind and the words: what stays the same when a run of it is removed. */
  group: string;
  kind: RunKind;
  question: string;
  /** Newest first. */
  runs: CanvasHistoryItem[];
  latest: CanvasHistoryItem;
}

export const runKind = (item: CanvasHistoryItem): RunKind => (item.kind === "chat" ? "chat" : "deep");
export const RUN_KIND_WORD: Record<RunKind, string> = { chat: "Chat", deep: "Deep analysis" };

/** One row per question and kind, newest first: the same question asked eleven times is one row with its count. */
export function foldHistory(items: readonly CanvasHistoryItem[]): AskedQuestion[] {
  const at = (i: CanvasHistoryItem) => Date.parse(i.started_at) || 0;
  const byQuestion = new Map<string, CanvasHistoryItem[]>();
  for (const item of [...items].sort((a, b) => at(b) - at(a))) {
    const k = `${runKind(item)}\u0000${item.question.trim()}`;
    byQuestion.set(k, [...(byQuestion.get(k) ?? []), item]);
  }
  return [...byQuestion.values()].map(runs => ({
    key: runs[0].id, group: `${runKind(runs[0])}\u0000${runs[0].question.trim()}`, kind: runKind(runs[0]),
    question: runs[0].question.trim(), runs, latest: runs[0],
  }));
}

/** A run's state when it is not simply finished — said, never coloured alone. */
export function runStateWord(status: string): { word: string; tone: "amber" | "down" } | null {
  if (status === "complete" || status === "completed" || !status) return null;
  if (status === "failed") return { word: "failed", tone: "down" };
  if (status === "timed_out") return { word: "timed out", tone: "down" };
  if (status === "running") return { word: "running", tone: "amber" };
  return { word: status.replace(/_/g, " "), tone: "amber" };
}
