/**
 * parity.test.ts — the Phase 2 regression harness.
 *
 * The design doc proposed replaying all 703 persisted charts through both engines and
 * diffing screenshots. That is not executable: a persisted chat_answer keeps `sql` and
 * `row_count` and NOT its rows, so replaying would mean re-running 703 queries against
 * warehouses that may no longer exist, non-deterministically. A fixture matrix is what is
 * left, and it is the better instrument anyway — deterministic, no warehouse, runs in CI,
 * and it catches the class of defect that broke Phase 1: a chart that renders a perfectly
 * plausible picture of the wrong thing. A screenshot diff would have passed that.
 *
 * The matrix is the six types the ledger says are ~99% of traffic, crossed with the shapes
 * that actually break charts: one row, one category, many categories, negatives, nulls,
 * long labels, multi-year dates, and data that has no honest chart at all.
 */

import { describe, expect, it } from "vitest";
import { resolveVegaSpec } from "@/components/charts/vega/resolveSpec";
import { resolveChartOption } from "@/components/charts/resolveOption";

interface Fixture {
  name: string;
  hint: string;
  columns: string[];
  rows: unknown[][];
  /** True when the data has no honest chart and BOTH engines must refuse it. */
  refuses?: boolean;
  /** True when tier 1 does not draw this type: Vega must refuse so the seam falls back to
   *  ECharts, which must still draw it. The matrix originally held only SUPPORTED types,
   *  which is exactly why it passed while a scatter was silently rendering as a bar. */
  unsupported?: boolean;
}

const months = (n: number, startYear = 2024): string[] =>
  Array.from({ length: n }, (_, i) => `${startYear + Math.floor(i / 12)}-${String((i % 12) + 1).padStart(2, "0")}`);

const FIXTURES: Fixture[] = [
  { name: "ranking, 8 categories", hint: "bar_horizontal", columns: ["category", "gmv"],
    rows: [["Apparel", 4.2e6], ["Electronics", 3.1e6], ["Home", 2.4e6], ["Beauty", 1.8e6],
           ["Grocery", 1.5e6], ["Toys", 9e5], ["Sports", 7.2e5], ["Books", 4.1e5]] },

  { name: "ranking, single category", hint: "bar_horizontal", columns: ["region", "revenue"],
    rows: [["North", 120_000]] },

  { name: "ranking, 50 categories", hint: "bar_horizontal", columns: ["sku", "units"],
    rows: Array.from({ length: 50 }, (_, i) => [`SKU-${i}`, 1000 - i * 17]) },

  { name: "ranking with negatives", hint: "bar_horizontal", columns: ["region", "delta"],
    rows: [["North", 120_000], ["South", -90_000], ["East", 45_000], ["West", -12_000]] },

  { name: "ranking with a null measure", hint: "bar_horizontal", columns: ["region", "revenue"],
    rows: [["North", 120_000], ["South", null], ["East", 45_000]] },

  { name: "ranking with long labels", hint: "bar_horizontal", columns: ["merchant", "gmv"],
    rows: [["A very long merchant name that will not fit on one line", 4.2e6],
           ["Another extremely long merchant name for good measure", 3.1e6]] },

  { name: "trend, 8 months", hint: "line", columns: ["month", "revenue"],
    rows: months(8).map((m, i) => [m, 120_000 + i * 28_000]) },

  { name: "trend crossing a year boundary", hint: "line", columns: ["month", "revenue"],
    rows: months(30).map((m, i) => [m, 100_000 + i * 5_000]) },

  { name: "trend by series", hint: "multi_line", columns: ["month", "region", "revenue"],
    rows: months(6).flatMap((m, i) => ["North", "South", "East"].map((r, ri) => [m, r, 30_000 + ri * 18_000 + i * 6_000])) },

  { name: "headline number", hint: "counter", columns: ["net_revenue"], rows: [[8_660_000]] },

  { name: "part to whole", hint: "pie", columns: ["method", "amount"],
    rows: [["Card", 5.4e6], ["Wallet", 2.9e6], ["BNPL", 1.3e6]] },

  { name: "vertical bar over time", hint: "bar", columns: ["month", "orders"],
    rows: months(6).map((m, i) => [m, 400 + i * 30]) },

  { name: "no rows", hint: "bar", columns: ["category", "gmv"], rows: [], refuses: true },
  { name: "no columns", hint: "bar", columns: [], rows: [], refuses: true },

  // Types tier 1 does NOT draw. Each must be refused, not approximated.
  { name: "scatter", hint: "scatter", columns: ["revenue", "profit"],
    rows: [[9e5, 1.8e5], [1.1e6, 2.2e5], [1.3e6, 2.6e5]], unsupported: true },
  { name: "heatmap", hint: "heatmap", columns: ["day", "hour", "orders"],
    rows: [["Mon", "09", 12], ["Mon", "10", 18], ["Tue", "09", 7]], unsupported: true },
  { name: "treemap", hint: "treemap", columns: ["category", "gmv"],
    rows: [["Apparel", 4.2e6], ["Home", 2.4e6]], unsupported: true },
  { name: "histogram", hint: "histogram", columns: ["order_value"],
    rows: [[12], [18], [25], [31], [44], [52], [63]], unsupported: true },
  { name: "waterfall", hint: "waterfall", columns: ["step", "delta"],
    rows: [["Open", 100], ["Won", 40], ["Lost", -25]], unsupported: true },
  { name: "funnel", hint: "funnel", columns: ["stage", "count"],
    rows: [["Visit", 1000], ["Cart", 300], ["Buy", 90]], unsupported: true },
];

/** Every leaf of a Vega-Lite spec must survive JSON — a function cannot be persisted. */
function functionPaths(node: unknown, path = "$"): string[] {
  if (typeof node === "function") return [path];
  if (Array.isArray(node)) return node.flatMap((v, i) => functionPaths(v, `${path}[${i}]`));
  if (node && typeof node === "object") {
    return Object.entries(node).flatMap(([k, v]) => functionPaths(v, `${path}.${k}`));
  }
  return [];
}

describe("Vega tier-1 resolver", () => {
  it.each(FIXTURES)("$name — agrees with ECharts on whether a chart is honest", (f) => {
    const vega = resolveVegaSpec({ columns: f.columns, rows: f.rows, chartType: f.hint });
    const echarts = resolveChartOption({ columns: f.columns, rows: f.rows, chartType: f.hint });
    if (f.refuses) {
      expect(vega).toBeNull();
      expect(echarts).toBeNull();
      return;
    }
    if (f.unsupported) {
      // Tier 1 must decline, and the outgoing engine must still draw it — that pair is
      // what makes the fallback a fallback instead of a hole in the product.
      expect(vega).toBeNull();
      expect(echarts).not.toBeNull();
      return;
    }
    // A refusal on one engine and a chart on the other is the migration's worst failure
    // mode: the answer silently loses (or gains) its chart when the engine flips.
    expect(vega === null).toBe(echarts === null);
  });

  it.each(FIXTURES.filter((f) => !f.refuses && !f.unsupported))("$name — emits pure JSON, no functions", (f) => {
    const v = resolveVegaSpec({ columns: f.columns, rows: f.rows, chartType: f.hint });
    expect(v).not.toBeNull();
    expect(functionPaths(v!.spec)).toEqual([]);
    // The round trip is the real test: this is what persisting a spec would do to it.
    expect(JSON.parse(JSON.stringify(v!.spec))).toEqual(v!.spec);
  });

  it.each(FIXTURES.filter((f) => !f.refuses && !f.unsupported))("$name — bakes no colour into the spec", (f) => {
    const v = resolveVegaSpec({ columns: f.columns, rows: f.rows, chartType: f.hint });
    // The 2026-06 exit from Vega-Lite was caused by colours being walked into a produced
    // spec. A stored spec must carry NO colour at all: the theme arrives as `config` at
    // render time, which is what lets a spec from March follow today's tokens.
    expect(JSON.stringify(v!.spec)).not.toMatch(/#[0-9a-f]{3,8}\b/i);
  });

  it("renders a ranking horizontally and a trend vertically, like the ECharts path", () => {
    const ranking = resolveVegaSpec({ columns: ["category", "gmv"], rows: [["A", 2], ["B", 1]], chartType: "bar" });
    expect(ranking!.resolved).toBe("bar_horizontal");

    const overTime = resolveVegaSpec({ columns: ["month", "orders"], rows: [["2024-01", 5], ["2024-02", 7]], chartType: "bar" });
    expect(overTime!.resolved).toBe("bar");

    const forced = resolveVegaSpec({ columns: ["category", "gmv"], rows: [["A", 2], ["B", 1]], chartType: "bar_vertical" });
    expect(forced!.resolved).toBe("bar");
  });

  it("lets the user override orientation, on BOTH engines", () => {
    const columns = ["category", "gmv"];
    const rows = [["Apparel", 4.2e6], ["Home", 2.4e6]];

    // A ranking defaults to horizontal on both engines.
    expect(resolveVegaSpec({ columns, rows, chartType: "bar" })!.resolved).toBe("bar_horizontal");

    // Forcing vertical must move the measure to the y axis, not merely record a preference.
    const vega = resolveVegaSpec({ columns, rows, chartType: "bar", orient: "vertical" })!;
    expect(vega.resolved).toBe("bar");
    const enc = (vega.spec as { encoding: Record<string, { field: string }> }).encoding;
    expect(enc.y.field).toBe("gmv");
    expect(enc.x.field).toBe("category");

    // And the same override has to reach the ECharts path, or the control lies whenever the
    // engine flag is off — which is every surface today.
    const axisType = (o: unknown, k: "xAxis" | "yAxis") => {
      const ax = (o as Record<string, unknown>)[k];
      return (Array.isArray(ax) ? ax[0] : ax) as { type?: string } | undefined;
    };
    const eH = resolveChartOption({ columns, rows, chartType: "bar", custom: { orient: "horizontal" } })!;
    expect(axisType(eH.option, "xAxis")?.type).toBe("value");

    const eV = resolveChartOption({ columns, rows, chartType: "bar", custom: { orient: "vertical" } })!;
    expect(axisType(eV.option, "yAxis")?.type).toBe("value");
  });

  it("gives a multi-series trend one line per series, not one line through every point", () => {
    const f = FIXTURES.find((x) => x.name === "trend by series")!;
    const v = resolveVegaSpec({ columns: f.columns, rows: f.rows, chartType: f.hint });
    const enc = (v!.spec as { encoding: { color?: { field?: string; sort?: unknown } } }).encoding;
    expect(enc.color?.field).toBe("region");
    // Data order, not alphabetical: otherwise a series changes hue between engines.
    expect(enc.color?.sort).toBeNull();
  });

  it("keeps the year on a trend that crosses one", () => {
    const f = FIXTURES.find((x) => x.name === "trend crossing a year boundary")!;
    const v = resolveVegaSpec({ columns: f.columns, rows: f.rows, chartType: f.hint });
    const x = (v!.spec as { encoding: { x: { axis?: { format?: string } } } }).encoding.x;
    expect(x.axis?.format).toBe("%b %Y");
  });
});
