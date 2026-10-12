/**
 * What the SQL editor's chrome says, decided apart from how it is drawn (`aughor-v2/CLARITY.md`): the result's
 * figures line, an error said as a failure or a refusal, the guards' verdict as a chip, the Tools ▾ menus that hold
 * every action that left the toolbar, and the starting point an empty result pane shows — recent runs folded by
 * statement, the largest tables.
 *
 * Pure: nothing here fetches, renders or decides what a control does — each tool's `onSelect` is the caller's own.
 */
import { outcomeOf } from "@/lib/auditFold";
import { compactNumber, countNoun, formatCount, formatSeconds } from "@/lib/format";
import type { AuditRecord, QueryValidation, TypedQueryResult } from "@/lib/api";

// ── The figures line ───────────────────────────────────────────────────────────────────────────────────────────────

/** DE-5d — what cut the result, in the reader's words. The server says WHICH of the three cuts it was (`cut_by`); a
 *  result from an older server that only says `truncated` keeps the old line. */
export function cutNote(result: Pick<TypedQueryResult, "row_count" | "cut_by">): string {
  const n = formatCount(result.row_count);
  switch (result.cut_by) {
    case "limit": return `cut at ${n} rows — more exist beyond this limit`;
    case "budget": return `cut at ${n} rows by this connection's row budget — more exist`;
    case "cap": return `cut at ${n} rows — this connector returns at most that many a call, whatever the limit`;
    default: return "truncated — more rows exist beyond this limit";
  }
}

/** How long a run took: "4 ms" under a second (an engine's own speed), "1.2 s" after. */
export function runTime(ms: number): string {
  if (!Number.isFinite(ms) || ms < 0) return "—";
  return ms < 1000 ? `${Math.round(ms)} ms` : formatSeconds(ms);
}

export interface FiguresLine {
  /** "3 rows", "1 row", "No rows" — or "2 of 5 rows" when filters narrow what is on screen. */
  rows: string;
  /** The run's own time; null for a cached answer, whose 0 ms is not a run. */
  time: string | null;
  /** The cut, said plainly, when the server proved more rows exist; null when the result is whole. */
  cut: string | null;
  cached: boolean;
}

/** The result's header: rows · time · the cut · cached. `shown` is how many rows the filters leave on screen. */
export function resultFigures(
  r: Pick<TypedQueryResult, "row_count" | "duration_ms" | "truncated" | "cut_by" | "cached">,
  shown?: { shown: number; returned: number },
): FiguresLine {
  const narrowed = shown && shown.shown !== shown.returned;
  const rows = narrowed
    ? `${formatCount(shown.shown)} of ${countNoun(shown.returned, "row")}`
    : r.row_count === 0 ? "No rows" : countNoun(r.row_count, "row");
  return {
    rows,
    time: r.cached ? null : runTime(r.duration_ms),
    cut: r.truncated ? cutNote(r) : null,
    cached: !!r.cached,
  };
}

// ── An error, said once — a failure or a refusal ───────────────────────────────────────────────────────────────────

export type RunErrorKind = "failed" | "refused" | "cancelled";

export interface RunError {
  kind: RunErrorKind;
  /** "Failed" · "Refused" · "Cancelled". */
  title: string;
  /** Why it was refused, as a chip: "blocked by a guard", "turned off for analysis". */
  why: string | null;
  /** Which statement of a Run all: "statement 2 of 3". */
  statement: string | null;
  /** The engine's or the gate's own words, without the platform's bracket tag. */
  message: string;
}

const REFUSALS: Array<{ re: RegExp; why: string; strip: boolean }> = [
  { re: /^\[BLOCKED\]\s*/, why: "blocked by a guard", strip: true },
  { re: /^\[EXCLUDED\]\s*/, why: "turned off for analysis", strip: true },
  { re: /^Blocked by this agent's sensitive-data guardrail/i, why: "sensitive data withheld", strip: false },
  { re: /^Only SELECT\b/i, why: "only SELECT runs here", strip: false },
];

/** A run's error as the reader needs it: did the engine fail, or did the platform refuse to run it — and why. */
export function describeRunError(error: string): RunError {
  const text = (error ?? "").trim();
  const cancelled = /^Cancelled after \d+ of \d+ statements\.?$/i.test(text);
  if (cancelled) return { kind: "cancelled", title: "Cancelled", why: null, statement: null, message: text };
  const each = /^Statement (\d+) of (\d+) failed:\s*([\s\S]*)$/.exec(text);
  const statement = each ? `statement ${each[1]} of ${each[2]}` : null;
  const body = each ? each[3].trim() : text;
  for (const r of REFUSALS) {
    if (r.re.test(body)) {
      return { kind: "refused", title: "Refused", why: r.why, statement,
        message: r.strip ? body.replace(r.re, "") : body };
    }
  }
  return { kind: "failed", title: "Failed", why: null, statement, message: body || "Query failed" };
}

// ── The guards' verdict, as a chip ─────────────────────────────────────────────────────────────────────────────────

export interface VerdictChip { text: string; tone: "up" | "amber"; title: string }

/** "Guards clean" only when every guard ran and passed — a guard that could not run is never counted as clean (GM-4).
 *  This endpoint judges fan-out, value-domain, grain and trust, never syntax. */
export function verdictChip(v: QueryValidation): VerdictChip {
  const title = v.unchecked
    ? (v.note || "The guards cannot read a parameterised query without values.")
    : v.passed
      ? "Fan-out, join and filter value-domain, grain and trust checks all passed"
      : [v.issue_count ? "Findings are shown in the editor gutter" : "",
         ...(v.unchecked_guards ?? []).map(u => `Not checked (${u.guard}): ${u.reason}`),
        ].filter(Boolean).join("\n");
  if (v.unchecked) return { text: "Not checked — fill parameters", tone: "amber", title };
  if (v.passed) return { text: "Guards clean", tone: "up", title };
  if (!v.issue_count && v.unchecked_guards?.length) return { text: "Not all checked", tone: "amber", title };
  return { text: `Checked — ${v.issue_count} ${v.issue_count === 1 ? "note" : "notes"}`, tone: "amber", title };
}

// ── Tools ▾ — every action that left the toolbar ───────────────────────────────────────────────────────────────────

/** One entry of a Tools ▾ menu — the same shape `components/catalog/CatalogTools.tsx`'s `ToolsMenu` takes. */
export interface ToolSpec {
  label: string;
  onSelect: () => void;
  title?: string;
  /** A rule above it. */
  apart?: boolean;
  /** Not offered now (no saved query, nothing in the buffer, an engine with no plan statement). */
  hidden?: boolean;
  danger?: boolean;
  testId?: string;
}

/** The editor's own tools: what used to be a row of buttons beside Run. */
export function editorTools(s: {
  connected: boolean;
  /** The engine's plan statement ("EXPLAIN"), or null where the engine has none (BigQuery). */
  explainWith: string | null;
  statementCount: number;
  /** The tab already runs every statement on Run, so a separate "Run all" would be the same verb twice. */
  runAllPref: boolean;
  hasSql: boolean;
  historyOpen: boolean;
  act: {
    explain: () => void; runAll: () => void; format: () => void; formatPrefs: () => void;
    openExisting: () => void; toggleHistory: () => void; shortcuts: () => void;
  };
}): ToolSpec[] {
  return [
    { label: "Explain plan", onSelect: s.act.explain, testId: "sql-explain",
      title: `The engine's own ${s.explainWith ?? "plan"} for exactly what Run would execute`,
      hidden: !s.explainWith || !s.connected },
    { label: `Run all ${s.statementCount} statements`, onSelect: s.act.runAll, testId: "sql-run-all",
      title: "In order, stopping at the first error",
      hidden: !s.connected || s.statementCount < 2 || s.runAllPref },
    { label: "Format SQL", onSelect: s.act.format, testId: "sql-format",
      title: "The selection, or the whole query (⌘⇧F)", hidden: !s.hasSql },
    { label: "Formatting preferences…", onSelect: s.act.formatPrefs, testId: "sql-format-prefs",
      title: "Keyword and function case, indent" },
    { label: "Open a saved or recent query…", onSelect: s.act.openExisting, testId: "sql-open-existing", apart: true,
      title: "Opens a copy in a new tab" },
    { label: s.historyOpen ? "Hide recent runs" : "Recent runs", onSelect: s.act.toggleHistory,
      testId: "sql-history-toggle", title: "Queries run from this editor, on this connection" },
    { label: "Keyboard shortcuts", onSelect: s.act.shortcuts, testId: "sql-shortcuts",
      title: "Every key this editor binds — or Esc then H, outside the editor" },
  ];
}

/** The tools both modes share — they belong to the saved query and the workbench, not to an editor. */
export function sharedTools(s: {
  saved: boolean;
  versionsOpen: boolean;
  catalogOpen: boolean;
  act: { versions: () => void; share: () => void; catalog: () => void };
}): ToolSpec[] {
  return [
    { label: s.versionsOpen ? "Hide version history" : "Version history", onSelect: s.act.versions,
      testId: "workbench-versions", apart: true, hidden: !s.saved, title: "Every saved change to this query" },
    { label: "Copy share link", onSelect: s.act.share, testId: "workbench-share",
      title: s.saved ? "A link that reopens this saved query" : "Save this query first — a share link points at a saved query" },
    { label: s.catalogOpen ? "Hide catalog" : "Show catalog", onSelect: s.act.catalog, testId: "workbench-catalog" },
  ];
}

/** A result's tools: the ways out that used to sit in the footer, beside the Copy and CSV kept on the line. */
export function resultTools(s: {
  hasRows: boolean;
  connected: boolean;
  /** Filters narrow the rows on screen; an export takes what is on screen. */
  filtered: boolean;
  /** Schedules already on this statement, once known. */
  scheduleCount: number;
  act: { addChart: () => void; export: () => void; pin: () => void; schedule: () => void };
}): ToolSpec[] {
  return [
    { label: "Add a chart", onSelect: s.act.addChart, testId: "results-add-viz", hidden: !s.hasRows,
      title: "A chart of these rows, in a tab beside the table" },
    { label: s.filtered ? "Other formats, filtered rows…" : "Other formats…", onSelect: s.act.export,
      testId: "results-export", hidden: !s.hasRows,
      title: "Copy or download as TSV, JSON, Markdown, HTML, SQL INSERTs, CSV for Excel or a plain table" },
    { label: "Pin to the dashboard", onSelect: s.act.pin, testId: "results-pin", apart: true,
      hidden: !s.hasRows || !s.connected, title: "This query, as a card on the dashboard" },
    { label: s.scheduleCount > 0 ? `Schedule (${s.scheduleCount})…` : "Schedule…", onSelect: s.act.schedule,
      testId: "results-schedule", hidden: !s.connected, title: "Run this query on a cadence" },
  ];
}

// ── The starting point: recent runs, the largest tables ────────────────────────────────────────────────────────────

/** The statement a person ran, without the wrapper the run put around it (`SELECT * FROM (…) __q LIMIT n` — the
 *  platform's row cap, not their SQL). Unwrapped once and only on that exact shape; anything else is left as written. */
export function unwrapRunSql(sql: string): string {
  const m = /^\s*SELECT \* FROM \(([\s\S]*)\) __q LIMIT \d+\s*$/i.exec(sql ?? "");
  return (m ? m[1] : sql ?? "").trim();
}

export interface RecentRun {
  /** The person's own statement, as it will open. */
  sql: string;
  /** One line of it. */
  preview: string;
  /** How many of the runs read were this statement — said once with a count, not listed again. */
  times: number;
  /** The latest of them. */
  last: AuditRecord;
}

const oneLine = (sql: string) => sql.replace(/\s+/g, " ").trim();

/** Recent runs, newest first, one row per statement: repeats fold into a count. */
export function recentRuns(records: AuditRecord[], limit = 5): RecentRun[] {
  const out = new Map<string, RecentRun>();
  for (const r of records) {
    const sql = unwrapRunSql(r.sql_full || r.sql_digest || "");
    if (!sql) continue;
    const key = oneLine(sql);
    const seen = out.get(key);
    if (seen) { seen.times += 1; continue; }
    out.set(key, { sql, preview: key.slice(0, 120), times: 1, last: r });
  }
  return [...out.values()].slice(0, limit);
}

/** A recent run's meta line: "5 rows · 769 ms", without the timestamp the caller adds. */
export function runMeta(r: AuditRecord): string {
  return [r.row_count != null ? countNoun(r.row_count, "row") : "",
    r.duration_ms != null ? runTime(r.duration_ms) : ""].filter(Boolean).join(" · ");
}

/** What a run's audit row says beyond "ran" — blocked, withheld, flagged, failed, in the Security screen's own words
 *  (`lib/auditFold.outcomeOf`); null for an ordinary passed run, so forty "safe" marks are not said forty times. */
export function runMark(r: AuditRecord): { word: string; tone: "red" | "amber" } | null {
  const o = outcomeOf(r);
  if (o === "passed") return null;
  return { word: o, tone: o === "flagged" ? "amber" : "red" };
}

export interface StartTable { name: string; rows: number | null; shown: string }

/** The largest tables first; a table with no row count is unknown, not zero, and sorts last. */
export function startTables(tables: Array<{ name: string; rowCount?: string | number | null }>, limit = 6): StartTable[] {
  const rowsOf = (rc: string | number | null | undefined): number | null => {
    if (rc == null || rc === "") return null;
    const n = typeof rc === "string" ? parseInt(rc.replace(/[^0-9]/g, ""), 10) : rc;
    return Number.isFinite(n) ? n : null;
  };
  return tables
    .map(t => ({ name: t.name, rows: rowsOf(t.rowCount) }))
    .sort((a, b) => (b.rows ?? -1) - (a.rows ?? -1) || a.name.localeCompare(b.name))
    .slice(0, limit)
    .map(t => ({ ...t, shown: t.rows == null ? "not counted" : compactNumber(t.rows) }));
}
