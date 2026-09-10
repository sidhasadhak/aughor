/**
 * SE-6 — what a selection of cells adds up to.
 *
 * DataGrip's data editor answers this the moment you drag across cells, and it is the
 * single most-used thing in that grid: "select the column, read the sum" replaces
 * writing a second query. Ported here as a pure function so the numbers are testable
 * away from the DOM.
 *
 * Two rules the summary follows, both of which a naive implementation gets wrong:
 *
 *  - **NULL is not zero.** It is counted separately and excluded from every statistic.
 *    A column of ten nulls has an average of nothing, not of 0.
 *  - **A number is a number because the COLUMN says so**, not because the text parses.
 *    An order id of `00417` is not the integer 417, and summing a column of them
 *    produces a figure that is wrong in a way nobody can see. Callers pass the declared
 *    types; a selection that spans a non-numeric column reports counts only.
 */

export type Cell = string | number | boolean | null;

export interface CellStats {
  /** Cells in the selection, nulls included. */
  count: number;
  nulls: number;
  distinct: number;
  /** Present only when every selected column is numeric and at least one value is. */
  numeric: null | {
    n: number;
    sum: number;
    avg: number;
    min: number;
    max: number;
  };
}

/** `values` is the selected cells in reading order; `allNumericColumns` says whether
 *  every column the selection touches is declared numeric. */
export function cellStats(values: readonly Cell[], allNumericColumns: boolean): CellStats {
  let nulls = 0;
  const seen = new Set<string>();
  const nums: number[] = [];
  for (const v of values) {
    if (v === null || v === undefined) { nulls += 1; continue; }
    seen.add(typeof v === "string" ? v : String(v));
    if (allNumericColumns) {
      const n = typeof v === "number" ? v : Number(v);
      if (Number.isFinite(n)) nums.push(n);
    }
  }
  let numeric: CellStats["numeric"] = null;
  if (allNumericColumns && nums.length) {
    let sum = 0, min = Infinity, max = -Infinity;
    for (const n of nums) { sum += n; if (n < min) min = n; if (n > max) max = n; }
    numeric = { n: nums.length, sum, avg: sum / nums.length, min, max };
  }
  return { count: values.length, nulls, distinct: seen.size, numeric };
}

/** Compact, honest rendering of a statistic. Integers stay integers; a long decimal is
 *  cut to six significant figures rather than shown to seventeen, which is the float's
 *  precision and not the data's. */
export function statText(n: number): string {
  if (!Number.isFinite(n)) return "—";
  // `maximumFractionDigits` is explicit because the default is THREE: an average of
  // 0.333333 rendered as "0.333", which is a different number quietly presented as
  // this one. The locale is pinned for the same reason `formatCount` pins it.
  const opts = { maximumFractionDigits: 20 } as const;
  if (Number.isInteger(n) && Math.abs(n) < 1e15) return n.toLocaleString("en-US", opts);
  return Number(n.toPrecision(6)).toLocaleString("en-US", opts);
}

/** The selection as TSV, the format every spreadsheet pastes without a dialog. */
export function selectionToTsv(grid: readonly (readonly Cell[])[]): string {
  return grid
    .map(row => row.map(v => (v === null || v === undefined ? "" : String(v).replace(/[\t\r\n]+/g, " "))).join("\t"))
    .join("\n");
}
