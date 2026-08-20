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
  countUnique, classifyColumns, isUngraphableGrid,
  GEO_NAME_COL, LAT_COL, LON_COL,
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
  | "combo"      // bar + line with dual y-axes — LEGACY ONLY (never offered, never inferred; §6 bans dual axes)
  | "delta-bar"  // signed per-item delta (obs − comp) — the period-over-period form
  | "stacked-bar"
  | "scatter"
  | "heatmap"
  | "matrix"
  | "pie"
  | "treemap"
  // ── native-fit additions (2026-07 viz-type wave) ──
  | "counter"    // single big-number KPI of the primary measure
  | "funnel"     // stage → value drop-off (few categories)
  | "histogram"  // distribution of ONE numeric column, binned
  | "boxplot"    // five-number distribution, per category
  | "sankey"     // flow between two dimensions (source → target)
  | "waterfall"  // running total of signed contributions
  // ── Tier-2 additions (heavier infra / narrower fit) ──
  | "line-forecast" // timeseries + a deterministic projection + confidence band
  | "gantt"      // task spans on a time axis (label + start + end)
  | "choropleth" // region → measure shaded on a map (needs geojson)
  | "point-map"  // lat/lon points on a base map
  | "table";

// ── Central type vocab (single source of truth) ─────────────────────────────
// Both TYPE_TO_HINT (ChartType → the underscore "hint" the <Chart> engine speaks)
// and CHART_TYPE_LABEL used to be duplicated across ResultChartCard, InvestigationChart
// and QueryBuilder — the exact drift this module exists to prevent. They live here now;
// every surface imports these so a new type is wired in ONE place.

/** ChartType (hyphenated) → the underscore hint `<Chart>` dispatches on. */
export const TYPE_TO_HINT: Record<ChartType, string> = {
  "line": "line", "area": "area", "multi-line": "multi_line", "small-multiples": "small_multiples",
  "bar": "bar", "grouped-bar": "grouped_bar", "combo": "combo", "delta-bar": "delta_bar", "stacked-bar": "stacked_bar",
  "scatter": "scatter", "heatmap": "heatmap", "matrix": "heatmap", "pie": "pie", "treemap": "treemap",
  "counter": "counter", "funnel": "funnel", "histogram": "histogram", "boxplot": "boxplot",
  "sankey": "sankey", "waterfall": "waterfall",
  "line-forecast": "line_forecast", "gantt": "gantt", "choropleth": "choropleth", "point-map": "point_map",
  "table": "auto",
};

/** Every user-selectable chart type, in a stable display order. The viz editor offers ALL
 *  of these (compatible ones lead — see availableChartTypes) so a user can pick any type,
 *  Databricks-style; an incompatible pick degrades rather than being hidden. Excludes the
 *  internal-only `matrix` (folds into heatmap) and `table` (a separate view toggle). */
export const ALL_CHART_TYPES: ChartType[] = [
  "bar", "line", "area", "delta-bar", "grouped-bar", "stacked-bar", "multi-line", "small-multiples",
  "scatter", "pie", "treemap", "heatmap", "histogram", "boxplot", "funnel", "waterfall",
  "sankey", "counter", "line-forecast", "gantt", "choropleth", "point-map",
];

/** The underscore engine hint → the ChartType it renders as. Reverse of TYPE_TO_HINT plus
 *  the engine-only variants (bar_horizontal/bar_vertical → bar, pareto → bar). Lets a surface
 *  DISPLAY the resolved type ("Bar") for an auto/backend-hinted chart instead of "Auto". */
export const HINT_TO_TYPE: Record<string, ChartType> = {
  line: "line", area: "area", multi_line: "multi-line", small_multiples: "small-multiples",
  bar: "bar", bar_horizontal: "bar", bar_vertical: "bar", combo: "combo", stacked_bar: "stacked-bar",
  grouped_bar: "grouped-bar", delta_bar: "delta-bar",
  // CA-4 form-by-job: the model names the data's JOB; each job renders as its form.
  magnitude: "bar", trend: "line", identity: "stacked-bar", change: "delta-bar",
  share: "stacked-bar", distribution: "histogram", relation: "scatter",
  scatter: "scatter", heatmap: "heatmap", matrix: "heatmap", pie: "pie", treemap: "treemap", pareto: "bar",
  counter: "counter", funnel: "funnel", histogram: "histogram", boxplot: "boxplot", sankey: "sankey",
  waterfall: "waterfall", line_forecast: "line-forecast", gantt: "gantt", choropleth: "choropleth", point_map: "point-map",
};

/** Human label for each type — the dropdown/gallery text. */
export const CHART_TYPE_LABEL: Record<ChartType | "auto", string> = {
  "auto": "Auto", "line": "Line", "area": "Area", "multi-line": "Multi-line",
  "small-multiples": "Small multiples", "bar": "Bar", "grouped-bar": "Grouped", "combo": "Combo",
  "stacked-bar": "Stacked", "delta-bar": "Delta", "scatter": "Scatter", "heatmap": "Heatmap", "matrix": "Matrix",
  "pie": "Pie", "treemap": "Treemap", "counter": "Counter", "funnel": "Funnel",
  "histogram": "Histogram", "boxplot": "Box plot", "sankey": "Sankey", "waterfall": "Waterfall",
  "line-forecast": "Line (forecast)", "gantt": "Gantt", "choropleth": "Choropleth map", "point-map": "Point map",
  "table": "Table",
};

/** CA-4 form-by-job: job token → the underscore engine hint its form renders as.
 *  MIRRORS aughor/agent/chart_vocab.py JOB_TO_FORM — the parity test walks both. */
export const JOB_TO_ENGINE_HINT: Record<string, string> = {
  magnitude: "bar_horizontal", trend: "line", identity: "stacked_bar",
  change: "delta_bar", share: "stacked_bar", distribution: "histogram", relation: "scatter",
};

export interface InferredChart {
  type: ChartType;
  xCol: number;    // index of the x-axis / category column
  yCols: number[]; // indexes of numeric columns to plot
  colorCol?: number; // index of the series/stack/segment column (multi-line, stacked, heatmap)
}

// Column classifier patterns + the classifier itself now live in ./columnRoles (imported above),
// so the type-inference here and the renderer in Chart.tsx share ONE source of truth.

/**
 * CA-4 form-by-job: what to do with MULTIPLE measures over one category — the
 * successor of the dual-axis scorer (dual axes are banned, §6; two measures of
 * different units get the primary alone, never two y-scales).
 *
 *   • a PERIOD PAIR (obs/comp, current/previous, two date-named columns of the
 *     same unit) → "delta": one signed delta bar — never grouped before/after
 *     bars (the reader wants the change, not two heights to subtract mentally);
 *   • same-unit, similar-scale measures → "grouped" (≤4 series, one honest axis);
 *   • different units or a ≥25x scale gap → "bar" of the primary magnitude (the
 *     second measure stays in the table/tooltip).
 */
const PAIR_BEFORE = /(^|_)(prev|previous|prior|last|comp|comparison|baseline|before|old)($|_)/i;
const PAIR_AFTER = /(^|_)(curr|current|this|obs|observation|now|after|new|latest)($|_)/i;
const PAIR_DATEISH = /(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec|q[1-4]|20\d\d|\d{4}_\d{2}|_w?\d{1,2}$)/i;

export function chooseMultiMeasure(
  columns: string[],
  rows: unknown[][],
  numericIdxs: number[],
): { mode: "delta" | "grouped" | "bar"; barIdx: number; pair?: [number, number]; groupIdxs: number[]; reason: string } {
  const nums = (i: number) => rows.map((r) => Number((r as unknown[])[i])).filter((v) => !isNaN(v));
  const maxAbs = (i: number) => { const v = nums(i); return v.length ? Math.max(...v.map(Math.abs)) : 0; };
  const isShare = (i: number) => {
    const v = nums(i);
    return v.length > 0 && SHARE_COL.test(columns[i]) && v.every((n) => Math.abs(n) <= 1.0001);
  };
  const _real = numericIdxs.filter((i) => !isIdLike(columns[i]) && !INSTRUMENTATION.test(columns[i]) && nums(i).length > 0);
  const measures = _real.length ? _real : numericIdxs.filter((i) => !isIdLike(columns[i]) && nums(i).length > 0);
  const rates     = measures.filter(isShare).sort((a, b) => maxAbs(b) - maxAbs(a));
  const absolutes = measures.filter((i) => !isShare(i)).sort((a, b) => maxAbs(b) - maxAbs(a));
  const primary   = absolutes[0] ?? rates[0] ?? measures[0] ?? numericIdxs[0];

  if (measures.length < 2) return { mode: "bar", barIdx: primary, groupIdxs: [primary], reason: "single measure" };

  // Period pair → delta. Same unit only (two absolutes or two rates); the pair is
  // recognised by before/after naming or two date-named columns.
  const sameUnit = absolutes.length >= 2 ? absolutes : rates.length >= 2 ? rates : [];
  if (sameUnit.length === 2 && measures.length === 2) {
    const [a, b] = sameUnit;
    const named = (PAIR_BEFORE.test(columns[a]) && PAIR_AFTER.test(columns[b]))
      || (PAIR_BEFORE.test(columns[b]) && PAIR_AFTER.test(columns[a]))
      || (PAIR_DATEISH.test(columns[a]) && PAIR_DATEISH.test(columns[b]));
    if (named) {
      const before = PAIR_BEFORE.test(columns[a]) || (!PAIR_BEFORE.test(columns[b]) && columns[a] < columns[b]) ? a : b;
      const after = before === a ? b : a;
      return { mode: "delta", barIdx: after, pair: [before, after], groupIdxs: [before, after], reason: "period pair" };
    }
  }

  // Different units, or a scale gap that would bury the smaller → the primary alone.
  if (absolutes.length >= 1 && rates.length >= 1) {
    return { mode: "bar", barIdx: absolutes[0], groupIdxs: [absolutes[0]], reason: "mixed units — primary only (no dual axis)" };
  }
  if (absolutes.length >= 2) {
    const ratio = maxAbs(absolutes[1]) > 0 ? maxAbs(absolutes[0]) / maxAbs(absolutes[1]) : Infinity;
    if (ratio >= 25) return { mode: "bar", barIdx: absolutes[0], groupIdxs: [absolutes[0]], reason: `scale gap ${Math.round(ratio)}x — primary only` };
  }
  if (sameUnit.length >= 2) {
    return { mode: "grouped", barIdx: primary, groupIdxs: sameUnit.slice(0, 4), reason: "grouped (same-unit measures)" };
  }
  return { mode: "bar", barIdx: primary, groupIdxs: [primary], reason: "single bar" };
}

/**
 * Infer the best chart type for the given columns + rows.
 * Returns null when the data is not chartable (< 2 rows, no numeric cols, etc.)
 */
export function inferChartType(
  columns: string[],
  rows: unknown[][],
): InferredChart | null {
  if (!columns.length || !rows.length) return null;
  // Chart-grammar gate: a stats/entity-profile grid is a table, never a chart.
  if (isUngraphableGrid(columns, rows)) return null;

  const { dateIdxs, numericIdxs, catIdxs } = classifyColumns(columns, rows);

  if (!numericIdxs.length) return null;

  // CA-4 form-by-job: ONE ROW is a headline number, not a one-bar bar chart —
  // the stat tile is the form.
  if (rows.length === 1) {
    const m = numericIdxs.find((i) => !isIdLike(columns[i]) && !INSTRUMENTATION.test(columns[i])) ?? numericIdxs[0];
    return { type: "counter", xCol: catIdxs[0] ?? dateIdxs[0] ?? m, yCols: [m] };
  }
  if (rows.length < 2) return null;

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
      // CA-4: never a dual axis. A period pair renders its DELTA (never grouped
      // before/after bars); same-unit measures group; mixed units keep the primary.
      const d = chooseMultiMeasure(columns, rows, numericIdxs);
      if (d.mode === "delta" && d.pair) return { type: "delta-bar", xCol: catIdx, yCols: [d.pair[0], d.pair[1]] };
      if (d.mode === "grouped") return { type: "grouped-bar", xCol: catIdx, yCols: d.groupIdxs };
      return { type: "bar", xCol: catIdx, yCols: [d.barIdx] };
    }

    // Single measure — composition (pie/treemap) for an ADDITIVE magnitude OR a SHARE that sums to a
    // whole. You don't pie a conversion RATE (each row's own rate, no whole to compose), but you DO
    // pie a `pct_of_total` whose slices sum to ~100% — a genuine parts-of-a-whole (this is what makes
    // a "share of returns" composition a donut on the quick path too, matching the deep-analysis lens).
    const additive = ADDITIVE_COL.test(columns[numIdx]) && !SHARE_COL.test(columns[numIdx]);
    const shareVals = rows.map((r) => Number((r as unknown[])[numIdx])).filter((v) => !isNaN(v));
    const shareSum = shareVals.reduce((s, v) => s + v, 0);
    const isShareComposition = SHARE_COL.test(columns[numIdx]) && shareVals.length > 0
      && (Math.abs(shareSum - 100) <= 2 || Math.abs(shareSum - 1) <= 0.02);

    // CA-4: composition never auto-infers a donut — a ranked bar of the parts
    // reads the magnitudes directly (pie stays a manual pick). Many-part additive
    // compositions keep the treemap (7-24 parts, where a bar's long tail buries it).
    if ((additive || isShareComposition) && uniqueCatCount <= 6) {
      return { type: "bar", xCol: catIdx, yCols: numericIdxs };
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
  const hasDate = dateIdxs.length > 0;
  const hasCat  = catIdxs.length > 0;
  const out: ChartType[] = [];
  const add = (t: ChartType) => { if (!out.includes(t)) out.push(t); };

  // ── Tier-2 geo / gantt — may apply to shapes WITHOUT a standard numeric measure, so
  //    they're evaluated before the numeric gate below. ──
  const hasLat = columns.some((c) => LAT_COL.test(c));
  const hasLon = columns.some((c) => LON_COL.test(c));
  if (hasLat && hasLon) add("point-map");
  if (catIdxs.some((i) => GEO_NAME_COL.test(columns[i])) && nNum >= 1) add("choropleth");
  if (dateIdxs.length >= 2) add("gantt");   // a label + start + end span

  if (!nNum) return out;   // the standard charts below all need a measure

  if (hasDate && hasCat) {
    // time × category — one series per category value
    add("multi-line"); add("small-multiples"); add("stacked-bar"); add("heatmap");
  } else if (hasDate) {
    // pure time series
    add("line"); add("area"); add("bar");
    if (nNum === 1) add("line-forecast");   // project a single trend forward
  }

  if (hasCat && !hasDate) {
    if (nNum >= 2) { add("grouped-bar"); add("delta-bar"); }
    add("bar");
    if (nNum === 1 && countUnique(rows, catIdxs[0]) <= 12) add("pie");
    add("treemap");
  }

  if (!hasDate && !hasCat && nNum >= 2) add("scatter");

  // ── native-fit specialized types — offered only where the shape renders something honest ──
  const nRows = rows.length;
  // Funnel — an ordered drop-off across a handful of categories (parts of a process).
  if (hasCat && !hasDate && nNum >= 1 && countUnique(rows, catIdxs[0]) <= 12) add("funnel");
  // Waterfall — signed contributions building to a total (category, or a short time sequence).
  if ((hasCat || hasDate) && nNum >= 1 && countUnique(rows, hasCat ? catIdxs[0] : dateIdxs[0]) <= 24) add("waterfall");
  // Sankey — flow between TWO dimensions (source → target), weighted by a measure.
  if (catIdxs.length >= 2 && nNum >= 1) add("sankey");
  // Histogram + Box plot — the distribution of a numeric column (needs enough values to bin/summarise).
  if (nNum >= 1 && nRows >= 8) { add("histogram"); add("boxplot"); }
  // Counter — a single big-number KPI of the primary measure (a valid view of any measured result).
  if (nNum >= 1) add("counter");

  return out;
}

/** Chart types the unified <Chart> engine can switch between for a given inferred type —
 *  the gallery shared by InvestigationChart and the Query Builder Explore rail. */
export function availableTypesFor(inferred: ChartType): ChartType[] {
  switch (inferred) {
    case "line":        return ["line", "bar", "counter", "line-forecast"];
    case "multi-line":  return ["multi-line", "small-multiples", "heatmap", "stacked-bar"];
    case "small-multiples": return ["small-multiples", "multi-line", "heatmap", "stacked-bar"];
    case "heatmap":     return ["heatmap", "multi-line", "small-multiples", "stacked-bar"];
    case "scatter":     return ["scatter", "bar", "histogram"];
    case "pie":         return ["pie", "bar", "treemap", "funnel"];
    case "treemap":     return ["treemap", "bar", "pie"];
    case "delta-bar":   return ["delta-bar", "grouped-bar", "bar"];
    case "grouped-bar": return ["grouped-bar", "delta-bar", "bar"];
    default:            return ["bar", "line", "counter"];
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
