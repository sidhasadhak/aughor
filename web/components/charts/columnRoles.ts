/**
 * columnRoles.ts — the SINGLE source of truth for chart column-role classification.
 *
 * Every chart surface classifies columns as date / share / change-metric / ordinal /
 * instrumentation and infers the x / measure / group roles. That logic used to be
 * duplicated three ways (here, `chartTypeInference.ts`, and inline in `Chart.tsx`),
 * which is exactly the drift the platform keeps re-fixing. It now lives here once:
 * both the type-inference (`chartTypeInference.inferChartType`) and the renderer
 * (`Chart.tsx`) import these regexes + `classifyColumns` so they can never disagree.
 */

/** Timestamp-ish column NAMES (ends with _date/_at/_time/created_at/…/timestamp). */
export const DATE_COL = /(_date|_at|_time|created_at|updated_at|timestamp)$/i;

/** Date column NAME — the suffix form OR a bare temporal name (month/week/period/…). The
 *  superset used by the shared classifier; a value-prefix match (`DATE_VALUE_RE`) also counts. */
export const DATE_NAME = /(_date|_at|_time|created_at|updated_at|timestamp|^date$|^month$|^week$|^period$|^quarter$|^day$|^year$)/i;

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

/** Pure identifier columns — excluded from measure selection. */
export const SKIP_ID = /(_id$|^id$)/i;

/** Identifier detection covering BOTH snake_case (_id, case-insensitive) and camelCase
 *  (franchiseID, supplierId, eventGUID — case-SENSITIVE suffix after a lowercase letter,
 *  so plain words like "valid"/"grid" never match). SKIP_ID alone missed camelCase, which
 *  let `franchiseID` be charted as a measure (bars of summed IDs). Mirrors the backend
 *  profiler's _KEY_PATTERN + _KEY_PATTERN_CAMEL. */
const _CAMEL_ID = /[a-z](ID|Id|Key|Code|Num|Number|Identifier|UUID|Uuid|GUID|Guid|PK|Pk)$/;
const _SNAKE_ID = /(_id|_key|_code|_pk|_uuid|_guid|_sk|_hash)$|^id$/i;
export function isIdLike(name: string): boolean {
  return _SNAKE_ID.test(name) || _CAMEL_ID.test(name);
}

/** Audit-only instrumentation: the numerator/denominator a ratio is built from, or a bare row-count
 *  `n`. These exist so a ratio is checkable, never as a measure to plot — charting them buries the
 *  real metric (an AOV finding rendered as a giant SUM bar). Excluded from chart measure selection. */
export const INSTRUMENTATION_COL = /(^|_)(numerator|denominator)(_total)?$|^n$|^event_count$/i;

/** A measure whose name PREFERS to be the plotted one (a share/rate over a raw magnitude). */
export const PREFER_COL = /(pct|percent|share|rate|ratio|proportion)/i;

/** An ADDITIVE magnitude (summable) — the only kind you compose in a pie/treemap. */
export const ADDITIVE_COL = /(revenue|sales|amount|count|spend|cost|total|value|gmv|qty|quantity|orders|units|profit|volume)/i;

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

/** Count the distinct values a column takes across all rows. */
export function countUnique(rows: unknown[][], colIdx: number): number {
  return new Set(rows.map((r) => String((r as unknown[])[colIdx]))).size;
}

/** Is a column entirely null/empty across all rows? (carries no information → never plot it). */
export function isDeadColumn(rows: unknown[][], colIdx: number): boolean {
  return rows.every((r) => {
    const v = (r as unknown[])[colIdx];
    return v === null || v === undefined || v === "" || v === "NULL";
  });
}

/** THE classifier — split columns into date / numeric / category index buckets. One implementation,
 *  used by both `inferChartType` (type selection) and `Chart.tsx` (rendering), so the two can't drift.
 *  A date is a date-NAME or a date-VALUE prefix; a numeric is a non-date, non-id numeric value; every
 *  other non-dead column is a category. */
export function classifyColumns(
  columns: string[],
  rows: unknown[][],
): { dateIdxs: number[]; numericIdxs: number[]; catIdxs: number[] } {
  if (!rows.length) return { dateIdxs: [], numericIdxs: [], catIdxs: [] };
  const dateIdxs: number[] = [];
  const numericIdxs: number[] = [];
  const catIdxs: number[] = [];
  columns.forEach((col, i) => {
    if (isDeadColumn(rows, i)) return;
    const firstVal = firstNonNull(rows, i);
    const isDate = DATE_NAME.test(col) || (typeof firstVal === "string" && DATE_VALUE_RE.test(firstVal));
    const numeric = !isDate && !isIdLike(col) && isNumeric(firstVal);
    if (isDate) dateIdxs.push(i);
    else if (numeric) numericIdxs.push(i);
    else catIdxs.push(i);
  });
  return { dateIdxs, numericIdxs, catIdxs };
}
