/**
 * transform.test.ts — do the declarative transforms compute the SAME numbers as the API?
 *
 * The four post-processing ops move from a POST to /query/postproc into the chart's own
 * dataflow. That is only an improvement if the numbers are identical, so this does not check
 * the shape of the transform blocks — it RUNS them through Vega and compares every value
 * against a direct port of aughor/tools/postproc.py's semantics, edge cases included.
 */

import { describe, expect, it } from "vitest";
import * as vl from "vega-lite";
import { View, parse } from "vega";
import { resolveVegaSpec, type TransformSpec } from "@/components/charts/vega/resolveSpec";

/** Reference implementations — a direct port of aughor/tools/postproc.py. */
const ref = {
  pop: (v: (number | null)[]) =>
    v.map((cur, i) => {
      if (i === 0) return null;
      const prev = v[i - 1];
      return prev === null || cur === null || prev === 0 ? null : (cur - prev) / prev;
    }),
  contribution: (v: (number | null)[]) => {
    const total = v.reduce<number>((a, x) => a + (x ?? 0), 0);
    return total === 0 ? v.map(() => null) : v.map((x) => (x === null ? null : x / total));
  },
  rolling: (v: (number | null)[], w: number) =>
    v.map((_, i) => {
      if (i + 1 < w) return null;
      const win = v.slice(i + 1 - w, i + 1);
      if (win.some((x) => x === null)) return null;
      return (win as number[]).reduce((a, b) => a + b, 0) / w;
    }),
  cumulative: (v: (number | null)[]) => {
    let running = 0;
    return v.map((x) => (running += x ?? 0));
  },
};

/** Compile the spec, run its dataflow headlessly, and read back the transformed rows. */
async function runTransform(rows: unknown[][], t: TransformSpec): Promise<(number | null)[]> {
  const spec = resolveVegaSpec({ columns: ["day", "revenue"], rows, chartType: "line", transform: t });
  expect(spec).not.toBeNull();
  const compiled = vl.compile({ ...spec!.spec, width: 400, height: 200 } as Parameters<typeof vl.compile>[0]).spec;
  const view = new View(parse(compiled), { renderer: "none" });
  await view.runAsync();
  const derived: string =
    t.op === "pop" ? "revenue_pct_change"
    : t.op === "contribution" ? "revenue_pct_of_total"
    : t.op === "rolling" ? `revenue_rolling_${t.agg ?? "mean"}${t.window ?? 3}`
    : "revenue_cumulative";
  // NOT "source_0" — that is the raw parsed input, before any transform. Vega-Lite emits the
  // transformed rows into a derived dataset (data_0, data_1, …) whose numbering depends on
  // the spec's shape, so find the one that actually carries the column rather than guessing.
  const names = ((compiled.data ?? []) as { name: string }[]).map((d) => d.name);
  const holder = names.find((n) => {
    const rowsOut = view.data(n) as Record<string, unknown>[] | undefined;
    return Array.isArray(rowsOut) && rowsOut.length > 0 && derived in rowsOut[0];
  });
  expect(holder, `no compiled dataset carries ${derived} (saw ${names.join(", ")})`).toBeDefined();
  const out = (view.data(holder!) as Record<string, unknown>[]).map((d) => {
    const x = d[derived];
    return x === undefined || x === null || Number.isNaN(x) ? null : Number(x);
  });
  view.finalize();
  return out;
}

const close = (a: (number | null)[], b: (number | null)[]) => {
  expect(a.length).toBe(b.length);
  a.forEach((x, i) => {
    if (x === null || b[i] === null) expect(x).toBe(b[i]);
    else expect(x).toBeCloseTo(b[i]!, 9);
  });
};

const days = (n: number) => Array.from({ length: n }, (_, i) => `2024-01-${String(i + 1).padStart(2, "0")}`);
const table = (vals: (number | null)[]) => days(vals.length).map((d, i) => [d, vals[i]] as unknown[]);

describe("declarative transforms match aughor/tools/postproc.py", () => {
  const plain: (number | null)[] = [100, 120, 90, 90, 150, 210, 60];
  const withNull: (number | null)[] = [100, null, 90, 120, null, 210, 60];
  const withZero: (number | null)[] = [0, 120, 90, 0, 150, 210, 60];

  it.each([["plain", plain], ["with a null", withNull], ["with a zero", withZero]])(
    "period-over-period, %s", async (_n, vals) => {
      close(await runTransform(table(vals), { op: "pop", valueCol: "revenue" }), ref.pop(vals));
    });

  it.each([["plain", plain], ["with a null", withNull]])("share of total, %s", async (_n, vals) => {
    close(await runTransform(table(vals), { op: "contribution", valueCol: "revenue" }), ref.contribution(vals));
  });

  it("share of total is all null when the total is zero", async () => {
    const zeros: (number | null)[] = [0, 0, 0];
    close(await runTransform(table(zeros), { op: "contribution", valueCol: "revenue" }), ref.contribution(zeros));
  });

  it.each([2, 3, 4])("rolling mean, window %i — null until the window fills", async (w) => {
    close(await runTransform(table(plain), { op: "rolling", valueCol: "revenue", window: w }), ref.rolling(plain, w));
  });

  it("rolling is null wherever a point INSIDE the window is missing", async () => {
    const got = await runTransform(table(withNull), { op: "rolling", valueCol: "revenue", window: 3 });
    close(got, ref.rolling(withNull, 3));
    // The null at index 1 must poison indexes 1..3, not just its own row.
    expect(got.slice(0, 4)).toEqual([null, null, null, null]);
  });

  it.each([["plain", plain], ["with a null", withNull]])("cumulative, %s", async (_n, vals) => {
    close(await runTransform(table(vals), { op: "cumulative", valueCol: "revenue" }), ref.cumulative(vals));
  });

  it("plots the derived column, not the original", async () => {
    const spec = resolveVegaSpec({ columns: ["day", "revenue"], rows: table(plain), chartType: "line",
                                   transform: { op: "cumulative", valueCol: "revenue" } })!;
    const enc = (spec.spec as { encoding: { y: { field: string } } }).encoding;
    expect(enc.y.field).toBe("revenue_cumulative");
  });
});
