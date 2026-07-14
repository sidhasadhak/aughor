/**
 * ECharts engine — public surface.
 *
 * `buildAutoOption` is the integration seam: it reuses Aughor's existing,
 * battle-tested `inferChartType` (the differentiator Superset lacks) to choose a
 * chart, resolves the column indexes to field names, and dispatches to the pure
 * builder for that type. Chart.tsx will call this and render the returned option
 * via <EChart>, falling back to the legacy Vega path for types not yet ported
 * (combo / heatmap / treemap / matrix / pareto / change-metric).
 */

import type { EChartsOption } from "echarts";
import {
  inferChartType,
  classifyColumns,
  type ChartType,
  type InferredChart,
} from "@/components/charts/chartTypeInference";
import { SHARE_COL, DATE_VALUE_RE, firstNonNull } from "@/components/charts/columnRoles";
import {
  lineOption, multiLineOption, smallMultiplesOption, barOption, groupedBarOption,
  stackedBarOption, pieOption, scatterOption, comboOption, heatmapOption, treemapOption,
  type Row, type BuildInput,
} from "./builders";

export { EChart } from "./EChart";
export * from "./builders";
export { AUGHOR_THEME_NAME, registerAughorTheme } from "./theme";

/** Chart types the ECharts engine can render today (the rest fall back to Vega). */
export const ECHARTS_SUPPORTED: ReadonlySet<ChartType> = new Set<ChartType>([
  "line", "area", "multi-line", "small-multiples", "bar", "grouped-bar", "stacked-bar", "pie", "scatter",
  "combo", "heatmap", "treemap",
]);

export function rowsToObjects(columns: string[], rows: unknown[][]): Row[] {
  return rows.map((r) => {
    const o: Row = {};
    columns.forEach((c, i) => { o[c] = (r as unknown[])[i]; });
    return o;
  });
}

const TIME_TYPES: ReadonlySet<ChartType> = new Set<ChartType>(["line", "area", "multi-line", "small-multiples", "stacked-bar", "heatmap"]);

/** Build an ECharts option from an already-resolved inference + the raw table. */
export function optionFor(
  inferred: InferredChart,
  columns: string[],
  rows: unknown[][],
  opts?: { title?: string; labels?: boolean },
): EChartsOption | null {
  if (!ECHARTS_SUPPORTED.has(inferred.type)) return null;
  const objs = rowsToObjects(columns, rows);
  const { dateIdxs } = classifyColumns(columns, rows);
  const x = columns[inferred.xCol];
  const ys = inferred.yCols.map((c) => columns[c]).filter(Boolean);
  const color = inferred.colorCol != null ? columns[inferred.colorCol] : undefined;
  // A time axis only when the x column is BOTH a temporal dimension AND carries real
  // ISO date VALUES ("2024-01…"). A fiscal/ordinal grain (fiscal_year → "2021".."2025")
  // is temporal but is NOT a continuous time scale — render it as ordered category
  // labels, or 5 yearly points land on a date axis with awkward spacing.
  const xFirst = firstNonNull(rows, inferred.xCol);
  const xIsIsoDate = typeof xFirst === "string" && DATE_VALUE_RE.test(xFirst);
  const xKind: BuildInput["xKind"] =
    TIME_TYPES.has(inferred.type) && dateIdxs.includes(inferred.xCol) && xIsIsoDate ? "time" : "category";
  if (!x || !ys.length) return null;
  const base: BuildInput = { rows: objs, x, ys, color, xKind, title: opts?.title, labels: opts?.labels };

  switch (inferred.type) {
    case "line":        return lineOption(base);
    case "area":        return lineOption(base, true);
    case "multi-line":  return multiLineOption({ ...base, xKind: xKind ?? "time" });
    case "small-multiples": return smallMultiplesOption({ ...base, xKind: xKind ?? "time" });
    case "bar":         return ys.length > 1 ? groupedBarOption(base) : barOption(base);
    case "grouped-bar": return groupedBarOption(base);
    // A share stacked over time is a 100%-stacked bar (composition shift); an absolute measure stacks by volume.
    case "stacked-bar": return stackedBarOption(base, SHARE_COL.test(ys[0]));
    case "pie":         return pieOption(base);
    case "scatter":     return scatterOption(base);
    case "combo":       return ys.length >= 2 ? comboOption(base) : barOption(base);
    case "heatmap":     return color ? heatmapOption(base) : null;
    case "treemap":     return treemapOption(base);
    default:            return null;
  }
}

/** Infer + build in one step. Returns null when the data isn't chartable OR the
 *  inferred type isn't ported to ECharts yet (caller falls back). */
export function buildAutoOption(
  columns: string[],
  rows: unknown[][],
  opts?: { title?: string; labels?: boolean },
): { option: EChartsOption; type: ChartType } | null {
  const inferred = inferChartType(columns, rows);
  if (!inferred) return null;
  const option = optionFor(inferred, columns, rows, opts);
  return option ? { option, type: inferred.type } : null;
}
