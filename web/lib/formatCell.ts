/**
 * Shared column-typed cell formatter.
 *
 * A column is treated as a share column only when BOTH conditions hold:
 *   1. The column name matches SHARE_COL_PATTERN
 *   2. Every non-null numeric value in the column is in [0, 1] (±0.001 tolerance)
 *
 * This prevents per-row heuristics that produce "21.00%" for an 11-row count.
 * Pre-compute `isShareColumn` once per column before rendering any rows.
 */

export const SHARE_COL_PATTERN = /share|pct|percent|rate|ratio|proportion/i;
export const ORDINAL_COL_PATTERN = /year|month|day|week|rank|_id$|^id$/i;

/** Returns true if the column should be rendered as XX.XX% */
export function isShareColumn(colName: string, colValues: unknown[]): boolean {
  if (!SHARE_COL_PATTERN.test(colName)) return false;
  const nums = colValues
    .filter((v) => v !== null && v !== undefined && v !== "NULL" && v !== "")
    .map((v) => parseFloat(String(v)));
  if (nums.length === 0) return false;
  const allInRange = nums.every((n) => !isNaN(n) && n >= -0.001 && n <= 1.001);
  if (!allInRange) {
    // Column name suggests share but values are outside [0,1] — log and skip
    if (typeof console !== "undefined") {
      console.warn(
        `[formatCell] Column "${colName}" matches share pattern but has values outside [0,1]. ` +
          `Rendering as plain numbers.`
      );
    }
    return false;
  }
  return true;
}

/**
 * Format a single cell value given the column name and whether the column
 * was pre-determined to be a share column (via isShareColumn).
 */
export function formatCell(
  col: string,
  val: unknown,
  shareCol: boolean
): string {
  if (val === null || val === undefined || val === "NULL") return "—";
  const s = String(val);
  const n = parseFloat(s.replace(/,/g, ""));

  if (isNaN(n)) return s;

  if (shareCol) return `${(n * 100).toFixed(2)}%`;
  if (ORDINAL_COL_PATTERN.test(col)) return String(Math.round(n));

  // Currency / large numbers
  if (Math.abs(n) >= 1_000_000) return `${(n / 1_000_000).toFixed(2)}M`;
  if (Math.abs(n) >= 1_000 && Number.isInteger(n)) return n.toLocaleString();
  if (!Number.isInteger(n)) return n.toFixed(2);
  return String(n);
}

/**
 * Convenience: pre-compute share flags for all columns in one pass,
 * then return a formatter bound to those flags.
 *
 * Usage:
 *   const fmt = buildColumnFormatter(columns, rows);
 *   // Inside row renderer:
 *   fmt(colIndex, cellValue)
 */
export function buildColumnFormatter(
  columns: string[],
  rows: unknown[][]
): (colIdx: number, val: unknown) => string {
  // Collect column values for share detection
  const colValues: unknown[][] = columns.map(() => []);
  for (const row of rows) {
    for (let i = 0; i < columns.length; i++) {
      colValues[i].push(row[i]);
    }
  }
  const shareFlags = columns.map((col, i) => isShareColumn(col, colValues[i]));
  return (colIdx: number, val: unknown) =>
    formatCell(columns[colIdx] ?? "", val, shareFlags[colIdx] ?? false);
}
