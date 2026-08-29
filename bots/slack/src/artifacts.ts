/**
 * RC-2 — the visual half of an answer, shaped for Slack.
 *
 * Slack has no table widget. A GFM table renders (the SDK's streaming healer
 * even buffers one until its separator row lands), but only while it is narrow
 * enough not to wrap into mush — past roughly six columns a table stops being
 * readable in a thread and starts being a wall. So the rule here is a shape
 * rule, not a size rule: narrow-and-short renders inline, everything else rides
 * as a CSV the reader can open in the tool they were going to open it in
 * anyway, and a preview goes above it so the thread still shows the answer.
 *
 * Whatever is trimmed says so. A table captioned as if it were whole, when it
 * is the first five rows of nine hundred, is the failure this file exists to
 * avoid — the reader cannot see the difference, which is exactly why it matters.
 */

/** Past this many columns a Slack table wraps into an unreadable block. */
export const MAX_INLINE_COLS = 6;
/** Past this many rows a thread turns into a spreadsheet nobody scrolls. */
export const MAX_INLINE_ROWS = 10;
/** How much of an oversized grid to preview above its CSV. */
export const PREVIEW_ROWS = 5;

export interface Grid {
  columns: string[];
  rows: unknown[][];
}

/** One cell, as text. `null` is empty — not the string "null", which reads as data. */
export function cell(v: unknown): string {
  if (v === null || v === undefined) return "";
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

/** A GFM table. Pipes are escaped, or one value silently becomes two columns. */
export function gfmTable({ columns, rows }: Grid): string {
  if (!columns.length) return "";
  const esc = (s: string) => s.replace(/\|/g, "\\|").replace(/\n/g, " ");
  const head = `| ${columns.map((c) => esc(cell(c))).join(" | ")} |`;
  const rule = `| ${columns.map(() => "---").join(" | ")} |`;
  const body = rows.map(
    (r) => `| ${columns.map((_, i) => esc(cell(r[i]))).join(" | ")} |`,
  );
  return [head, rule, ...body].join("\n");
}

/** RFC 4180: quote anything containing a delimiter, a quote, or a newline. */
export function toCsv({ columns, rows }: Grid): string {
  const q = (v: unknown) => {
    const s = cell(v);
    return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  return [columns.map(q).join(","), ...rows.map((r) => columns.map((_, i) => q(r[i])).join(","))]
    .join("\n");
}

/** Narrow AND short: the only grid a thread renders without becoming a wall. */
export function fitsInline({ columns, rows }: Grid): boolean {
  return columns.length > 0 && columns.length <= MAX_INLINE_COLS && rows.length <= MAX_INLINE_ROWS;
}

/**
 * Is this grid worth a second message at all?
 *
 * A quick answer's result is usually one number in one cell, and the prose
 * above it already said that number. Posting "| revenue |\n| €1.2M |" under a
 * sentence that reads "revenue was €1.2M" is pure noise, so a grid earns its
 * exhibit only by having a shape — more than one row, or enough columns to be
 * a breakdown rather than a restatement.
 */
export function worthShowing({ columns, rows }: Grid): boolean {
  if (!columns.length || !rows.length) return false;
  return rows.length > 1 || columns.length > 2;
}

export interface GridRendering {
  /** Markdown to post — the whole table, a preview of it, or nothing. */
  markdown: string;
  /** The full grid as CSV when the markdown does not carry every row. */
  csv: string | null;
}

/**
 * The grid, rendered for a thread. Three outcomes, and the caption always names
 * which one happened:
 *
 * - narrow and short → the whole table, no attachment;
 * - narrow but long → the first rows, plus a CSV holding all of them;
 * - wide → no table at all (it would not read), just the CSV.
 */
export function renderGrid(grid: Grid): GridRendering {
  const { columns, rows } = grid;
  if (!columns.length || !rows.length) return { markdown: "", csv: null };

  if (fitsInline(grid)) return { markdown: gfmTable(grid), csv: null };

  const csv = toCsv(grid);
  if (columns.length > MAX_INLINE_COLS) {
    // No preview: a wide table's first rows are as unreadable as all of them.
    return {
      markdown: `_${rows.length} row${rows.length === 1 ? "" : "s"} × ${columns.length} columns — attached as CSV._`,
      csv,
    };
  }
  const shown = Math.min(PREVIEW_ROWS, rows.length);
  return {
    markdown: [
      gfmTable({ columns, rows: rows.slice(0, shown) }),
      `_Showing ${shown} of ${rows.length} rows — the full result is attached as CSV._`,
    ].join("\n\n"),
    csv,
  };
}

/**
 * The way back to the platform. Slack is the doorway; the interactive chart,
 * the full result, the SQL and the Trust Receipt live in Aughor, and every
 * answer carries the link that reaches them.
 */
export function deepLink(webUrl: string, sessionId: string): string {
  const base = (webUrl || "").replace(/\/+$/, "");
  return `${base}/chat?chat=${encodeURIComponent(sessionId)}`;
}

/** A filename that sorts and survives Slack — no colons, no spaces. */
export function csvFilename(question: string): string {
  const stem = question.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 40);
  return `${stem || "result"}.csv`;
}
