/**
 * Band fit: the chart takes the row; the bars stay readable (2026-11-06, the user's screenshot of a
 * four-platform grouped bar drawn at 670px with the rest of the row empty).
 */
import { describe, expect, it } from "vitest";
import * as vl from "vega-lite";

import { BASE_BAND_PADDING, MAX_BAND_PADDING, MAX_BAR_PX, PLOT_CHROME_PX, bandPaddingFor, barsPerBand, withBandPadding } from "./bandFit";

describe("bandPaddingFor", () => {
  it("leaves a crowded chart at Vega-Lite's default", () => {
    expect(bandPaddingFor(800, 20, 1)).toBeNull();
    expect(bandPaddingFor(0, 4, 2)).toBeNull();
    expect(bandPaddingFor(1200, 0, 1)).toBeNull();
  });

  it("widens the gaps so no bar is thicker than the cap", () => {
    // The screenshot's case at a wide desktop: four platforms, two measures each.
    const w = 1700, bands = 4, per = 2;
    const p = bandPaddingFor(w, bands, per)!;
    expect(p).toBeGreaterThan(BASE_BAND_PADDING);
    const bar = ((w - PLOT_CHROME_PX) / bands) * (1 - p) / per;
    expect(bar).toBeLessThanOrEqual(MAX_BAR_PX + 1);
  });

  it("never lets the gap take more than its share", () => {
    expect(bandPaddingFor(4000, 2, 1)).toBe(MAX_BAND_PADDING);
  });
});

describe("barsPerBand", () => {
  it("counts the folded measures of a grouped bar", () => {
    const spec = { transform: [{ fold: ["yoy_pct", "mom_pct"], as: ["__measure", "__value"] }],
                   encoding: { xOffset: { field: "__measure" } } };
    expect(barsPerBand(spec, [], [])).toBe(2);
  });
  it("counts the series values when a column is the series", () => {
    const spec = { encoding: { xOffset: { field: "region" } } };
    expect(barsPerBand(spec, ["month", "region", "rev"], [["a", "EU", 1], ["a", "US", 2], ["b", "EU", 3]])).toBe(2);
  });
  it("is one without a group", () => {
    expect(barsPerBand({ encoding: { x: { field: "p" } } }, ["p"], [["a"]])).toBe(1);
  });
});

describe("withBandPadding", () => {
  it("compiles to a bar band scale with the padding, and leaves the offset scale alone", () => {
    const spec = {
      data: { values: [{ p: "A", m: "x", v: 1 }, { p: "A", m: "y", v: 2 }, { p: "B", m: "x", v: 3 }, { p: "B", m: "y", v: 4 }] },
      mark: "bar",
      encoding: { x: { field: "p", type: "nominal" }, xOffset: { field: "m" }, y: { field: "v", type: "quantitative" } },
      width: 1200, height: 300,
    };
    const out = vl.compile(withBandPadding(spec, 0.45) as unknown as Parameters<typeof vl.compile>[0]).spec;
    const scales = (out.scales ?? []) as { name: string; paddingInner?: number }[];
    expect(scales.find((s) => s.name === "x")?.paddingInner).toBe(0.45);
    expect(scales.find((s) => s.name === "xOffset")?.paddingInner ?? 0).toBe(0);
  });
  it("is the same spec when there is nothing to change", () => {
    const spec = { mark: "bar" };
    expect(withBandPadding(spec, null)).toBe(spec);
  });
});
