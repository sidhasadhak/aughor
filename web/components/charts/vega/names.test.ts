/**
 * The Daily Briefing's chart, 2026-11-06: a legend of "r28 · r29" over an axis called "Value".
 * The fixture is that run's own grid; the names are what `series_names.py` reads from its SQL.
 */
import { describe, expect, it } from "vitest";

import { applyNames, namesOf } from "@/components/charts/vega/names";
import { resolveVegaSpec } from "@/components/charts/vega/resolveSpec";

const columns = ["category", "r29", "r28"];
const rows = [
  ["Outerwear & Coats", 3000.36, 12737.46], ["Jeans", 3130.27, 9743.79], ["Sweaters", 2669.22, 7730.77],
  ["Active", 1222.21, 4461.41], ["Tops & Tees", 1140.2, 4182.75],
];
const names = { labels: { r28: "Oct 28", r29: "Oct 29" }, y_title: "Revenue" };

describe("names over a resolved spec", () => {
  it("relabels the folded series and titles the axis, keeping the columns the resolver read", () => {
    const plain = resolveVegaSpec({ columns, rows, chartType: "auto" });
    const named = resolveVegaSpec({ columns, rows, chartType: "auto", names });
    expect(plain && named).toBeTruthy();
    expect(named!.resolved).toBe(plain!.resolved);                 // the same picture, chosen the same way
    const tf = (named!.spec as { transform: Record<string, unknown>[] }).transform;
    const fold = tf.findIndex((t) => Array.isArray(t.fold));
    expect([...(tf[fold].fold as string[])].sort()).toEqual(["r28", "r29"]);   // columns untouched
    expect(String(tf[fold + 1].calculate)).toContain('"Oct 28"');
    const y = (named!.spec as { encoding: { y: { axis: { title: string } } } }).encoding.y.axis.title;
    expect(y).toBe("Revenue");
    const yPlain = (plain!.spec as { encoding: { y: { axis: { title: string } } } }).encoding.y.axis.title;
    expect(yPlain).toBe("Value");
  });

  it("names a single measure's axis by its label", () => {
    const one = resolveVegaSpec({ columns: ["category", "rev"], rows: rows.map((r) => [r[0], r[2]]),
                                  chartType: "bar", names: { labels: { rev: "Revenue" } } });
    const enc = (one!.spec as { encoding: Record<string, { axis?: { title?: string } }> }).encoding;
    expect(Object.values(enc).some((c) => c.axis?.title === "Revenue")).toBe(true);
  });

  it("is a no-op without names, and reads names off a chart config defensively", () => {
    const spec = { title: "t", encoding: { y: { field: "v", axis: { title: "V" } } } };
    expect(applyNames(spec, null)).toBe(spec);
    expect(namesOf({ names: { labels: { r28: "Oct 28", bad: 3 }, y_title: "" } })).toEqual({ labels: { r28: "Oct 28" }, y_title: null });
    expect(namesOf({})).toBeNull();
    expect(namesOf(null)).toBeNull();
  });
});
