/**
 * A query card's chart (Arc AP-7): what the person set up is what is drawn — bars stacked, side by side or as shares, a
 * line never stacked, a scatter placed by two numbers — in the theme's colours in a fixed order, Other in its grey, and
 * labels only where they say something.
 */
import { describe, expect, it } from "vitest";

import type { QueryShaped } from "@/lib/api";
import { queryChartSpec, seriesColours, xText } from "@/lib/cockpit/queryChart";

type Chart = Extract<QueryShaped, { as: "bar" | "line" | "area" | "scatter" }>;
const COLOURS = { palette: ["#c1", "#c2", "#c3"], other: "#grey" };
const DAYS = ["2026-10-08", "2026-10-09", "2026-10-10"];

function chart(as: Chart["as"], split = true, kind: Chart["x"]["kind"] = "date"): Chart {
  const series = split ? ["China", "United States", "Other"] : [""];
  return {
    as, x: { name: "day", kind, bucket: kind === "date" ? "day" : "" }, series, other: split, said: [],
    points: DAYS.flatMap((d, i) => series.map((s, j) => ({ x: kind === "text" ? ["Shipped", "Processing", "Returned"][i] : d, s, v: 10 * (i + 1) + j }))),
  };
}
const setup = (segments: "stacked" | "side_by_side" | "shares" = "stacked", labels = false) => ({ segments, labels, running: false });
type Layer = { mark: Record<string, unknown>; encoding: Record<string, Record<string, unknown>>; transform?: Record<string, unknown>[] };
const layers = (spec: Record<string, unknown>) => spec.layer as Layer[];

describe("a query card's chart", () => {
  it("stacks its bars, colours each series in order and Other in the theme's grey, and says each date by its bucket", () => {
    const spec = queryChartSpec(chart("bar"), setup(), COLOURS);
    const [bars] = layers(spec);
    expect(bars.mark.type).toBe("bar");
    expect(bars.encoding.y.stack).toBe("zero");
    expect(bars.encoding.color.scale).toEqual({ domain: ["China", "United States", "Other"], range: ["#c1", "#c2", "#grey"] });
    expect(bars.encoding.xOffset).toBeUndefined();
    expect((spec.data as { values: { x: string }[] }).values[0].x).toMatch(/Oct 8/);
  });

  it("stands its bars side by side, or shows shares on an axis of per cents", () => {
    const side = layers(queryChartSpec(chart("bar"), setup("side_by_side"), COLOURS))[0];
    expect(side.encoding.y.stack).toBeNull();
    expect(side.encoding.xOffset).toEqual({ field: "s", sort: ["China", "United States", "Other"] });
    const shares = layers(queryChartSpec(chart("bar"), setup("shares"), COLOURS))[0];
    expect(shares.encoding.y.stack).toBe("normalize");
    expect((shares.encoding.y.axis as { format: string }).format).toBe(".0%");
  });

  it("never stacks a line, lays areas over each other when asked, and places a scatter by two numbers", () => {
    expect(layers(queryChartSpec(chart("line"), setup(), COLOURS))[0].encoding.y.stack).toBeNull();
    const over = layers(queryChartSpec(chart("area"), setup("side_by_side"), COLOURS))[0];
    expect(over.encoding.y.stack).toBeNull();
    expect(over.mark.opacity).toBe(0.45);
    const dots = layers(queryChartSpec(chart("scatter", true, "number"), setup(), COLOURS))[0];
    expect(dots.mark.type).toBe("point");
    expect(dots.encoding.x.type).toBe("quantitative");
  });

  it("draws one series in the theme's own colour, with no legend to read", () => {
    const [bars] = layers(queryChartSpec(chart("bar", false), setup(), COLOURS));
    expect(bars.encoding.color).toBeUndefined();
    expect(bars.encoding.y.stack).toBeNull();
  });

  it("labels a stack by its total at the last date only, and each bar along categories", () => {
    const dated = layers(queryChartSpec(chart("bar"), setup("stacked", true), COLOURS));
    expect(dated).toHaveLength(2);
    expect(dated[1].transform?.[0]).toEqual({ filter: { field: "x", equal: xText(DAYS[2], "date", "day") } });
    expect(dated[1].transform?.[1]).toEqual({ aggregate: [{ op: "sum", field: "v", as: "total" }], groupby: ["x"] });
    const kinds = layers(queryChartSpec(chart("bar", true, "text"), setup("stacked", true), COLOURS));
    expect(kinds[1].transform).toEqual([{ aggregate: [{ op: "sum", field: "v", as: "total" }], groupby: ["x"] }]);
    expect(kinds[0].encoding.x.sort).toEqual({ op: "sum", field: "v", order: "descending" });
    expect(layers(queryChartSpec(chart("bar"), setup("shares", true), COLOURS))).toHaveLength(1);   // a share needs no number
  });

  it("says a day by its month and day — the year only where the chart spans two — lays its legend flat, and keeps numbers short", () => {
    const one = queryChartSpec(chart("bar"), setup("stacked", true), COLOURS);
    expect((one.data as { values: { x: string }[] }).values.map(v => v.x).slice(0, 1)).toEqual(["Oct 8"]);
    const span = chart("bar");
    span.points = [{ x: "2025-12-31", s: "China", v: 1 }, { x: "2026-01-01", s: "China", v: 2 }];
    expect((queryChartSpec(span, setup(), COLOURS).data as { values: { x: string }[] }).values[0].x).toMatch(/2025/);
    const [bars, label] = layers(one);
    expect((bars.encoding.color.legend as { direction: string }).direction).toBe("horizontal");
    expect((bars.encoding.y.axis as { format: string }).format).toBe(".3~s");
    expect(label.encoding.text.format).toBe(".3~s");
  });

  it("gives Other the grey wherever it sits, and the series their colours in order", () => {
    expect(seriesColours(["a", "Other", "b"], COLOURS)).toEqual(["#c1", "#grey", "#c2"]);
  });
});
