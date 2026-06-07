/**
 * columnRoles.ts — shared column-role classification for chart building.
 *
 * The chart engine (Chart.tsx, extracted from ChatMessage) and ChatMessage's
 * own result-summary code both classify columns as date / share / change-metric /
 * ordinal / time-label. These regexes + helpers lived inline in ChatMessage; they
 * now have one home so the chart component can live independently of ChatMessage.
 *
 * (chartTypeInference.ts carries a parallel set for InvestigationChart; those will
 * converge here when the two chart engines are fully merged.)
 */

/** Timestamp-ish column NAMES (ends with _date/_at/_time/created_at/…/timestamp). */
export const DATE_COL = /(_date|_at|_time|created_at|updated_at|timestamp)$/i;

/** Share / ratio column names → render as percentages. */
export const SHARE_COL = /(share|pct|percent|rate|ratio|proportion)/i;

// Change / delta / period-over-period metric column names.
// When ANY numeric column matches this pattern the question is a COMPARISON question
// (MoM, YoY, delta, growth rate) — heatmap and stacked-bar are the wrong charts.
// Also catches lag/prev/prior columns — their presence signals a POP query even when
// no explicit delta column was computed.
export const CHANGE_METRIC_COL = /(change|delta|growth|mom|yoy|wow|qoq|pct_change|percent_change|_chg$|_diff$|vs_prev|^prev_|_prev$|^prior_|_prior$|^lag_|_lag$)/i;

/** Ordinal / identifier columns — never abbreviate or treat as a measure. */
export const ORDINAL_COL = /(year|month|day|week|rank|_id$|^id$)/i;

// Columns whose values are already human-formatted time labels (Month - Year, Q1 2024, etc.)
// → preserve SQL ordering, don't parse as dates, don't re-sort.
export const TIME_LABEL_COL = /(month|quarter|week|half|period)/i;

/** ISO date VALUE prefix ("2024-01" / "2024-01-01…"). */
export const DATE_VALUE_RE = /^\d{4}-\d{2}(-\d{2})?/;

export function isNumeric(v: unknown): boolean {
  return v !== null && v !== "" && !isNaN(Number(v));
}

/** Scan the full row set for the first non-null value of column colIdx.
 *  Falls back to rows[0]?.[colIdx] (which may be null) if all rows are null.
 *  Prevents NULL-heavy leading rows (e.g. first month of MoM lag queries) from
 *  mis-classifying numeric columns as categorical. A 20-row cap breaks LAG/LEAD
 *  queries where the first N rows (one per category for the first period) are all
 *  NULL — so we scan everything. */
export function firstNonNull(rows: unknown[][], colIdx: number): unknown {
  for (let i = 0; i < rows.length; i++) {
    const v = (rows[i] as unknown[])[colIdx];
    if (v !== null && v !== undefined && v !== "") return v;
  }
  return rows[0]?.[colIdx as number];
}
