/**
 * M23d — Chart type inference.
 *
 * Pure function that decides the best chart type from column metadata + row data.
 * All chart components should call this instead of reimplementing their own detection.
 */

export type ChartType = "line" | "bar" | "grouped-bar" | "scatter" | "table";

export interface InferredChart {
  type: ChartType;
  xCol: number;   // index of the x-axis / category column
  yCols: number[]; // indexes of numeric columns to plot
}

// ── Column classifier patterns ─────────────────────────────────────────────────

const DATE_NAME = /(_date|_at|_time|created_at|updated_at|timestamp|^date$|^month$|^week$|^period$|^quarter$|^day$|^year$)/i;
const DATE_VAL  = /^\d{4}-\d{2}/;
const SKIP_ID   = /(_id$|^id$)/i;
const SHARE_COL = /(share|pct|percent|rate|ratio|proportion)/i;

function isNumericValue(v: unknown): boolean {
  return v !== null && v !== "" && !isNaN(Number(v));
}

function sampleRows(rows: unknown[][], n = 10): unknown[][] {
  return rows.slice(0, n);
}

/**
 * Classify each column index as "date", "numeric", or "category".
 * Returns three sorted arrays of column indexes.
 */
export function classifyColumns(
  columns: string[],
  rows: unknown[][],
): { dateIdxs: number[]; numericIdxs: number[]; catIdxs: number[] } {
  const sample = sampleRows(rows);
  if (!sample.length) return { dateIdxs: [], numericIdxs: [], catIdxs: [] };

  const dateIdxs: number[]    = [];
  const numericIdxs: number[] = [];
  const catIdxs: number[]     = [];

  columns.forEach((col, i) => {
    const colVals = sample.map(r => (r as unknown[])[i]);
    const firstVal = colVals[0];

    const isDate =
      DATE_NAME.test(col) ||
      (typeof firstVal === "string" && DATE_VAL.test(firstVal));

    const isNumeric =
      !isDate &&
      !SKIP_ID.test(col) &&
      colVals.every(v => isNumericValue(v));

    if (isDate)        dateIdxs.push(i);
    else if (isNumeric) numericIdxs.push(i);
    else               catIdxs.push(i);
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

  // Time series: date col + ≥1 numeric → line
  if (dateIdxs.length > 0 && numericIdxs.length > 0) {
    return { type: "line", xCol: dateIdxs[0], yCols: numericIdxs };
  }

  // Two numeric cols + enough rows → scatter (outlier detection)
  if (numericIdxs.length === 2 && catIdxs.length === 0 && rows.length >= 10) {
    return { type: "scatter", xCol: numericIdxs[0], yCols: [numericIdxs[1]] };
  }

  // Category + exactly 1 numeric → bar
  if (catIdxs.length > 0 && numericIdxs.length === 1) {
    return { type: "bar", xCol: catIdxs[0], yCols: numericIdxs };
  }

  // Category + multiple numerics → grouped-bar
  if (catIdxs.length > 0 && numericIdxs.length >= 2) {
    return { type: "grouped-bar", xCol: catIdxs[0], yCols: numericIdxs };
  }

  return null;
}

/** True when the column name looks like a 0-1 share / rate / percentage. */
export function isShareColumn(colName: string, rows: unknown[][], colIdx: number): boolean {
  if (!SHARE_COL.test(colName)) return false;
  return rows.slice(0, 20).every(r => {
    const n = Number((r as unknown[])[colIdx]);
    return !isNaN(n) && n >= 0 && n <= 1;
  });
}
