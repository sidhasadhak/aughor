/**
 * What the Data Canvas screens say, decided here and laid out by `components/CanvasBrowser.tsx` (the list) and
 * `components/CanvasWorkspace.tsx` (an open canvas), to `aughor-v2/CLARITY.md`: the list's figures, what needs a
 * person, the facts each canvas wears as chips, its sort and filter, and an open canvas's history with a question
 * asked eleven times said once. Pure: nothing here fetches.
 */
import type { Canvas, CanvasHistoryItem, Connection } from "@/lib/api";
import { countNoun, formatCount, MONTHS_SHORT } from "@/lib/format";

const DAY = 86_400_000;

/** How long a canvas may go unasked before the list counts it as not used. */
export const IDLE_DAYS = 30;

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

// ── The list's figures and what needs a person ────────────────────────────────────────────────────────────────────

export interface CanvasFigures {
  total: number;
  /** Connections the canvases read, each once. */
  connections: number;
  /** Made automatically from a connection, not by a person. */
  auto: number;
  /** The canvas asked something most recently, and when. */
  lastUsed: { canvas: Canvas; at: string } | null;
  /** Not asked anything in `IDLE_DAYS` — the never-used among them. */
  idle: number;
  never: number;
}

export function canvasFigures(canvases: readonly Canvas[], now: number): CanvasFigures {
  let lastUsed: CanvasFigures["lastUsed"] = null;
  let idle = 0;
  let never = 0;
  for (const c of canvases) {
    const d = daysSince(c.last_activity, now);
    if (d == null) { never += 1; idle += 1; continue; }
    if (d >= IDLE_DAYS) idle += 1;
    if (!lastUsed || Date.parse(c.last_activity!) > Date.parse(lastUsed.at)) lastUsed = { canvas: c, at: c.last_activity! };
  }
  return {
    total: canvases.length,
    connections: new Set(canvases.map(connectionIdOf).filter(Boolean)).size,
    auto: canvases.filter(c => c.is_legacy).length,
    lastUsed, idle, never,
  };
}

/** The canvases that need a person: each whose connection is gone, so a question there has nothing to read. */
export function canvasNeeds(canvases: readonly Canvas[], connections: readonly Connection[]): Canvas[] {
  return canvases.filter(c => connectionGone(c, connections));
}

// ── Sort and filter ───────────────────────────────────────────────────────────────────────────────────────────────

export type CanvasSort = "activity" | "modified" | "name" | "tables";

/** How the list says its order: "sorted by last used". */
export const SORT_WORDS: Record<CanvasSort, string> = {
  activity: "last used", modified: "last edited", name: "name", tables: "table count",
};

const edited = (c: Canvas) => Date.parse(c.updated_at || c.created_at) || 0;
const used = (c: Canvas) => (c.last_activity ? Date.parse(c.last_activity) || 0 : 0);

export function sortCanvases(canvases: readonly Canvas[], sort: CanvasSort): Canvas[] {
  const cmp: Record<CanvasSort, (a: Canvas, b: Canvas) => number> = {
    activity: (a, b) => used(b) - used(a) || edited(b) - edited(a),
    modified: (a, b) => edited(b) - edited(a),
    name: (a, b) => a.name.localeCompare(b.name),
    tables: (a, b) => tablesOf(b).length - tablesOf(a).length,
  };
  return [...canvases].sort(cmp[sort]);
}

/** The canvases a filter keeps: words found in the name, the description or the connection's name; and, when asked,
 *  none made automatically. */
export function filterCanvases(canvases: readonly Canvas[], opts: {
  query: string; hideAuto: boolean; connectionName: (c: Canvas) => string;
}): Canvas[] {
  const q = opts.query.trim().toLowerCase();
  return canvases.filter(c => {
    if (opts.hideAuto && c.is_legacy) return false;
    if (!q) return true;
    return c.name.toLowerCase().includes(q) || (c.description ?? "").toLowerCase().includes(q)
      || opts.connectionName(c).toLowerCase().includes(q);
  });
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
