/**
 * Chart type inference — applies principled selection rules.
 *
 * Rule set mirrors the LLM prompt guidance (CHAT_SQL_SYSTEM / CHAT_PROMPT):
 *
 * COMPARISON  (categories, no time)
 *   bar          1 cat + 1 num, ≤15 categories
 *   grouped-bar  1 cat + multiple numerics
 *   scatter      2 numerics, no category (correlation / outlier detection)
 *
 * TREND OVER TIME
 *   line         date + 1 num, NO category column
 *   multi-line   date + category (2–10 unique series) + 1 num
 *   stacked-bar  date + category (≤5 unique series) + 1 num — shows volume composition
 *
 * TWO-DIMENSIONAL DISTRIBUTION
 *   heatmap      date + category (>5 unique values) + 1 num — colour grid
 *
 * COMPOSITION
 *   pie          category + 1 num, ≤6 unique values (parts of whole)
 *
 * Falls back to "table" when data is not chartable.
 */

export type ChartType =
  | "line"
  | "multi-line"
  | "area"
  | "bar"
  | "grouped-bar"
  | "combo"      // bar + line with dual y-axes
  | "stacked-bar"
  | "scatter"
  | "heatmap"
  | "matrix"
  | "pie"
  | "treemap"
  | "table";

export interface InferredChart {
  type: ChartType;
  xCol: number;    // index of the x-axis / category column
  yCols: number[]; // indexes of numeric columns to plot
  colorCol?: number; // index of the series/stack/segment column (multi-line, stacked, heatmap)
}

// ── Column classifier patterns ──────────────────────────────────────────────

const DATE_NAME = /(_date|_at|_time|created_at|updated_at|timestamp|^date$|^month$|^week$|^period$|^quarter$|^day$|^year$)/i;
const DATE_VAL  = /^\d{4}-\d{2}/;
const SKIP_ID   = /(_id$|^id$)/i;
const SHARE_COL = /(share|pct|percent|rate|ratio|proportion)/i;
// Change/delta/period-over-period metric column names.
// When ANY numeric column matches, the question is a COMPARISON question
// (MoM, YoY, WoW, delta, growth rate) — heatmap is the wrong chart type.
// Also catches lag/prev/prior — their presence signals a POP query even when
// no explicit delta column was computed.
const CHANGE_METRIC = /(change|delta|growth|mom|yoy|wow|qoq|pct_change|percent_change|_chg$|_diff$|vs_prev|^prev_|_prev$|^prior_|_prior$|^lag_|_lag$)/i;

function isNumericValue(v: unknown): boolean {
  return v !== null && v !== "" && !isNaN(Number(v));
}

/** Scan up to 20 rows to find the first non-null value for a column.
 *  Avoids misclassifying columns whose early rows happen to be NULL
 *  (e.g. the first month of a MoM lag query). */
function firstNonNull(rows: unknown[][], colIdx: number): unknown {
  for (let i = 0; i < Math.min(rows.length, 20); i++) {
    const v = (rows[i] as unknown[])[colIdx];
    if (v !== null && v !== undefined && v !== "") return v;
  }
  return (rows[0] as unknown[])?.[colIdx];
}

/** Count the number of distinct values a column takes across all rows. */
function countUnique(rows: unknown[][], colIdx: number): number {
  return new Set(rows.map(r => String((r as unknown[])[colIdx]))).size;
}

/**
 * Classify each column index as "date", "numeric", or "category".
 */
export function classifyColumns(
  columns: string[],
  rows: unknown[][],
): { dateIdxs: number[]; numericIdxs: number[]; catIdxs: number[] } {
  if (!rows.length) return { dateIdxs: [], numericIdxs: [], catIdxs: [] };

  const dateIdxs: number[]    = [];
  const numericIdxs: number[] = [];
  const catIdxs: number[]     = [];

  columns.forEach((col, i) => {
    const firstVal = firstNonNull(rows, i);

    const isDate =
      DATE_NAME.test(col) ||
      (typeof firstVal === "string" && DATE_VAL.test(firstVal));

    const isNumeric =
      !isDate &&
      !SKIP_ID.test(col) &&
      isNumericValue(firstVal);

    if (isDate)         dateIdxs.push(i);
    else if (isNumeric) numericIdxs.push(i);
    else                catIdxs.push(i);
  });

  return { dateIdxs, numericIdxs, catIdxs };
}

/**
 * Infer the best chart type for the given columns + rows.
 * Returns null when the data is not chartable (< 2 rows, no numeric cols, etc.)
 */
export function inferChartType(
  columns: string[],
  rows: unknown[][],
): InferredChart | null {
  if (!columns.length || rows.length < 2) return null;

  const { dateIdxs, numericIdxs, catIdxs } = classifyColumns(columns, rows);

  if (!numericIdxs.length) return null;

  const dateIdx = dateIdxs[0];
  const catIdx  = catIdxs[0];
  const numIdx  = numericIdxs[0];

  // ── TIME SERIES (date column present) ────────────────────────────────────
  if (dateIdx !== undefined) {
    // No category → pure single line
    if (catIdx === undefined) {
      return { type: "line", xCol: dateIdx, yCols: numericIdxs };
    }

    // Category present → choose by cardinality AND metric intent
    const uniqueSeriesCount = countUnique(rows, catIdx);

    // Check if ANY numeric column is a change/delta/growth metric.
    // These are COMPARISON questions (MoM, YoY, WoW, delta, growth rate).
    // Heatmap is for DISTRIBUTION exploration — never for change data.
    const hasChangeMetric = numericIdxs.some(i => CHANGE_METRIC.test(columns[i]));

    if (hasChangeMetric) {
      // Change/delta metrics are TREND questions: period on X, delta on Y, one line per series.
      // Always multi-line regardless of series count — user needs to see trajectories, not a bar.
      // Prefer the change/delta column as the primary Y (not the first numeric like revenue).
      const changeNumIdx = numericIdxs.find(i => CHANGE_METRIC.test(columns[i])) ?? numIdx;
      return { type: "multi-line", xCol: dateIdx, yCols: [changeNumIdx], colorCol: catIdx };
    }

    if (uniqueSeriesCount > 5) {
      // High-cardinality ABSOLUTE metric: heatmap is the most readable option
      return { type: "heatmap", xCol: dateIdx, yCols: [numIdx], colorCol: catIdx };
    }

    // Low-cardinality absolute metric: multi-line for trend comparison
    return { type: "multi-line", xCol: dateIdx, yCols: [numIdx], colorCol: catIdx };
  }

  // ── NO TIME AXIS ─────────────────────────────────────────────────────────

  // Two pure numerics, no category → scatter (correlation / outlier detection)
  if (numericIdxs.length === 2 && catIdx === undefined && rows.length >= 10) {
    return { type: "scatter", xCol: numericIdxs[0], yCols: [numericIdxs[1]] };
  }

  // Category present
  if (catIdx !== undefined) {
    const uniqueCatCount = countUnique(rows, catIdx);

    // Very few categories → pie (parts of whole)
    if (uniqueCatCount <= 6 && numericIdxs.length === 1) {
      return { type: "pie", xCol: catIdx, yCols: numericIdxs };
    }

    // Multiple numeric columns → combo chart (bar + line, dual axes)
    if (numericIdxs.length >= 2) {
      return { type: "combo", xCol: catIdx, yCols: numericIdxs };
    }

    // Single numeric, any cardinality → bar
    return { type: "bar", xCol: catIdx, yCols: numericIdxs };
  }

  return null;
}

/** True when the column name looks like a 0–1 share / rate / percentage. */
export function isShareColumn(colName: string, rows: unknown[][], colIdx: number): boolean {
  if (!SHARE_COL.test(colName)) return false;
  return rows.slice(0, 20).every(r => {
    const n = Number((r as unknown[])[colIdx]);
    return !isNaN(n) && n >= 0 && n <= 1;
  });
}
