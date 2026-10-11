/**
 * A card of a person's own query, drawn as they set it up (Arc AP-7; ROADMAP §3.57, the study's §9) — as Vega-Lite,
 * from the points the server shaped (`aughor/cockpit/queries.py`): one point per bucket and series, the top values of a
 * split and the rest as Other. Bars stack, stand side by side or show shares; a line never stacks; an area stacks or
 * shows shares; a scatter places each point by two numbers. Dates along the bottom are said by the bucket they are in.
 *
 * Colours are the chart theme's, in a fixed order: the first series takes the first colour, Other the theme's grey — a
 * series keeps its colour whatever the reader narrows, and Other never wears a series' colour.
 */
import type { QueryShaped, QueryShown } from "@/lib/api";
import { dayLabel } from "@/lib/cockpit/objectView";
import { fmtDate, type Gran } from "@/lib/format";

type QueryChart = Extract<QueryShaped, { as: "bar" | "line" | "area" | "scatter" }>;

export interface ChartColours { palette: string[]; other: string }

const GRAN: Record<string, Gran> = { day: "day", week: "week", month: "month", quarter: "quarter", year: "year" };

/** What a point's place along the bottom is called: a day or a week by the day it starts on — "Oct 9", the year said
 *  only where the chart spans more than one — a month, a quarter or a year as such; anything else as it is. */
export function xText(x: unknown, kind: string, bucket: string, manyYears = false): string | number | null {
  if (x === null || x === undefined) return null;
  if (kind === "date" || kind === "time") {
    const day = String(x).slice(0, 10);
    const gran = GRAN[bucket] ?? "day";
    return (gran === "day" || gran === "week") && !manyYears ? dayLabel(day) : fmtDate(day, gran);
  }
  return typeof x === "number" ? x : String(x);
}

/** The colour of each series, in order — Other the theme's grey. */
export function seriesColours(series: string[], colours: ChartColours): string[] {
  let k = 0;
  return series.map(s => (s === "Other" ? colours.other : colours.palette[k++ % colours.palette.length]));
}

export function queryChartSpec(c: QueryChart, setup: Pick<QueryShown, "segments" | "labels" | "running">,
  colours: ChartColours): Record<string, unknown> {
  const temporal = c.x.kind === "date" || c.x.kind === "time";
  const manyYears = temporal && new Set(c.points.map(p => String(p.x ?? "").slice(0, 4))).size > 1;
  const values = c.points.map(p => ({ x: xText(p.x, c.x.kind, c.x.bucket, manyYears), s: p.s || "", v: p.v }));
  const split = c.series.length > 1 || (c.series.length === 1 && c.series[0] !== "");
  const named = c.series.filter(s => s !== "");
  const color = split
    ? { color: { field: "s", type: "nominal", sort: named, title: null,
        scale: { domain: named, range: seriesColours(named, colours) },
        legend: { orient: "top", direction: "horizontal", title: null, symbolType: "square", labelLimit: 140 } } }
    : {};
  const numericX = c.x.kind === "number";
  const bars = c.as === "bar";
  // a category along the bottom reads largest first; dates and numbers in their own order
  const xSort = c.x.kind === "text" && bars && !setup.running ? { op: "sum", field: "v", order: "descending" } : null;
  const x = {
    field: "x",
    type: c.as === "scatter" && numericX ? "quantitative" : "ordinal",
    sort: xSort,
    axis: { title: null, labelAngle: 0, labelOverlap: "parity", ticks: false },
    ...(c.as === "scatter" && numericX ? { scale: { zero: false } } : {}),
  };
  const shares = setup.segments === "shares" && (c.as === "bar" || c.as === "area");
  const stack = c.as === "line" || c.as === "scatter" || !split ? null
    : shares ? "normalize" : setup.segments === "side_by_side" ? null : "zero";
  const y = {
    field: "v", type: "quantitative", stack, title: null,
    axis: { title: null, tickCount: 4, ...(shares ? { format: ".0%" } : { format: ".3~s" }) },
    ...(c.as === "scatter" ? { scale: { zero: false } } : {}),
  };
  const tooltip = [
    { field: "x", title: "Along the bottom" },
    ...(split ? [{ field: "s", title: "Series" }] : []),
    { field: "v", type: "quantitative", title: "Value", format: ",.2~f" },
  ];
  const mark = bars ? { type: "bar", tooltip: true, cornerRadiusEnd: 2 }
    : c.as === "line" ? { type: "line", tooltip: true, strokeWidth: 2 }
      : c.as === "area" ? { type: "area", tooltip: true, ...(stack === null && split ? { opacity: 0.45 } : {}) }
        : { type: "point", tooltip: true, filled: true, size: 36 };
  const encoding: Record<string, unknown> = {
    x, y, ...color, tooltip,
    ...(bars && split && setup.segments === "side_by_side" ? { xOffset: { field: "s", sort: named } } : {}),
  };
  const layer: Record<string, unknown>[] = [{ mark, encoding }];
  if (setup.labels && !shares && c.as !== "scatter") {
    // labels are selective: along dates or numbers only the last place is labelled — a stack by its total, a line or a
    // side-by-side bar by each series' value there; along categories each bar is
    const lastX = temporal || numericX ? values.at(-1)?.x : undefined;
    const only = lastX !== undefined && lastX !== null ? [{ filter: { field: "x", equal: lastX } }] : [];
    // side by side, a label for each series sat on a bar a few pixels wide, over its neighbours' (seen on theLook,
    // 2026-10-11): only the highest at each labelled place says its number
    const lead = bars && split && setup.segments === "side_by_side"
      ? [{ window: [{ op: "rank", as: "at" }], sort: [{ field: "v", order: "descending" }], groupby: ["x"] }, { filter: "datum.at === 1" }] : [];
    layer.push(bars && stack === "zero"
      ? { transform: [...only, { aggregate: [{ op: "sum", field: "v", as: "total" }], groupby: ["x"] }],
        mark: { type: "text", dy: -6, fontSize: 10.5 },
        encoding: { x: { field: "x", type: x.type, sort: xSort }, y: { field: "total", type: "quantitative" },
          text: { field: "total", type: "quantitative", format: ".3~s" } } }
      : { transform: [...only, ...lead], mark: { type: "text", dy: -6, fontSize: 10.5 },
        encoding: { x, y: { field: "v", type: "quantitative", stack }, text: { field: "v", type: "quantitative", format: ".3~s" },
          ...(bars && split && setup.segments === "side_by_side" ? { xOffset: { field: "s", sort: named } } : {}) } });
  }
  return { $schema: "https://vega.github.io/schema/vega-lite/v5.json", background: null, data: { values }, layer };
}
