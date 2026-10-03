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
import { classifyColumns, isNumeric, plottedMeasures } from "@/components/charts/columnRoles";
import { MONTHS_SHORT, cleanLabel } from "@/lib/format";

/** The forms that draw their y columns as they are: one mark series per measure, by the x column. */
const DRAWS_ITS_MEASURES = new Set(["bar", "grouped-bar", "line", "multi-line", "area", "stacked-bar"]);

/** A month's first day, as the x column of a month-grain result holds it. */
const MONTH_START = /^(\d{4})-(\d{2})-01/;

/** A column as words in a sentence: "average_order_value" → "average order value", "aov" → "AOV". A percent
 *  change reads as a change — its axis carries the % ("Pct change by month", 2026-10-03). */
function phrase(col: string): string {
  return cleanLabel(col).split(" ")
    .map((w) => (w.length > 1 && w === w.toUpperCase() ? w : w.toLowerCase())).join(" ")
    .replace(/^(?:pct|percent|perc) (?=(?:change|growth|increase|decrease|diff|difference|delta)\b)/, "");
}

/** The months a chart draws, as titles name them: "Sep 2025 – Aug 2026", "Sep – Nov 2025", "Jul 2026". "" unless
 *  every point it draws is a month. */
function drawnMonths(rows: unknown[][], x: number, measures: number[]): string {
  const drawn = rows.filter((r) => measures.some((i) => isNumeric(r[i]))).map((r) => String(r[x] ?? "")).sort();
  if (!drawn.length || !drawn.every((v) => MONTH_START.test(v))) return "";
  const a = drawn[0].match(MONTH_START)!, b = drawn[drawn.length - 1].match(MONTH_START)!;
  const m = (g: RegExpMatchArray) => MONTHS_SHORT[Number(g[2]) - 1];
  if (a[1] === b[1] && a[2] === b[2]) return `${m(a)} ${a[1]}`;
  return a[1] === b[1] ? `${m(a)} – ${m(b)} ${a[1]}` : `${m(a)} ${a[1]} – ${m(b)} ${b[1]}`;
}

/** A title's period written in months — "Aug 2025 – Aug 2026", "Aug – Dec 2025", "Jul 2026", "2025" — not in days. */
function namesMonths(period: string): boolean {
  const words = period.split(/\s+|–/).filter(Boolean);
  return words.some((w) => /^\d{4}$/.test(w)) && words.every((w) => /^\d{4}$/.test(w) || MONTHS_SHORT.includes(w));
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
  const drawnIdx = inferred.type === "grouped-bar" ? inferred.yCols : inferred.yCols.slice(0, 1);
  const drawn = drawnIdx.map((i) => columns[i]);
  // The months it draws, not the window its SQL filtered on: a change has none for the month it is measured from,
  // and a query that read August only to measure September from it returns September on (Q3, 2026-10-03).
  const months = inferred.xCol >= 0 ? drawnMonths(rows, inferred.xCol, drawnIdx) : "";
  const period = (text: string) => {
    const said = text.match(/ — ([^—]*)$/);
    return months && said && said[1] !== months && namesMonths(said[1]) ? `${text.slice(0, said.index)} — ${months}` : text;
  };
  const measured = plottedMeasures(columns, rows, classifyColumns(columns, rows).numericIdxs).map((i) => columns[i]);
  if (measured.every((m) => drawn.includes(m))) return period(title);
  const by = [inferred.xCol, inferred.colorCol]
    .filter((i): i is number => typeof i === "number" && i >= 0)
    .map((i) => phrase(columns[i]));
  const cut = title.search(/ where | — /);
  const caption = `${listed(drawn.map(phrase))}${by.length ? ` by ${listed(by)}` : ""}${cut >= 0 ? title.slice(cut) : ""}`;
  return period(caption.charAt(0).toUpperCase() + caption.slice(1));
}

/** The one series an auto chart draws — its x values and its measure's — or null when it draws another form,
 *  several series or fewer than two points. */
function drawnSeries(columns: string[], rows: unknown[][], chartType?: string | null): Map<string, number> | null {
  if (String(chartType ?? "auto").toLowerCase() !== "auto" || rows.length < 2) return null;
  const inferred = inferChartType(columns, rows);
  if (!inferred || !DRAWS_ITS_MEASURES.has(inferred.type) || inferred.type === "grouped-bar"
      || (inferred.colorCol ?? -1) >= 0 || inferred.xCol < 0 || inferred.yCols[0] === undefined) return null;
  const series = new Map<string, number>();
  for (const r of rows) if (isNumeric(r[inferred.yCols[0]])) series.set(String(r[inferred.xCol]), Number(r[inferred.yCols[0]]));
  return series.size >= 2 ? series : null;
}

/** The results whose chart another result's chart already draws: every point of its series is a point of the
 *  other's. Q3 (2026-10-03) drew monthly revenue twice — September to August, and again from the August before.
 *  The longer is drawn; of two the same, the first. */
export function repeatedCharts(results: { id: string; columns: string[]; rows: unknown[][]; chartType?: string | null }[]): Set<string> {
  const all = results.map((r) => ({ id: r.id, s: drawnSeries(r.columns, r.rows, r.chartType) }));
  const same = (a: number, b: number) => Math.abs(a - b) <= 1e-9 * Math.max(1, Math.abs(a));
  return new Set(all.filter((a, i) => a.s && all.some((b, j) => j !== i && b.s
    && (b.s.size > a.s!.size || (b.s.size === a.s!.size && j < i))
    && [...a.s!].every(([x, y]) => b.s!.has(x) && same(y, b.s!.get(x)!)))).map((a) => a.id));
}

