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

import {
  isIdLike, INSTRUMENTATION_COL as INSTRUMENTATION,
  SHARE_COL, CHANGE_METRIC_COL as CHANGE_METRIC, ADDITIVE_COL,
  countUnique, classifyColumns,
} from "./columnRoles";

// Re-exported so existing importers of these from chartTypeInference keep working while the
// single source of truth lives in columnRoles.ts.
export { classifyColumns, SHARE_COL };

export type ChartType =
  | "line"
  | "multi-line"
  | "small-multiples"
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

// Column classifier patterns + the classifier itself now live in ./columnRoles (imported above),
// so the type-inference here and the renderer in Chart.tsx share ONE source of truth.

/**
 * Score whether a multi-measure, single-category chart should be a dual-axis COMBO
 * (bar + line on independent y-axes) or a plain single-measure BAR.
 *
 * A dual axis only EARNS its complexity when the two measures can't honestly share
 * one axis — they're different UNITS (a magnitude + a 0–1 rate) or wildly different
 * SCALES (>=25x). Two same-unit, similar-scale counts on independent axes are
 * actively MISLEADING (they look equal when they aren't), so those collapse to a
 * single bar of the primary magnitude. Returns the chosen bar (+ line) column idx.
 */
export function scoreDualAxis(
  columns: string[],
  rows: unknown[][],
  numericIdxs: number[],
): { combo: boolean; barIdx: number; lineIdx?: number; groupIdxs: number[]; reason: string } {
  const nums = (i: number) => rows.map((r) => Number((r as unknown[])[i])).filter((v) => !isNaN(v));
  const maxAbs = (i: number) => { const v = nums(i); return v.length ? Math.max(...v.map(Math.abs)) : 0; };
  const isShare = (i: number) => {
    const v = nums(i);
    return v.length > 0 && SHARE_COL.test(columns[i]) && v.every((n) => Math.abs(n) <= 1.0001);
  };
  // Real measures only: not an id/key, not audit-only instrumentation, and has at least one
  // non-null numeric value (an all-null column carries nothing and must never reach a chart).
  // Fall back to the unfiltered set only if excluding instrumentation would leave nothing.
  const _real = numericIdxs.filter((i) => !isIdLike(columns[i]) && !INSTRUMENTATION.test(columns[i]) && nums(i).length > 0);
  const measures = _real.length ? _real : numericIdxs.filter((i) => !isIdLike(columns[i]) && nums(i).length > 0);
  const rates     = measures.filter(isShare).sort((a, b) => maxAbs(b) - maxAbs(a));
  const absolutes = measures.filter((i) => !isShare(i)).sort((a, b) => maxAbs(b) - maxAbs(a));
  const primary   = absolutes[0] ?? rates[0] ?? measures[0] ?? numericIdxs[0];

  if (measures.length < 2) return { combo: false, barIdx: primary, groupIdxs: [primary], reason: "single measure" };

  // (1) magnitude + rate → genuinely different units → dual axis clarifies
  if (absolutes.length >= 1 && rates.length >= 1) {
    return { combo: true, barIdx: absolutes[0], lineIdx: rates[0], groupIdxs: [absolutes[0], rates[0]], reason: "magnitude + rate" };
  }
  // (2) two absolutes with a large scale gap → the smaller would vanish on a shared axis
  if (absolutes.length >= 2) {
    const ratio = maxAbs(absolutes[1]) > 0 ? maxAbs(absolutes[0]) / maxAbs(absolutes[1]) : Infinity;
    if (ratio >= 25) return { combo: true, barIdx: absolutes[0], lineIdx: absolutes[1], groupIdxs: [absolutes[0], absolutes[1]], reason: `scale gap ${Math.round(ratio)}x` };
  }
  // Same UNIT (multiple absolutes, or multiple rates), similar scale → a GROUPED bar
  // shows them side by side on one honest shared axis (no dropped series, no
  // misleading independent axes). Cap at 4 series for readability.
  const sameUnit = absolutes.length >= 2 ? absolutes : rates;
  if (sameUnit.length >= 2) {
    return { combo: false, barIdx: primary, groupIdxs: sameUnit.slice(0, 4), reason: "grouped (same-unit measures)" };
  }
  // Fallback → one honest bar of the primary magnitude
  return { combo: false, barIdx: primary, groupIdxs: [primary], reason: "single bar" };
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

    // COMPOSITION OVER TIME — a SHARE measure across a few groups → 100%-stacked bar (the shift in
    // the mix reads directly). Chart.tsx / optionFor render it in percent mode for a share measure.
    if (SHARE_COL.test(columns[numIdx]) && uniqueSeriesCount <= 8) {
      return { type: "stacked-bar", xCol: dateIdx, yCols: [numIdx], colorCol: catIdx };
    }
    // Many groups → a many-line spaghetti chart is unreadable. Small multiples (a grid of mini lines,
    // one per group, shared y-scale) up to 9 groups; beyond that a heatmap is the most compact.
    if (uniqueSeriesCount > 9) {
      return { type: "heatmap", xCol: dateIdx, yCols: [numIdx], colorCol: catIdx };
    }
    if (uniqueSeriesCount > 6) {
      return { type: "small-multiples", xCol: dateIdx, yCols: [numIdx], colorCol: catIdx };
    }
    // Low-cardinality absolute metric: multi-line for trend comparison
    return { type: "multi-line", xCol: dateIdx, yCols: [numIdx], colorCol: catIdx };
  }

  // ── NO TIME AXIS ─────────────────────────────────────────────────────────

  // Two pure numerics, no category → scatter (correlation / outlier detection)
  if (numericIdxs.length === 2 && catIdx === undefined && rows.length >= 10) {
    return { type: "scatter", xCol: numericIdxs[0], yCols: [numericIdxs[1]] };
  }

  // Category present, no time axis. WHEN-TO-USE (pick the chart by data shape + intent,
  // not "bar+line for everything"):
  //   • ≥2 measures           → scoreDualAxis: COMBO only for genuinely different units
  //                             (magnitude + 0-1 rate) or ≥25x scale; else GROUPED/BAR.
  //   • 1 ADDITIVE measure, ≤6 categories  → PIE       (parts of a whole, few slices)
  //   • 1 ADDITIVE measure, 7-24 categories → TREEMAP  (composition across many parts —
  //                             a 20-slice pie is unreadable, a 20-bar long tail buries it)
  //   • otherwise (rates, averages, ranking) → BAR     (comparison / ranking)
  if (catIdx !== undefined) {
    const uniqueCatCount = countUnique(rows, catIdx);

    if (numericIdxs.length >= 2) {
      const d = scoreDualAxis(columns, rows, numericIdxs);
      return d.combo
        ? { type: "combo", xCol: catIdx, yCols: [d.barIdx, d.lineIdx!] }
        : { type: "bar",   xCol: catIdx, yCols: [d.barIdx] };
    }

    // Single measure — composition (pie/treemap) for an ADDITIVE magnitude OR a SHARE that sums to a
    // whole. You don't pie a conversion RATE (each row's own rate, no whole to compose), but you DO
    // pie a `pct_of_total` whose slices sum to ~100% — a genuine parts-of-a-whole (this is what makes
    // a "share of returns" composition a donut on the quick path too, matching the ADA lens).
    const additive = ADDITIVE_COL.test(columns[numIdx]) && !SHARE_COL.test(columns[numIdx]);
    const shareVals = rows.map((r) => Number((r as unknown[])[numIdx])).filter((v) => !isNaN(v));
    const shareSum = shareVals.reduce((s, v) => s + v, 0);
    const isShareComposition = SHARE_COL.test(columns[numIdx]) && shareVals.length > 0
      && (Math.abs(shareSum - 100) <= 2 || Math.abs(shareSum - 1) <= 0.02);

    if ((additive || isShareComposition) && uniqueCatCount <= 6) {
      return { type: "pie", xCol: catIdx, yCols: numericIdxs };
    }
    if (additive && uniqueCatCount > 6 && uniqueCatCount <= 24) {
      return { type: "treemap", xCol: catIdx, yCols: numericIdxs };
    }
    return { type: "bar", xCol: catIdx, yCols: numericIdxs };
  }

  return null;
}

/** Every chart type the unified <Chart> engine can actually RENDER for the given data
 *  shape — the gallery for the Query Builder display dropdown. Unlike availableTypesFor
 *  (which keys off a single inferred type and offers a narrow swap list), this keys off
 *  the column classification so it can offer the full set the data supports (combo, pie,
 *  heatmap, treemap, scatter, stacked, area …) without ever offering a type that would
 *  render blank for the shape. Returns [] when the data isn't chartable. */
export function availableChartTypes(columns: string[], rows: unknown[][]): ChartType[] {
  if (!columns.length || rows.length < 2) return [];
  const { dateIdxs, numericIdxs, catIdxs } = classifyColumns(columns, rows);
  const nNum = numericIdxs.length;
  if (!nNum) return [];
  const hasDate = dateIdxs.length > 0;
  const hasCat  = catIdxs.length > 0;
  const out: ChartType[] = [];
  const add = (t: ChartType) => { if (!out.includes(t)) out.push(t); };

  if (hasDate && hasCat) {
    // time × category — one series per category value
    add("multi-line"); add("small-multiples"); add("stacked-bar"); add("heatmap");
  } else if (hasDate) {
    // pure time series
    add("line"); add("area"); add("bar");
  }

  if (hasCat && !hasDate) {
    if (nNum >= 2) add("combo");
    add("bar");
    if (nNum === 1 && countUnique(rows, catIdxs[0]) <= 12) add("pie");
    add("treemap");
  }

  if (!hasDate && !hasCat && nNum >= 2) add("scatter");

  return out;
}

/** Chart types the unified <Chart> engine can switch between for a given inferred type —
 *  the gallery shared by InvestigationChart and the Query Builder Explore rail. */
export function availableTypesFor(inferred: ChartType): ChartType[] {
  switch (inferred) {
    case "line":        return ["line", "bar"];
    case "multi-line":  return ["multi-line", "small-multiples", "heatmap", "stacked-bar"];
    case "small-multiples": return ["small-multiples", "multi-line", "heatmap", "stacked-bar"];
    case "heatmap":     return ["heatmap", "multi-line", "small-multiples", "stacked-bar"];
    case "scatter":     return ["scatter", "bar"];
    case "pie":         return ["pie", "bar", "treemap"];
    case "treemap":     return ["treemap", "bar", "pie"];
    case "combo":       return ["combo", "bar"];
    default:            return ["bar", "line"];
  }
}

/** True when the column name looks like a 0–1 share / rate / percentage. */
export function isShareColumn(colName: string, rows: unknown[][], colIdx: number): boolean {
  if (!SHARE_COL.test(colName)) return false;
  return rows.slice(0, 20).every(r => {
    const n = Number((r as unknown[])[colIdx]);
    return !isNaN(n) && n >= 0 && n <= 1;
  });
}
