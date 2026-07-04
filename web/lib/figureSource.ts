/**
 * figureSource.ts — derive a chart/table's provenance footer from its query result
 * (REC-U7). "Source: orders, order_items · 12,345 rows · Jan–Dec 2024".
 *
 * All best-effort and defensive: a chart with no parseable source just renders no
 * footer. Table extraction is a lightweight FROM/JOIN scan (not a full parser — the
 * backend gate already validated the SQL); the date range reuses the format.ts
 * granularity detection so the label matches the axis.
 */
import type { FigureSource } from "@/components/brief/Brief";
import { detectGranularity, fmtDate, normDateStr } from "@/lib/format";
import { DATE_VALUE_RE } from "@/components/charts/columnRoles";

const FROM_JOIN_RE = /\b(?:from|join)\s+([a-zA-Z_][\w.]*)/gi;

/** Input tables referenced by a SQL string, in first-seen order (deduped, capped). */
export function tablesInSql(sql: string | null | undefined): string[] {
  if (!sql) return [];
  const seen: string[] = [];
  for (const m of sql.matchAll(FROM_JOIN_RE)) {
    const t = m[1];
    // skip subquery aliases / CTE refs that aren't real tables (no dot, single word
    // that reappears as an alias) — keep it simple: keep dotted names + bare identifiers.
    if (t && !seen.includes(t)) seen.push(t);
  }
  return seen.slice(0, 6);
}

/** The min–max label of the first date-like column, e.g. "Jan 2024 – Dec 2024". */
function dateRange(columns: string[], rows: unknown[][]): string | undefined {
  if (!rows.length) return undefined;
  const idx = columns.findIndex((c, i) => {
    const v = rows.find((r) => r[i] != null)?.[i];
    return typeof v === "string" && DATE_VALUE_RE.test(v);
  });
  if (idx < 0) return undefined;
  const vals = rows.map((r) => r[idx]).filter((v): v is string => typeof v === "string" && DATE_VALUE_RE.test(v));
  if (!vals.length) return undefined;
  const sorted = [...vals].sort((a, b) => normDateStr(a).localeCompare(normDateStr(b)));
  const gran = detectGranularity(columns[idx], vals);
  const lo = fmtDate(sorted[0], gran);
  const hi = fmtDate(sorted[sorted.length - 1], gran);
  return lo === hi ? lo : `${lo} – ${hi}`;
}

/** Build the figure source footer from a result set + its SQL. Returns undefined when
 *  there's nothing worth showing (so the caller can omit the footer entirely). */
export function deriveFigureSource(
  sql: string | null | undefined,
  columns: string[],
  rows: unknown[][],
  rowCount?: number,
): FigureSource | undefined {
  const tables = tablesInSql(sql);
  const n = typeof rowCount === "number" ? rowCount : rows.length;
  const range = dateRange(columns, rows);
  if (!tables.length && !range && !n) return undefined;
  return { tables: tables.length ? tables : undefined, rowCount: n || undefined, dateRange: range };
}
