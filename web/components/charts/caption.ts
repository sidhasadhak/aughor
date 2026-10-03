/**
 * A chart's caption names what the chart draws.
 *
 * A result's title names everything the result measured: "Revenue and average order value by
 * category — 4 Mar – 3 Sep 2026". A chart of two measures on scales far apart draws only the first
 * (CA-4: never a dual axis), so on 2026-10-03 the caption over Q2's revenue bars named a measure no
 * bar showed. Q3's change chart was captioned with the result's three measures and drew one. The title
 * still names the result wherever the result is shown whole, in its source link and its table.
 *
 * Only for a chart the inference chose ("auto"), and only where its marks are measures read whole:
 * one bar or line per measure. A form that draws something else — a difference, a scatter, a grid —
 * keeps the title.
 */
import { inferChartType } from "@/components/charts/chartTypeInference";
import { classifyColumns, plottedMeasures } from "@/components/charts/columnRoles";
import { cleanLabel } from "@/lib/format";

/** The forms that draw their y columns as they are: one mark series per measure, by the x column. */
const DRAWS_ITS_MEASURES = new Set(["bar", "grouped-bar", "line", "multi-line", "area", "stacked-bar"]);

/** A column as words in a sentence: "average_order_value" → "average order value", "aov" → "AOV". */
function phrase(col: string): string {
  return cleanLabel(col).split(" ")
    .map((w) => (w.length > 1 && w === w.toUpperCase() ? w : w.toLowerCase())).join(" ");
}

function listed(names: string[]): string {
  return names.length <= 1 ? (names[0] ?? "") : `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`;
}

/** The caption for a result's chart: the title, unless the chart draws fewer measures than the result
 *  measured — then what it draws, by what, with the title's own filters and period. */
export function chartCaption(title: string, columns: string[], rows: unknown[][], chartType?: string | null): string {
  if (!title || String(chartType ?? "auto").toLowerCase() !== "auto") return title;
  const inferred = inferChartType(columns, rows);
  if (!inferred || !DRAWS_ITS_MEASURES.has(inferred.type) || !inferred.yCols.length) return title;
  const drawn = (inferred.type === "grouped-bar" ? inferred.yCols : inferred.yCols.slice(0, 1)).map((i) => columns[i]);
  const measured = plottedMeasures(columns, rows, classifyColumns(columns, rows).numericIdxs).map((i) => columns[i]);
  if (measured.every((m) => drawn.includes(m))) return title;
  const by = [inferred.xCol, inferred.colorCol]
    .filter((i): i is number => typeof i === "number" && i >= 0)
    .map((i) => phrase(columns[i]));
  const cut = title.search(/ where | — /);
  const caption = `${listed(drawn.map(phrase))}${by.length ? ` by ${listed(by)}` : ""}${cut >= 0 ? title.slice(cut) : ""}`;
  return caption.charAt(0).toUpperCase() + caption.slice(1);
}
