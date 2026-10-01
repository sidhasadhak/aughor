/**
 * columnRoles.test.ts — a chart plots what the result answers, read from the result.
 *
 * The rows are the theLook Agent answers of 2026-10-01, as stored. The repeat-rate answer drew
 * its traffic-source chart with customer counts read as years ("Jan 1000 … Jan 9000"), its
 * country chart as a heatmap with counts for categories, and its cohort chart as a line of a
 * count — never the rate the question asked for. The fulfilment answer put an item count beside
 * two hour averages on one "Value" axis.
 */

import { describe, expect, it } from "vitest";
import { classifyColumns, percentRates, plottedMeasures, rateParts } from "@/components/charts/columnRoles";
import { inferChartType } from "@/components/charts/chartTypeInference";
import { resolveVegaSpec } from "@/components/charts/vega/resolveSpec";
import { seriesTrend } from "@/components/brief/Sparkline";

const RATE_COLS = (cut: string) => [cut, "total_first_time_customers", "repeat_customers", "repeat_rate"];
const COHORTS = {
  columns: RATE_COLS("cohort_month"),
  rows: [["2025-01-01", "1238", "86", "0.06946688206785137"],
         ["2025-02-01", "1214", "106", "0.08731466227347612"],
         ["2025-03-01", "1405", "108", "0.07686832740213523"],
         ["2025-11-01", "1651", "176", "0.10660205935796487"],
         ["2025-12-01", "1823", "220", "0.12068019747668678"]],
};
const SOURCES = {
  columns: RATE_COLS("traffic_source"),
  rows: [["Email", "901", "106", "0.11764705882352941"], ["Facebook", "1082", "105", "0.09704251386321626"],
         ["Search", "12351", "1157", "0.09367662537446361"], ["Organic", "2699", "244", "0.0904038532789922"],
         ["Display", "699", "56", "0.08011444921316166"]],
};
const COUNTRIES = {
  columns: RATE_COLS("country"),
  rows: [["Colombia", "4", "1", "0.25"], ["Belgium", "233", "25", "0.1072961373390558"],
         ["United Kingdom", "809", "81", "0.10012360939431397"], ["China", "5978", "591", "0.09886249581799933"],
         ["Austria", "1", "0", "0.0"]],
};
const CENTRES = {
  columns: ["distribution_center", "avg_hours_to_ship", "avg_hours_to_deliver", "order_count"],
  rows: [["NY/NJ", "34.88826815642459", "61.7932960893855", "179"],
         ["Philadelphia PA", "34.17412935323385", "61.79104477611939", "201"],
         ["Los Angeles CA", "35.00000000000001", "59.65024630541871", "203"]],
};
const col = (g: { columns: string[] }, i: number | undefined) => (i === undefined ? undefined : g.columns[i]);

describe("a date is named as one at the END of its name, or reads as one", () => {
  it("a count whose name holds `_time` in the middle is a measure", () => {
    const { dateIdxs, numericIdxs } = classifyColumns(SOURCES.columns, SOURCES.rows);
    expect(dateIdxs).toEqual([]);
    expect(numericIdxs).toEqual([1, 2, 3]);
  });
  it("a label whose name holds `_time` or `_at` in the middle is a category", () => {
    const columns = ["first_time_buyer", "is_at_risk", "customers"];
    const rows = [["new", "yes", "120"], ["returning", "no", "340"]];
    const { dateIdxs, catIdxs } = classifyColumns(columns, rows);
    expect(dateIdxs).toEqual([]);
    expect(catIdxs.map((i) => columns[i])).toEqual(["first_time_buyer", "is_at_risk"]);
  });
  it("plain numbers under a timestamp suffix are measures; a grain name keeps its numbers", () => {
    const columns = ["has_shipped_at", "avg_delivery_time", "year", "fiscal_year", "created_at", "region"];
    const rows = [["3", "34.5", "2025", "2025", "2025-01-01T00:00:00", "N"],
                  ["4", "36.1", "2026", "2026", "2025-02-01T00:00:00", "S"]];
    const { dateIdxs, numericIdxs } = classifyColumns(columns, rows);
    expect(dateIdxs.map((i) => columns[i])).toEqual(["year", "fiscal_year", "created_at"]);
    expect(numericIdxs.map((i) => columns[i])).toEqual(["has_shipped_at", "avg_delivery_time"]);
  });
});

describe("a rate beside its own numerator and denominator is what the chart plots", () => {
  it("finds the parts on the values, as a fraction or written ×100 to one place", () => {
    expect(rateParts(SOURCES.columns, SOURCES.rows, [1, 2, 3]))
      .toEqual([{ rate: 3, num: 2, den: 1, scaled: false }]);
    const pct = { columns: ["country", "customers", "repeaters", "repeat_pct"],
                  rows: [["Belgium", "233", "25", "10.7"], ["Australia", "406", "30", "7.4"]] };
    expect(rateParts(pct.columns, pct.rows, [1, 2, 3])).toEqual([{ rate: 3, num: 2, den: 1, scaled: true }]);
    pct.rows[1][3] = "7.6";                       // 7.39 is not 7.6 at one decimal
    expect(rateParts(pct.columns, pct.rows, [1, 2, 3])).toEqual([]);
  });
  it("the cohort trend, the source and country rankings all plot the rate", () => {
    expect(inferChartType(COHORTS.columns, COHORTS.rows)).toMatchObject({ type: "line", xCol: 0, yCols: [3] });
    for (const g of [SOURCES, COUNTRIES]) {
      expect(inferChartType(g.columns, g.rows)).toMatchObject({ type: "bar", xCol: 0, yCols: [3] });
    }
  });
  it("an explicit hint plots the rate too, not its first numerator", () => {
    const spec = resolveVegaSpec({ columns: SOURCES.columns, rows: SOURCES.rows, chartType: "bar" })?.spec;
    expect((spec as { encoding: { x: { field: string } } }).encoding.x.field).toBe("repeat_rate");
  });
  it("a rate with no parts beside it changes nothing", () => {
    const g = { columns: ["region", "revenue", "margin_pct"], rows: [["N", "100", "0.2"], ["S", "300", "0.1"]] };
    expect(plottedMeasures(g.columns, g.rows, [1, 2])).toEqual([1, 2]);
    expect(percentRates(g.columns, g.rows, [1, 2]).size).toBe(0);
  });
  it("reads as a percentage on the line and the bar, labels included", () => {
    const line = resolveVegaSpec({ columns: COHORTS.columns, rows: COHORTS.rows, chartType: "auto" });
    const enc = (line?.spec as { encoding: { y: { field: string; axis: { format: string } } } }).encoding;
    expect([enc.y.field, enc.y.axis.format]).toEqual(["repeat_rate", ".1%"]);
    const bar = resolveVegaSpec({ columns: SOURCES.columns, rows: SOURCES.rows, chartType: "auto", showLabels: true });
    expect(JSON.stringify(bar?.spec)).toContain("format(datum['repeat_rate'], '.1%')");
  });
  it("a declared percent written ×100 is scaled down once on a line", () => {
    const g = { columns: ["month", "return_pct"], rows: [["2025-01", "6.9"], ["2025-02", "8.7"], ["2025-03", "7.7"]] };
    const spec = resolveVegaSpec({ columns: g.columns, rows: g.rows, chartType: "auto",
                                   columnUnits: { return_pct: "percent" } })?.spec as Record<string, unknown>;
    expect(spec.transform).toEqual([{ calculate: "datum['return_pct'] / 100", as: "return_pct__frac" }]);
    expect((spec.encoding as { y: { field: string } }).y.field).toBe("return_pct__frac");
  });
});

describe("the count beside an average is its support, not a second bar", () => {
  it("leaves the count out of the measures and out of the grouped bars", () => {
    expect(plottedMeasures(CENTRES.columns, CENTRES.rows, [1, 2, 3]).map((i) => CENTRES.columns[i]))
      .toEqual(["avg_hours_to_ship", "avg_hours_to_deliver"]);
    const spec = resolveVegaSpec({ columns: CENTRES.columns, rows: CENTRES.rows, chartType: "auto" })?.spec;
    expect((spec as { transform: { fold: string[] }[] }).transform[0].fold.sort())
      .toEqual(["avg_hours_to_deliver", "avg_hours_to_ship"]);
  });
});

describe("the trend strip trends the measure its chart plots", () => {
  it("the repeat rate, November to December — not first-time customers", () => {
    const t = seriesTrend(COHORTS.columns, COHORTS.rows);
    expect(t?.values.at(-1)).toBeCloseTo(0.12068, 5);
    expect(t?.lastDelta).toBeCloseTo(0.12068019747668678 / 0.10660205935796487 - 1, 6);
    expect(col(COHORTS, inferChartType(COHORTS.columns, COHORTS.rows)?.yCols[0])).toBe("repeat_rate");
  });
});
