/**
 * A breakdown's rows (the Grist study §10): the largest groups, the rest folded into Other, the objects with no value
 * their own row — and the check that they add up to the whole, which a breakdown says rather than assumes.
 */
import { describe, expect, it } from "vitest";

import { breakdownGaps, foldBreakdown, pathWords, type BreakdownMeasure } from "@/lib/dashboards/objectView";

const COUNT_SUM: BreakdownMeasure[] = [{ agg: "count" }, { agg: "sum", path: "revenue" }];
const ROWS: unknown[][] = [["China", "40", "400"], ["Brasil", "30", "300"], [null, "5", "50"], ["Spain", "20", "200"], ["Peru", "10", "100"]];

describe("folding a breakdown's groups", () => {
  it("keeps the largest with a value, sums the rest into Other, and keeps the objects with no value", () => {
    const rows = foldBreakdown(ROWS, 2, COUNT_SUM, null, true);
    expect(rows.map(r => [r.kind, r.value, r.values, r.groups])).toEqual([
      ["group", "China", [40, 400], 1], ["group", "Brasil", [30, 300], 1],
      ["other", "", [30, 300], 2], ["none", "", [5, 50], 1],
    ]);
    expect(breakdownGaps(rows, [105, 1050], COUNT_SUM)).toEqual([]);
  });

  it("asks the door for what does not add — an average — and for all of Other when the groups read are not all", () => {
    const avg: BreakdownMeasure[] = [{ agg: "count" }, { agg: "avg", path: "revenue" }];
    expect(foldBreakdown(ROWS, 2, avg, [33, 9.5], true).find(r => r.kind === "other")?.values).toEqual([30, 9.5]);
    expect(foldBreakdown(ROWS, 2, COUNT_SUM, [999, 9999], false).find(r => r.kind === "other")?.values).toEqual([999, 9999]);
    // no Other row when every group with a value is shown
    expect(foldBreakdown(ROWS, 9, COUNT_SUM, null, true).some(r => r.kind === "other")).toBe(false);
  });

  it("finds the measures whose rows do not add up to the whole, and checks no average", () => {
    const rows = foldBreakdown(ROWS, 2, COUNT_SUM, null, true);
    expect(breakdownGaps(rows, [106, 1050], COUNT_SUM)).toEqual([0]);
    expect(breakdownGaps(rows, [105, 1049], COUNT_SUM)).toEqual([1]);
    expect(breakdownGaps(rows, [1, 1], [{ agg: "avg", path: "x" }, { agg: "max", path: "y" }])).toEqual([]);
  });

  it("says a property path in words, and the link it is read through", () => {
    expect(pathWords("placed_by.country")).toEqual({ label: "Country", via: "Placed by" });
    expect(pathWords("status")).toEqual({ label: "Status", via: "" });
  });
});
